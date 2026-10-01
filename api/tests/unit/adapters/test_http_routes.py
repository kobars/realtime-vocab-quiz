# AI-ASSISTED: the HTTP edge: an end that was not announced, an unhandled error, the identity limit.
import io
import json
from collections.abc import AsyncIterator
from typing import Literal

import httpx
import pytest
from fastapi import FastAPI

from quiz.config import Settings
from quiz.main import create_app, services_of
from quiz.obs import logs
from quiz.ports.store import End

TOKEN = {"X-Admin-Token": "admin-test-token"}


@pytest.fixture
def app() -> FastAPI:
    base = {"store": "memory", "admin_mock": True, "admin_token": TOKEN["X-Admin-Token"]}
    return create_app(Settings.model_validate(base), clock=lambda: 1_800_000_000_000)


@pytest.fixture
async def http(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_a_host_end_that_is_never_announced_answers_503(
    app: FastAPI, http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"quizId": "VOCAB-42", "timeLimitMs": 20_000, "windowMs": 600_000}
    assert (await http.post("/admin/quizzes", json=body, headers=TOKEN)).status_code == 201
    store = services_of(app).store

    async def mark_only(_: str, __: Literal["deadline", "host"]) -> End:
        return End("marked")  # the mark was lost between the two calls

    monkeypatch.setattr(store, "end_quiz", mark_only)
    resp = await http.post("/admin/quizzes/VOCAB-42/end", headers=TOKEN)
    assert (resp.status_code, resp.json()["error"]) == (503, "UNAVAILABLE")
    assert (await store.snapshot("VOCAB-42", None)).at_seq == 0  # no quiz_ended went out


async def test_an_unhandled_error_answers_500_with_the_request_id(
    app: FastAPI, http: httpx.AsyncClient
) -> None:
    @app.get("/boom")
    async def boom() -> None:
        msg = "boom"
        raise RuntimeError(msg)

    out = io.StringIO()
    logs.configure_logging(out)
    resp = await http.get("/boom", headers={"X-Request-ID": "req-9"})
    assert (resp.status_code, resp.headers["X-Request-ID"]) == (500, "req-9")
    assert resp.json() == {"error": "INTERNAL", "message": "internal error"}
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    [error] = [line for line in lines if "exception" in line]
    assert error["request_id"] == "req-9"
    assert "RuntimeError: boom" in error["exception"]
    [served] = [line for line in lines if line["event"] == "http_request"]
    assert (served["status"], served["request_id"]) == (500, "req-9")


async def test_sessions_and_tickets_share_one_limit_per_client_address() -> None:
    app = create_app(Settings(per_ip_conn_cap=1))  # a burst of 2: a session and a ticket
    transport = httpx.ASGITransport(app=app)  # the peer is 127.0.0.1, a trusted proxy
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        token = (await http.post("/sessions", json={"displayName": "Ana"})).json()["sessionToken"]
        auth = {"Authorization": f"Bearer {token}"}
        assert (await http.post("/tickets", headers=auth)).status_code == 201
        refused = await http.post("/tickets", headers=auth)
        assert (refused.status_code, refused.json()["error"]) == (429, "TOO_MANY_REQUESTS")
        assert (await http.post("/sessions", json={"displayName": "Ana"})).status_code == 429
        other = {"X-Forwarded-For": "203.0.113.7"}  # another client behind that proxy
        resp = await http.post("/sessions", json={"displayName": "Bo"}, headers=other)
        assert resp.status_code == 201
