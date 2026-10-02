# AI-ASSISTED: the /ws upgrade: every check before accept, then the receive loop; path-only logs.
"""``GET /ws?ticket=…`` with the subprotocol ``quiz.v1`` (docs/spec/protocol.md §8).

Before accept, in order: the Origin (403), the subprotocol (400), the upgrade attempts of the
client address (429), the ticket (401), then the caps (503 per process, 429 per client address).
A refusal is a plain HTTP response; an accepted upgrade names the node that serves it in
``X-Node-Id``.

A socket whose close the sender gave up (the peer reads nothing, so not even the close frame
goes out) leaves the registry at once but keeps its cap slots, and its close frame stays
pending, until that frame goes out or uvicorn reports the disconnect. ASGI has no abort and
uvicorn's close waits for the buffer to flush, so that transport lasts until the peer reads
again (the frame goes out and uvicorn's close timeout ends the transport) or goes (the kernel
ends a vanished peer's connection), and the caps keep bounding open transports. The cost is
one idle handler per such socket; no timer frees the slot sooner, since a peer that never
reads could then open sockets without limit. ``ws_connections`` counts a socket for as long as it
holds its cap slots, and ``ws_pending_close`` the ones among them whose close frame is pending."""

import asyncio
import logging
import time
import uuid

import structlog
from fastapi import Response, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from quiz.adapters.ws.limits import ConnectionCaps, RateLimiter, address_limiter, connection_ip
from quiz.adapters.ws.registry import Registry
from quiz.adapters.ws.sender import Sender
from quiz.adapters.ws.session import Deps, serve
from quiz.app.service import Connection, QuizService
from quiz.config import Settings
from quiz.obs import metrics
from quiz.ports.clock import Clock
from quiz.ports.store import Store
from quiz.ports.tickets import TicketStore

log = logging.getLogger(__name__)

SUBPROTOCOL = "quiz.v1"
UVICORN_LOGGERS = ("uvicorn.access", "uvicorn.error", "uvicorn.asgi")  # asgi: the trace level
MISSED_HANDSHAKE = "ASGI callable returned without completing handshake."


def _redact(arg: object) -> object:
    if isinstance(arg, str) and arg.startswith("/"):
        return arg.partition("?")[0]
    if isinstance(arg, dict):  # an ASGI scope, as uvicorn's trace logger prints it
        return {k: "<redacted>" if k == "query_string" else _redact(v) for k, v in arg.items()}
    return arg


def path_only(record: logging.LogRecord) -> bool:
    """Cut the query string, which holds the ticket, from uvicorn's lines and logged scopes."""
    if isinstance(record.args, tuple):
        record.args = tuple(_redact(arg) for arg in record.args)
    return True


def not_after_a_denial(record: logging.LogRecord) -> bool:
    """Drop the error that uvicorn's websockets protocol logs after every denial response: it
    never marks the handshake done on that path. ``Gateway.endpoint`` always accepts or denies,
    so the message never means a missed handshake here."""
    return record.msg != MISSED_HANDSHAKE


class Gateway:
    def __init__(
        self, settings: Settings, tickets: TicketStore, service: QuizService, store: Store
    ) -> None:
        self._settings, self._tickets = settings, tickets
        self._accept_headers = [(b"x-node-id", settings.node_id.encode())]
        self.registry = Registry(store, settings.grace_ms)
        self._deps = Deps(service, self.registry, settings.max_payload_bytes)
        self.caps = ConnectionCaps(settings.max_connections, settings.per_ip_conn_cap)
        self.clock: Clock = lambda: time.monotonic_ns() // 1_000_000  # paces the token buckets
        # Each upgrade attempt costs a ticket lookup in the store.
        self.upgrades = address_limiter(settings.per_ip_conn_cap, self._now)
        for name in UVICORN_LOGGERS:  # adding it twice is a no-op
            logging.getLogger(name).addFilter(path_only)
        logging.getLogger("uvicorn.error").addFilter(not_after_a_denial)

    def _now(self) -> int:  # reads ``clock`` on each call, so a test can replace it
        return self.clock()

    def _refusal(self, ws: WebSocket, ip: str) -> tuple[int, str] | None:
        """The status and reason that refuse the upgrade before its ticket is looked up."""
        if ws.headers.get("origin") not in self._settings.allowed_origins:
            return 403, "origin not allowed"
        if SUBPROTOCOL not in ws.scope.get("subprotocols", ()):
            return 400, f"subprotocol {SUBPROTOCOL} not offered"
        if not self.upgrades.allow(ip):
            return 429, "too many upgrade attempts"
        return None

    async def endpoint(self, ws: WebSocket) -> None:
        settings = self._settings
        ip = connection_ip(ws, settings.trusted_proxies)
        if (refusal := self._refusal(ws, ip)) is not None:
            return await _refuse(ws, *refusal)
        ticket = ws.query_params.get("ticket")
        try:
            identity = await self._tickets.redeem(ticket) if ticket else None
        except ConnectionError, TimeoutError:
            return await _refuse(ws, 503, "ticket store unreachable")
        if identity is None:
            return await _refuse(ws, 401, "missing, used or expired ticket")
        if (status := self.caps.acquire(ip)) is not None:
            return await _refuse(ws, status, "connection cap reached")
        try:
            with metrics.WS_CONNECTIONS.track_inprogress():  # as long as the cap slot is held
                await self._serve(ws, Connection(uuid.uuid4().hex, identity.user_id))
        finally:
            self.caps.release(ip)
        return None

    async def _serve(self, ws: WebSocket, conn: Connection) -> None:
        settings, path = self._settings, ws.scope["path"]
        code = 1006  # the socket dropped without a close frame
        sender: Sender | None = None
        # the socket's lines carry its connection id as request_id; the join binds quiz_id
        with structlog.contextvars.bound_contextvars(request_id=conn.conn_id, quiz_id=None):
            try:
                await ws.accept(subprotocol=SUBPROTOCOL, headers=self._accept_headers)
                rate, burst = settings.rate_limit_per_s, settings.rate_limit_burst
                soft, hard = settings.send_buffer_soft_bytes, settings.send_buffer_hard_bytes
                limiter, sender = RateLimiter(rate, burst, self.clock), Sender(ws, soft, hard)
                code = await serve(ws, conn, limiter, sender, self._deps)
            except WebSocketDisconnect as gone:
                code = gone.code
            finally:
                self.registry.drop(conn)
                structlog.contextvars.bind_contextvars(quiz_id=conn.quiz_id)
                log.info("ws %s closed %d", path, code)
                metrics.WS_CLOSES.labels(str(code)).inc()
        if sender is not None and sender.closing is not None:
            peer_gone = asyncio.create_task(_until_disconnect(ws))
            try:
                with metrics.WS_PENDING_CLOSE.track_inprogress():
                    await asyncio.wait(
                        {sender.closing, peer_gone}, return_when=asyncio.FIRST_COMPLETED
                    )
            finally:
                sender.closing.cancel()
                peer_gone.cancel()


async def _until_disconnect(ws: WebSocket) -> None:
    while ws.client_state is not WebSocketState.DISCONNECTED:
        await ws.receive()  # until uvicorn's disconnect: the transport is gone


async def _refuse(ws: WebSocket, status: int, reason: str) -> None:
    log.info("ws %s refused %d: %s", ws.scope["path"], status, reason)
    await ws.send_denial_response(Response(status_code=status))
