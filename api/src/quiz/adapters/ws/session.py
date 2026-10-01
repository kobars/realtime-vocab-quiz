# AI-ASSISTED: the receive loop of one accepted socket: size, rate limit, strict parse, use cases.
"""Per inbound frame, in order: the size (``MESSAGE_TOO_LARGE``, close 1009), the token bucket
(``RATE_LIMITED``; close 1008 after 10 s of abuse), the strict parser, then the use case."""

from fastapi import WebSocket

from quiz.adapters.ws.limits import RateLimiter, Verdict
from quiz.app.service import Connection, QuizService
from quiz.contracts import messages as m
from quiz.contracts.codec import encode, parse_client_message

CLOSE_POLICY, CLOSE_TOO_BIG = 1008, 1009


def _error(code: m.ErrorCode, text: str) -> m.ProtocolError:
    return m.ProtocolError(code=code, message=text, requestType=None)


async def _send(ws: WebSocket, message: m.ServerMessage) -> None:
    await ws.send_text(encode(message).decode())


async def _close(ws: WebSocket, code: int, error: m.ErrorCode, text: str) -> int:
    await _send(ws, _error(error, text))  # the error goes out before every application close
    await ws.close(code)
    return code


async def serve(
    ws: WebSocket, conn: Connection, service: QuizService, limiter: RateLimiter, max_payload: int
) -> int:
    """Run until the client leaves or a rule closes the socket; return the close code."""
    while True:
        event = await ws.receive()
        if event["type"] == "websocket.disconnect":
            return int(event.get("code", 1000))
        text: str | None = event.get("text")
        raw = text.encode() if text is not None else event.get("bytes") or b""
        if len(raw) > max_payload:
            return await _close(ws, CLOSE_TOO_BIG, m.ErrorCode.MESSAGE_TOO_LARGE, "frame too big")
        verdict = limiter.check()
        if verdict is Verdict.CLOSE:
            return await _close(ws, CLOSE_POLICY, m.ErrorCode.RATE_LIMITED, "abuse: closing")
        if verdict is Verdict.NOTIFY:
            await _send(ws, _error(m.ErrorCode.RATE_LIMITED, "message dropped: rate limited"))
        if verdict is not Verdict.ACCEPT:
            continue
        msg = parse_client_message(raw) if text is not None else None
        if msg is None or isinstance(msg, m.ProtocolError):
            await _send(ws, msg or _error(m.ErrorCode.INVALID_MESSAGE, "text frames only"))
            continue
        outcome = await service.handle(conn, msg)
        for reply in outcome.replies:
            await _send(ws, reply)
        if outcome.close_code is not None:
            await ws.close(outcome.close_code)
            return outcome.close_code
