# AI-ASSISTED: the receive loop of one accepted socket: size, rate limit, strict parse, use cases.
"""Per inbound frame, in order: the size (``MESSAGE_TOO_LARGE``, close 1009), the token bucket
(``RATE_LIMITED``; close 1008 after 10 s of abuse), the strict parser, then the use case.
Every reply and close goes through the socket's ``Sender``, its one writer."""

import asyncio
from dataclasses import dataclass

import structlog
from fastapi import WebSocket

from quiz.adapters.ws.limits import RateLimiter, Verdict
from quiz.adapters.ws.registry import Registry
from quiz.adapters.ws.sender import Sender
from quiz.app.service import Connection, QuizService
from quiz.contracts import messages as m
from quiz.contracts.codec import parse_client_message

CLOSE_POLICY, CLOSE_TOO_BIG, CLOSE_GONE = 1008, 1009, 1006


@dataclass(frozen=True, slots=True)
class Deps:  # what every socket of one node shares
    service: QuizService
    registry: Registry
    max_payload: int


def _error(code: m.ErrorCode, text: str) -> m.ProtocolError:
    return m.ProtocolError(code=code, message=text, requestType=None)


def _close(sender: Sender, code: int, error: m.ErrorCode, text: str) -> int:
    sender.send(_error(error, text))  # the error goes out before every application close
    sender.close(code)
    return code


async def _receive(
    ws: WebSocket, conn: Connection, limiter: RateLimiter, sender: Sender, deps: Deps
) -> int:
    """Handle frames until the client leaves (its close code) or a rule closes the socket."""
    while True:
        event = await ws.receive()
        if event["type"] == "websocket.disconnect":
            return int(event.get("code", 1000))
        text: str | None = event.get("text")
        raw = text.encode() if text is not None else event.get("bytes") or b""
        if len(raw) > deps.max_payload:
            return _close(sender, CLOSE_TOO_BIG, m.ErrorCode.MESSAGE_TOO_LARGE, "frame too big")
        verdict = limiter.check()
        if verdict is Verdict.CLOSE:
            return _close(sender, CLOSE_POLICY, m.ErrorCode.RATE_LIMITED, "abuse: closing")
        if verdict is Verdict.NOTIFY:
            sender.send(_error(m.ErrorCode.RATE_LIMITED, "message dropped: rate limited"))
        if verdict is not Verdict.ACCEPT:
            continue
        msg = parse_client_message(raw) if text is not None else None
        if msg is None or isinstance(msg, m.ProtocolError):
            sender.send(msg or _error(m.ErrorCode.INVALID_MESSAGE, "text frames only"))
            continue
        if (code := await _dispatch(conn, msg, sender, deps)) is not None:
            return code


async def _dispatch(
    conn: Connection, msg: m.ClientMessage, sender: Sender, deps: Deps
) -> int | None:
    """Run the use case; a join binds the socket to its quiz and closes the one it replaced."""
    outcome = await deps.service.handle(conn, msg)
    if isinstance(msg, m.Join):
        deps.registry.bind(conn, sender)
        structlog.contextvars.bind_contextvars(quiz_id=conn.quiz_id)  # this socket's later lines
    if outcome.replaced_conn_id is not None:
        deps.registry.replace(outcome.replaced_conn_id)
    for reply in outcome.replies:
        sender.send(reply)
    if outcome.close_code is not None:
        sender.close(outcome.close_code)
    return outcome.close_code


async def serve(
    ws: WebSocket, conn: Connection, limiter: RateLimiter, sender: Sender, deps: Deps
) -> int:
    """Run until the client leaves or the socket is closed; return the close code."""
    receiver = asyncio.create_task(_receive(ws, conn, limiter, sender, deps))
    try:
        await asyncio.wait({receiver, sender.task}, return_when=asyncio.FIRST_COMPLETED)
        if sender.close_code is not None:  # a rule, the store or a slow-client limit closes it
            await sender.task
            return sender.close_code
        return receiver.result() if receiver.done() else CLOSE_GONE
    finally:
        receiver.cancel()
        sender.task.cancel()
