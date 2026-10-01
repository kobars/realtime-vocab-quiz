# AI-ASSISTED: the uvicorn server settings: the WebSocket heartbeat and the transport limits.
"""ASGI has no ping call, so the server heartbeat is uvicorn's: a ping every ``heartbeat_ms``,
and a socket whose pong has not come back by the next ping is closed (docs/spec/protocol.md §9).

The image runs the server through ``server_config`` (``python -m quiz``), so the settings drive
these options. uvicorn buffers a whole frame before the gateway's size check, and its own cap is
16 MiB: four times the gateway limit keeps the gateway's ``MESSAGE_TOO_LARGE`` answer for frames
just above it and bounds memory beyond. The gateway alone reads ``X-Forwarded-For``, so
uvicorn's proxy headers are off; ``permessage-deflate`` stays off (§1). uvicorn's own logging
config would replace the app's JSON handlers, so it is not applied."""

import uvicorn
from starlette.types import ASGIApp

from quiz.config import Settings


def server_config(app: ASGIApp, settings: Settings, host: str, port: int) -> uvicorn.Config:
    seconds = settings.heartbeat_ms / 1000
    return uvicorn.Config(
        app,
        host=host,
        port=port,
        access_log=False,
        log_config=None,  # the app's JSON logging is set when the app is built, before this
        proxy_headers=False,
        ws_max_size=4 * settings.max_payload_bytes,
        ws_ping_interval=seconds,
        ws_ping_timeout=seconds,
        ws_per_message_deflate=False,
    )
