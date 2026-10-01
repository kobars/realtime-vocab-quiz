# AI-ASSISTED: the HTTP edge: mock sessions and tickets, quiz info, mock admin, probes, metrics.
"""HTTP routes of docs/spec/protocol.md §8 plus the operator endpoints.

MOCK: ``POST /sessions`` and ``POST /tickets`` stand in for an identity provider, and the
``/admin`` routes for a quiz admin service; they exist only with ``ADMIN_MOCK=1``, stay out of the
OpenAPI page, and answer any request under ``/admin`` without the right ``X-Admin-Token`` before
routing, with the 404 of a path that does not exist (no 405, no 422 that would give them away).
Every error body is ``{error, message}``. Every request logs one JSON line with its
``request_id`` and, when it names one, its ``quiz_id``.
"""

import hmac
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated

import structlog
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint

from quiz.adapters.http import models as h
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.obs import metrics
from quiz.ports.questions import QuestionBank
from quiz.ports.store import Store
from quiz.ports.tickets import TicketStore

QUIZ_ID, REQUEST_ID = re.compile(r"[A-Z0-9-]{3,16}"), re.compile(r"[A-Za-z0-9_.-]{1,64}")
STATUS = {ErrorCode.QUIZ_NOT_FOUND: 404, ErrorCode.INVALID_STATE: 409, ErrorCode.UNAVAILABLE: 503}
NOT_FOUND = "no such quiz"  # one body for every unknown ID: no hint whether it ever existed
log = structlog.get_logger("quiz.http")


@dataclass(frozen=True, slots=True)
class HttpDeps:
    store: Store
    tickets: TicketStore
    bank: QuestionBank
    ready: Callable[[], Awaitable[bool]]  # the store answers
    ticket_ttl_ms: int
    admin_token: str | None = None  # None: no admin routes
    outages: tuple[type[Exception], ...] = (ConnectionError, TimeoutError)  # -> 503


def _quiz(request: Request, quiz_id: str) -> None:
    """Tag this request's log lines with the quiz it names."""
    request.state.quiz_id = quiz_id  # for the request line, logged outside the handler's context
    structlog.contextvars.bind_contextvars(quiz_id=quiz_id)


async def _info(deps: HttpDeps, quiz_id: str) -> h.QuizInfo:
    questions = await deps.bank.questions(quiz_id) if QUIZ_ID.fullmatch(quiz_id) else None
    if questions is None:
        raise DomainError(ErrorCode.QUIZ_NOT_FOUND, NOT_FOUND)
    page = await deps.store.standings_page(quiz_id, 0, 1)  # status from the clock alone
    return h.QuizInfo(
        quizId=quiz_id,
        title=await deps.bank.title(quiz_id) or quiz_id,
        questionCount=len(questions),
        status="ended" if page.final else "open",
        players=page.player_count,
    )


def _public(deps: HttpDeps) -> APIRouter:
    api = APIRouter()
    text = {"content": {"text/plain": {"example": "# TYPE ws_connections gauge\n"}}}

    @api.post("/sessions", status_code=201, tags=["MOCK identity"])
    async def create_session(body: h.SessionIn) -> h.SessionOut:
        """MOCK: create an anonymous user and its session token (kept in the browser tab)."""
        identity, token = await deps.tickets.create_session(body.displayName)
        return h.SessionOut(userId=identity.user_id, sessionToken=token)

    @api.post(
        "/tickets", status_code=201, tags=["MOCK identity"], responses={401: {"model": h.Problem}}
    )
    async def create_ticket(
        authorization: Annotated[str, Header(examples=["Bearer mF3x…"])] = "",
    ) -> h.TicketOut:
        """MOCK: a single-use ticket for ``GET /ws?ticket=…``, valid 30 s."""
        scheme, _, token = authorization.partition(" ")
        token = token.lstrip(" ")  # the scheme is case-insensitive (RFC 7235); the token is not
        bearer = scheme.lower() == "bearer" and token
        ticket = await deps.tickets.issue_ticket(token) if bearer else None
        if ticket is None:
            raise HTTPException(401, "unknown session", headers={"WWW-Authenticate": "Bearer"})
        return h.TicketOut(ticket=ticket, expiresInMs=deps.ticket_ttl_ms)

    @api.get("/quizzes/{quiz_id}", tags=["quizzes"], responses={404: {"model": h.Problem}})
    async def quiz_info(request: Request, quiz_id: str) -> h.QuizInfo:
        """Public information about a quiz; ``ended`` from its deadline, whoever is connected."""
        _quiz(request, quiz_id)
        return await _info(deps, quiz_id)

    @api.get("/healthz", tags=["operations"])
    async def healthz() -> h.Status:
        """Liveness: the process answers HTTP."""
        return h.Status(status="ok")

    @api.get("/readyz", tags=["operations"], responses={503: {"model": h.Status}})
    async def readyz(response: Response) -> h.Status:
        """Readiness: the store answers; 503 when Redis is unreachable."""
        if await deps.ready():
            return h.Status(status="ready")
        response.status_code = 503
        return h.Status(status="unavailable")

    @api.get("/metrics", tags=["operations"], response_class=Response, responses={200: text})
    async def scrape() -> Response:
        """The node's metrics in the Prometheus text format."""
        body, content_type = metrics.exposition()
        return Response(body, media_type=content_type)

    return api


