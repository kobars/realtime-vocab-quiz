# AI-ASSISTED: the uvicorn server settings: the WebSocket heartbeat and the transport limits.
"""ASGI has no ping call, so the server heartbeat is uvicorn's: a ping every ``heartbeat_ms``,
and a socket whose pong has not come back by the next ping is closed (docs/spec/protocol.md §9).

The image runs the server through ``server_config`` (``python -m quiz``), so the settings drive
these options. uvicorn buffers a whole frame before the gateway's size check, and its own cap is
16 MiB: four times the gateway limit keeps the gateway's ``MESSAGE_TOO_LARGE`` answer for frames
just above it and bounds memory beyond. The gateway alone reads ``X-Forwarded-For``, so
uvicorn's proxy headers are off; ``permessage-deflate`` stays off (§1). uvicorn's own logging
config would replace the app's JSON handlers, so it is not applied.

Two limits act before the app sees a request, so the gateway's caps cannot. uvicorn's httptools
protocol buffers a request head with no size limit and no deadline: ``BoundedHead`` answers a
head above ``MAX_HEAD_BYTES`` with 400 and closes a connection whose head is not complete
``header_timeout_ms`` after it opened, or after its request began. uvicorn's WebSocket protocol
keeps every fragment of a message, and an empty one adds nothing to the frame size cap:
``BoundedFragments`` closes a message of more than ``MAX_FRAGMENTS`` fragments with 1009. Both
classes are passed by name, so ``auto`` cannot pick an unbounded one. uvicorn runs with no
connection limit of its own and times no request body, and the gateway's caps count only
accepted sockets, so a node is never published directly: nginx stands in front of it and
buffers each request body before passing it on."""

import asyncio
from typing import ClassVar, override

import uvicorn
from starlette.types import ASGIApp
from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
from uvicorn.protocols.websockets.websockets_sansio_impl import WebSocketsSansIOProtocol
from websockets.frames import Frame
from websockets.protocol import State

from quiz.config import KIB, Settings

MAX_HEAD_BYTES = 16 * KIB  # the request line and headers of one request
MAX_FRAGMENTS = 64  # the frames of one WebSocket message; empty fragments count too
GRACEFUL_SHUTDOWN_S = 5  # then open requests are cancelled; below the engine's 10 s stop grace


class HeadTooLargeError(Exception):
    """Raised from a parser callback: httptools stops, and uvicorn answers 400 and closes."""


class BoundedHead(HttpToolsProtocol):
    head_timeout_s: ClassVar[float]  # set by ``bounded_head``
    head_bytes = 0
    began = False  # a request began inside the current read
    deadline: asyncio.TimerHandle | None = None  # set while a request head is unfinished

    def _start_deadline(self) -> None:
        if self.deadline is None:
            self.deadline = self.loop.call_later(self.head_timeout_s, self.transport.close)

    def _stop_deadline(self) -> None:
        if self.deadline is not None:
            self.deadline.cancel()
            self.deadline = None

    def _parsed_head_bytes(self) -> int:
        return len(self.url) + sum(len(name) + len(value) for name, value in self.headers)

    @override
    def connection_made(self, transport: asyncio.Transport) -> None:  # type: ignore[override]
        super().connection_made(transport)
        self._start_deadline()

    @override
    def connection_lost(self, exc: Exception | None) -> None:
        self._stop_deadline()
        super().connection_lost(exc)

    @override
    def data_received(self, data: bytes) -> None:
        self.began = False
        super().data_received(data)
        if self.deadline is None or self.transport.is_closing():
            return
        # The head is still unfinished. A read that began it may also hold the end of the
        # previous request, so only its parsed part counts; any later read is all head.
        self.head_bytes = self._parsed_head_bytes() if self.began else self.head_bytes + len(data)
        if self.head_bytes > MAX_HEAD_BYTES:
            self.send_400_response("Request head too large.")

    @override
    def on_message_begin(self) -> None:
        super().on_message_begin()
        self.began = True
        self.head_bytes = 0
        self._start_deadline()

    @override
    def on_headers_complete(self) -> None:
        self._stop_deadline()
        if self._parsed_head_bytes() > MAX_HEAD_BYTES:  # a head that finished within one read
            raise HeadTooLargeError
        super().on_headers_complete()


def bounded_head(timeout_s: float) -> type[BoundedHead]:
    class Configured(BoundedHead):
        head_timeout_s = timeout_s

    return Configured


class BoundedFragments(WebSocketsSansIOProtocol):
    @override
    def handle_cont(self, event: Frame) -> None:
        if self.close_sent:  # the frames parsed from the same read after a refusal are dropped
            return
        if len(self.frames) >= MAX_FRAGMENTS:
            self.frames = []
            if self.conn.state is State.OPEN:  # else the peer's close came first and is answered
                self.conn.send_close(1009, "too many fragments")
            self.handle_parser_exception()  # sends the close, tells the app, closes the transport
            return
        super().handle_cont(event)


def server_config(app: ASGIApp, settings: Settings, host: str, port: int) -> uvicorn.Config:
    seconds = settings.heartbeat_ms / 1000
    return uvicorn.Config(
        app,
        host=host,
        port=port,
        http=bounded_head(settings.header_timeout_ms / 1000),
        ws=BoundedFragments,
        access_log=False,
        log_config=None,  # the app's JSON logging is set when the app is built, before this
        proxy_headers=False,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
        ws_max_size=4 * settings.max_payload_bytes,
        ws_ping_interval=seconds,
        ws_ping_timeout=seconds,
        ws_per_message_deflate=False,
    )
