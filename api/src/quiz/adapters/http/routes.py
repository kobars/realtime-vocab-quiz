# AI-ASSISTED: the HTTP edge: mock sessions and tickets, quiz info, mock admin and probes.
"""HTTP routes of docs/spec/protocol.md §8 plus the operator endpoints.

MOCK: ``POST /sessions`` and ``POST /tickets`` stand in for an identity provider, and the
``/admin`` routes for a quiz admin service; they exist only with ``ADMIN_MOCK=1`` and answer 404
to a request without the right ``X-Admin-Token``, the same as a route that does not exist.
"""

import hmac
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from quiz.adapters.http import models as h
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.ports.questions import QuestionBank
from quiz.ports.store import Store
from quiz.ports.tickets import TicketStore

QUIZ_ID = re.compile(r"[A-Z0-9-]{3,16}")
STATUS = {ErrorCode.QUIZ_NOT_FOUND: 404, ErrorCode.INVALID_STATE: 409}
NOT_FOUND = "no such quiz"  # one body for every unknown ID: no hint whether it ever existed


@dataclass(frozen=True, slots=True)
class HttpDeps:
    store: Store
    tickets: TicketStore
    bank: QuestionBank
    ready: Callable[[], Awaitable[bool]]  # the store answers
    ticket_ttl_ms: int
    admin_token: str | None = None  # None: no admin routes
    outages: tuple[type[Exception], ...] = (ConnectionError, TimeoutError)  # -> 503


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
        ticket = await deps.tickets.issue_ticket(token) if scheme == "Bearer" and token else None
        if ticket is None:
            raise HTTPException(401, "unknown session", headers={"WWW-Authenticate": "Bearer"})
        return h.TicketOut(ticket=ticket, expiresInMs=deps.ticket_ttl_ms)

    @api.get("/quizzes/{quiz_id}", tags=["quizzes"], responses={404: {"model": h.Problem}})
    async def quiz_info(quiz_id: str) -> h.QuizInfo:
        """Public information about a quiz; ``ended`` from its deadline, whoever is connected."""
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

    return api


def _admin(deps: HttpDeps, token: str) -> APIRouter:
    async def guard(x_admin_token: Annotated[str, Header()] = "") -> None:
        if not hmac.compare_digest(x_admin_token.encode(), token.encode()):
            raise HTTPException(404, "Not Found")

    api = APIRouter(prefix="/admin", tags=["MOCK admin"], dependencies=[Depends(guard)])

    @api.post("/quizzes", status_code=201, responses={409: {"model": h.Problem}})
    async def create_quiz(body: h.CreateQuiz) -> h.QuizInfo:
        """MOCK: start the bank's quiz of this ID; 409 when it exists."""
        if (bank := await deps.bank.questions(body.quizId)) is None:
            raise DomainError(ErrorCode.QUIZ_NOT_FOUND, NOT_FOUND)
        questions = tuple(Question(q.question_id, q.correct_choice) for q in bank)
        window, limit = body.windowMs, body.timeLimitMs
        await deps.store.create_quiz(body.quizId, questions, window_ms=window, time_limit_ms=limit)
        return await _info(deps, body.quizId)

    @api.post("/quizzes/{quiz_id}/end", responses={404: {"model": h.Problem}})
    async def end_quiz(quiz_id: str) -> h.Ended:
        """MOCK: the host's "end now": mark the end, then announce it (docs/spec/redis.md §3.1)."""
        end = await deps.store.end_quiz(quiz_id, "host")
        if end.status == "marked":
            end = await deps.store.end_quiz(quiz_id, "host")
        return h.Ended(quizId=quiz_id, status="ended", endSeq=end.seq)

    return api


def install(app: FastAPI, deps: HttpDeps) -> None:
    """Add the routes and the error mapping to ``app``."""

    async def mapped(request: Request, error: Exception) -> JSONResponse:
        if request.scope["type"] != "http":  # the WebSocket gateway handles its own errors
            raise error
        if not isinstance(error, DomainError):
            return JSONResponse(
                {"error": "UNAVAILABLE", "message": "the store is unreachable"}, 503
            )
        message = NOT_FOUND if error.code is ErrorCode.QUIZ_NOT_FOUND else str(error)
        return JSONResponse({"error": error.code, "message": message}, STATUS.get(error.code, 422))

    app.include_router(_public(deps))
    if deps.admin_token is not None:
        app.include_router(_admin(deps, deps.admin_token))
    for kind in (DomainError, *deps.outages):
        app.add_exception_handler(kind, mapped)