def _problem(
    status: int, error: str, message: str, headers: Mapping[str, str] | None = None
) -> Response:
    return JSONResponse({"error": error, "message": message}, status, headers)


# The reply to a path that does not exist.
NO_ROUTE = (404, HTTPStatus.NOT_FOUND.name, HTTPStatus.NOT_FOUND.phrase)


def _admin_guard(token: str) -> Callable[[Request, RequestResponseEndpoint], Awaitable[Response]]:
    """Answer ``/admin`` requests without the right token before routing: method matching and body
    parsing run after it, so their 405 and 422 never show that a path exists."""

    async def guard(request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.scope["path"]
        if path == "/admin" or path.startswith("/admin/"):
            given = request.headers.get("x-admin-token", "")
            if not hmac.compare_digest(given.encode(), token.encode()):
                return _problem(*NO_ROUTE)
        return await call_next(request)

    return guard


def _admin(deps: HttpDeps) -> APIRouter:
    api = APIRouter(prefix="/admin", tags=["MOCK admin"], include_in_schema=False)

    @api.post("/quizzes", status_code=201, responses={409: {"model": h.Problem}})
    async def create_quiz(request: Request, body: h.CreateQuiz) -> h.QuizInfo:
        """MOCK: start the bank's quiz of this ID; 409 when it exists."""
        _quiz(request, body.quizId)
        if (bank := await deps.bank.questions(body.quizId)) is None:
            raise DomainError(ErrorCode.QUIZ_NOT_FOUND, NOT_FOUND)
        questions = tuple(Question(q.question_id, q.correct_choice) for q in bank)
        window, limit = body.windowMs, body.timeLimitMs
        await deps.store.create_quiz(body.quizId, questions, window_ms=window, time_limit_ms=limit)
        return await _info(deps, body.quizId)

    @api.post(
        "/quizzes/{quiz_id}/end",
        responses={404: {"model": h.Problem}, 503: {"model": h.Problem}},
    )
    async def end_quiz(request: Request, quiz_id: str) -> h.Ended:
        """MOCK: the host's "end now": mark, wait for the fsync, announce (redis.md §3.1).

        503 ``UNAVAILABLE`` when the end was not made durable and announced; retry it."""
        _quiz(request, quiz_id)
        if not QUIZ_ID.fullmatch(quiz_id):
            raise DomainError(ErrorCode.QUIZ_NOT_FOUND, NOT_FOUND)
        end_seq = await deps.store.end_by_host(quiz_id)
        return h.Ended(quizId=quiz_id, status="ended", endSeq=end_seq)

    return api


async def _log_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
    given = request.headers.get("x-request-id", "")
    request_id = given if REQUEST_ID.fullmatch(given) else uuid.uuid4().hex
    start = time.perf_counter()
    with structlog.contextvars.bound_contextvars(request_id=request_id, quiz_id=None):
        try:
            response = await call_next(request)
        except Exception:  # logged here, inside the request's context, then a 500 with its id
            log.exception("unhandled error", method=request.method, path=request.url.path)
            response = JSONResponse({"error": "INTERNAL", "message": "internal error"}, 500)
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,  # never the query string
            status=response.status_code,
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
            quiz_id=getattr(request.state, "quiz_id", None),
        )
    response.headers["X-Request-ID"] = request_id
    return response


def _invalid(error: RequestValidationError) -> str:
    """``displayName: String should have at most 128 characters``; the ``body`` prefix dropped."""

    def where(loc: tuple[str | int, ...]) -> str:
        return ".".join(str(part) for part in loc[1:]) or "body"

    return "; ".join(f"{where(e['loc'])}: {e['msg']}" for e in error.errors())


def install(app: FastAPI, deps: HttpDeps) -> None:
    """Add the routes, the request log and the error mapping to ``app``."""

    async def mapped(request: Request, error: Exception) -> Response:
        if request.scope["type"] != "http":  # the WebSocket gateway handles its own errors
            raise error
        if isinstance(error, StarletteHTTPException):
            status = HTTPStatus(error.status_code)
            return _problem(status, status.name, str(error.detail), error.headers)
        if isinstance(error, RequestValidationError):
            return _problem(422, ErrorCode.INVALID_MESSAGE, _invalid(error))
        if not isinstance(error, DomainError):
            return _problem(503, "UNAVAILABLE", "store unreachable")
        message = NOT_FOUND if error.code is ErrorCode.QUIZ_NOT_FOUND else str(error)
        message = message.removeprefix(f"{error.code}: ")  # DomainError's text repeats its code
        return _problem(STATUS.get(error.code, 422), error.code, message)

    app.include_router(_public(deps))
    if deps.admin_token is not None:
        app.include_router(_admin(deps))
        app.middleware("http")(_admin_guard(deps.admin_token))  # inside the request log
    kinds = (StarletteHTTPException, RequestValidationError, DomainError, *deps.outages)
    for kind in kinds:
        app.add_exception_handler(kind, mapped)
    app.middleware("http")(_log_request)
