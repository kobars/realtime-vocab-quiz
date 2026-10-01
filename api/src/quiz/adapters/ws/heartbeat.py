# AI-ASSISTED: the server heartbeat: uvicorn's WebSocket ping, set from the settings.
"""ASGI has no ping call, so the server heartbeat is uvicorn's: a ping every ``heartbeat_ms``,
and a socket whose pong has not come back by the next ping is closed (docs/spec/protocol.md §9).
``permessage-deflate`` stays off (§1)."""

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
        ws_ping_interval=seconds,
        ws_ping_timeout=seconds,
        ws_per_message_deflate=False,
    )
