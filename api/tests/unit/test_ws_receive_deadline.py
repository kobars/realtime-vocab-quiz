# AI-ASSISTED: a WebSocket server that never answers fails the waiting test instead of hanging it.
import time
from collections.abc import Callable

import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.types import Message


def test_a_receive_from_a_silent_server_raises_timeout_error_at_the_deadline(
    ws_receive: Callable[[float], Callable[[WebSocketTestSession], Message]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()

    @app.websocket("/silent")
    async def silent(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.receive()  # waits for the client's close; sends nothing

    monkeypatch.setattr(WebSocketTestSession, "receive", ws_receive(0.2))
    with TestClient(app) as client, client.websocket_connect("/silent") as ws:
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            ws.receive_json()
        assert time.monotonic() - start < 2
