# AI-ASSISTED: the /ws upgrade: every check before accept, then the receive loop; path-only logs.
"""``GET /ws?ticket=…`` with the subprotocol ``quiz.v1`` (docs/spec/protocol.md §8).

Before accept, in order: the Origin (403), the subprotocol (400), the ticket (401), then the
caps (503 per process, 429 per client address). A refusal is a plain HTTP response."""

import logging
import time
import uuid

from fastapi import Response, WebSocket, WebSocketDisconnect

from quiz.adapters.ws.limits import ConnectionCaps, RateLimiter, client_ip
from quiz.adapters.ws.session import serve
from quiz.app.service import Connection, QuizService
from quiz.config import Settings
from quiz.ports.clock import Clock
from quiz.ports.tickets import TicketStore

log = logging.getLogger(__name__)

SUBPROTOCOL = "quiz.v1"


def path_only(record: logging.LogRecord) -> bool:
    """Cut the query string from the paths in uvicorn's log lines: it holds the ticket."""
    if isinstance(record.args, tuple):
        record.args = tuple(
            arg.partition("?")[0] if isinstance(arg, str) and arg.startswith("/") else arg
            for arg in record.args
        )
    return True


class Gateway:
    def __init__(self, settings: Settings, tickets: TicketStore, service: QuizService) -> None:
        self._settings, self._tickets, self._service = settings, tickets, service
        self.caps = ConnectionCaps(settings.max_connections, settings.per_ip_conn_cap)
        self.clock: Clock = lambda: time.monotonic_ns() // 1_000_000  # paces the token buckets
        for name in ("uvicorn.access", "uvicorn.error"):  # adding it twice is a no-op
            logging.getLogger(name).addFilter(path_only)

    async def endpoint(self, ws: WebSocket) -> None:
        settings, path = self._settings, ws.scope["path"]
        if ws.headers.get("origin") not in settings.allowed_origins:
            return await _refuse(ws, 403, "origin not allowed")
        if SUBPROTOCOL not in ws.scope.get("subprotocols", ()):
            return await _refuse(ws, 400, f"subprotocol {SUBPROTOCOL} not offered")
        ticket = ws.query_params.get("ticket")
        try:
            identity = await self._tickets.redeem(ticket) if ticket else None
        except ConnectionError, TimeoutError:
            return await _refuse(ws, 503, "ticket store unreachable")
        if identity is None:
            return await _refuse(ws, 401, "missing, used or expired ticket")
        peer = ws.client.host if ws.client else None
        ip = client_ip(peer, ws.headers.getlist("x-forwarded-for"), settings.trusted_proxies)
        if (status := self.caps.acquire(ip)) is not None:
            return await _refuse(ws, status, "connection cap reached")
        code = 1006  # the socket dropped without a close frame
        try:
            await ws.accept(subprotocol=SUBPROTOCOL)
            conn = Connection(uuid.uuid4().hex, identity.user_id)
            rate, burst = settings.rate_limit_per_s, settings.rate_limit_burst
            limiter = RateLimiter(rate, burst, self.clock)
            code = await serve(ws, conn, self._service, limiter, settings.max_payload_bytes)
        except WebSocketDisconnect as gone:
            code = gone.code
        finally:
            self.caps.release(ip)
            log.info("ws %s closed %d", path, code)
        return None


async def _refuse(ws: WebSocket, status: int, reason: str) -> None:
    log.info("ws %s refused %d: %s", ws.scope["path"], status, reason)
    await ws.send_denial_response(Response(status_code=status))
