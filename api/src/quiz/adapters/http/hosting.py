# AI-ASSISTED: self-service hosting: list the bank quizzes, start a run with a host token, end it.
"""Any visitor may start a run of a bank quiz and end it early with the host token it got.

The token is 32 random bytes, shown once; the store keeps its SHA-256 only, compared in constant
time, and no log line carries it. Creation is limited per client address and by a cap on the open
self-hosted quizzes of every node; a browser request from another origin is refused. The routes
exist only with ``PUBLIC_HOSTING`` on (docs/spec/protocol.md §8).
"""

import hashlib
import hmac
import math
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, Request

from quiz.adapters.http import models as h
from quiz.adapters.http.models import QUESTION_MS
from quiz.adapters.http.routes import NOT_FOUND, QUIZ_ID, HttpDeps, Refusal, tag_quiz
from quiz.adapters.ws.limits import AddressRateLimiter, connection_ip
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question

# Upper-case letters and digits that cannot be read as one another (no 0/O, no 1/I).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 4
ATTEMPTS = 5  # a run code already taken is drawn again
QUIZ_ID_MAX = 16  # the longest ID that QUIZ_ID matches
TOKEN_BYTES = 32


def run_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def run_id(bank_id: str, code: str) -> str:
    """The bank quiz's ID and the run code, the ID cut short to keep the whole a valid quiz ID."""
    return f"{bank_id[: QUIZ_ID_MAX - len(code) - 1].rstrip('-')}-{code}"


def token_hash(token: str) -> str:
    """The stored form of a host token: 256 random bits need no slow hash."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Hosting:
    window_ms: int  # every self-hosted quiz's window
    max_open: int  # open self-hosted quizzes, all nodes together
    limit: AddressRateLimiter  # creations per client address
    origins: tuple[str, ...]  # a request with an Origin header must name one of these
    banks: tuple[str, ...]  # the bank quizzes a visitor may host


def _same_origin(hosting: Hosting) -> Callable[[Request], Awaitable[None]]:
    """403 for a browser request from another origin; a client that sends no Origin is no
    browser, so no other site can make it send the request."""

    async def same_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin is not None and origin not in hosting.origins:
            raise Refusal(403, "FORBIDDEN", "origin not allowed")

    return same_origin


def _limited(deps: HttpDeps, hosting: Hosting) -> Callable[[Request], Awaitable[None]]:
    """Count the creation against its client address: 429 with Retry-After above the limit."""

    async def limited(request: Request) -> None:
        if not hosting.limit.allow(connection_ip(request, deps.trusted_proxies)):
            retry_s = math.ceil(1 / hosting.limit.rate_per_s)  # one token has refilled by then
            message = "too many quizzes hosted from this address; try again later"
            raise Refusal(429, "RATE_LIMITED", message, {"Retry-After": str(retry_s)})

    return limited


async def _host(deps: HttpDeps, hosting: Hosting, bank_id: str) -> tuple[str, str, int]:
    """Start a run of ``bank_id``: its quiz ID, host token and deadline."""
    bank = await deps.bank.questions(bank_id) if bank_id in hosting.banks else None
    if bank is None:
        raise DomainError(ErrorCode.INVALID_MESSAGE, "bankQuizId: not a quiz you can host")
    questions = tuple(Question(q.question_id, q.correct_choice) for q in bank)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    for _ in range(ATTEMPTS):
        quiz_id = run_id(bank_id, run_code())
        if await deps.store.read_seq(quiz_id) is not None:  # taken
            continue
        if not await deps.store.hold_hosted(quiz_id, hosting.window_ms, hosting.max_open):
            message = "the server hosts as many quizzes as it can; try again later"
            raise Refusal(503, "HOSTING_FULL", message)
        try:
            created = await deps.store.create_quiz(
                quiz_id,
                questions,
                window_ms=hosting.window_ms,
                time_limit_ms=QUESTION_MS,
                bank_quiz_id=bank_id,
                host_token_hash=token_hash(token),
            )
        except DomainError as error:
            await deps.store.release_hosted(quiz_id)
            if error.code is not ErrorCode.INVALID_STATE:  # anything but "taken meanwhile"
                raise
            continue
        return quiz_id, token, created.deadline_ms
    raise DomainError(ErrorCode.UNAVAILABLE, "no free run code; retry")


async def _end(deps: HttpDeps, quiz_id: str, token: str) -> int:
    """End ``quiz_id`` for the holder of its host token: the end seq."""
    if not QUIZ_ID.fullmatch(quiz_id) or await deps.store.read_seq(quiz_id) is None:
        raise DomainError(ErrorCode.QUIZ_NOT_FOUND, NOT_FOUND)
    stored = await deps.store.host_token_hash(quiz_id) or ""
    given = token_hash(token) if token else ""
    if not (stored and given and hmac.compare_digest(given, stored)):
        raise Refusal(403, "FORBIDDEN", "not the host of this quiz")
    if (await deps.store.ranks_of(quiz_id, ())).status == "ended":
        await deps.store.release_hosted(quiz_id)  # in case the end's own release failed
        raise DomainError(ErrorCode.QUIZ_ENDED, "the quiz has ended")
    return await deps.store.end_by_host(quiz_id)


def _router(deps: HttpDeps, hosting: Hosting) -> APIRouter:
    api = APIRouter(tags=["hosting"], dependencies=[Depends(_same_origin(hosting))])
    problem: dict[str, Any] = {"model": h.Problem}

    listing = [{"id": "VOCAB-42", "title": "Everyday English", "questionCount": 10}]
    listed: dict[int | str, dict[str, Any]] = {
        200: {"content": {"application/json": {"example": listing}}}
    }

    @api.get("/banks", responses=listed)
    async def banks() -> list[h.Bank]:
        """The bank quizzes a visitor may host."""
        listed = []
        for bank_id in hosting.banks:
            if (questions := await deps.bank.questions(bank_id)) is not None:
                title = await deps.bank.title(bank_id) or bank_id
                listed.append(h.Bank(id=bank_id, title=title, questionCount=len(questions)))
        return listed

    @api.post(
        "/quizzes",
        status_code=201,
        dependencies=[Depends(_limited(deps, hosting))],
        responses=dict.fromkeys((403, 422, 429, 503), problem),
    )
    async def host_quiz(request: Request, body: h.HostIn) -> h.Hosted:
        """Start a run of ``bankQuizId``; the reply's ``hostToken`` alone can end it early."""
        quiz_id, token, ends_at_ms = await _host(deps, hosting, body.bankQuizId)
        tag_quiz(request, quiz_id)
        return h.Hosted(
            quizId=quiz_id,
            sharePath=f"/q/{quiz_id}",
            hostToken=token,
            windowMs=hosting.window_ms,
            endsAtMs=ends_at_ms,
        )

    @api.post("/quizzes/{quiz_id}/end", responses=dict.fromkeys((403, 404, 409, 503), problem))
    async def end_hosted(
        request: Request,
        quiz_id: str,
        x_host_token: Annotated[str, Header(examples=["Qm9…43 characters"])] = "",
    ) -> h.Ended:
        """End a self-hosted quiz early with its host token; players get the final results."""
        tag_quiz(request, quiz_id)
        end_seq = await _end(deps, quiz_id, x_host_token)
        return h.Ended(quizId=quiz_id, status="ended", endSeq=end_seq)

    return api


def install(app: FastAPI, deps: HttpDeps, hosting: Hosting) -> None:
    """Add the hosting routes; ``routes.install`` has added the error mapping."""
    app.include_router(_router(deps, hosting))
