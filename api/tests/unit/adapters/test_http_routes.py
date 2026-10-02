# AI-ASSISTED: the HTTP edge: an end that was not announced, an unhandled error, Redis refusing
# writes, the identity limit, public quiz info without a ranking.
import io
import json
from collections.abc import AsyncIterator
from typing import Literal

import httpx
import pytest
from fastapi import FastAPI
from redis import exceptions as redis_errors

from quiz.adapters.memory import store as memory_store
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
    listener = logs.configure_logging(out)
    resp = await http.get("/boom", headers={"X-Request-ID": "req-9"})
    assert (resp.status_code, resp.headers["X-Request-ID"]) == (500, "req-9")
    assert resp.json() == {"error": "INTERNAL", "message": "internal error"}
    listener.stop()  # writes the queued lines
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    [error] = [line for line in lines if "exception" in line]
    assert error["request_id"] == "req-9"
    assert "RuntimeError: boom" in error["exception"]
    [served] = [line for line in lines if line["event"] == "http_request"]
    assert (served["status"], served["request_id"]) == (500, "req-9")


class RefusingRedis:  # the ticket store's commands, each refused with ``error``
    def __init__(self, error: redis_errors.ResponseError) -> None:
        self.error = error

    async def set(self, *_: object, **__: object) -> None:
        raise self.error


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (redis_errors.ReadOnlyError("You can't write against a read only replica."), 503),
        (redis_errors.OutOfMemoryError("command not allowed when used memory > 'maxmemory'."), 503),
        (redis_errors.ResponseError("MISCONF Errors writing to the AOF file"), 503),
        (redis_errors.ResponseError("WRONGTYPE Operation against a key"), 500),
    ],
    ids=["READONLY", "OOM", "MISCONF", "another reply error"],
)
async def test_redis_write_refusals_answer_503_and_other_reply_errors_500(
    error: redis_errors.ResponseError, status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(Settings(store="redis", redis_url="redis://127.0.0.1:1/0"))
    monkeypatch.setattr(services_of(app).tickets, "_redis", RefusingRedis(error))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post("/sessions", json={"displayName": "Ana"})
    assert resp.status_code == status


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


async def test_quiz_info_counts_players_without_ranking_them(
    app: FastAPI, http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"quizId": "VOCAB-42", "timeLimitMs": 20_000, "windowMs": 600_000}
    assert (await http.post("/admin/quizzes", json=body, headers=TOKEN)).status_code == 201
    store = services_of(app).store
    for user in "abc":
        await store.join("VOCAB-42", user, user.upper(), f"c-{user}")

    def refuse(_: object) -> list[object]:
        pytest.fail("ranked every player")

    monkeypatch.setattr(memory_store, "standings", refuse)
    info = (await http.get("/quizzes/VOCAB-42")).json()
    assert (info["status"], info["players"]) == ("open", 3)
    monkeypatch.undo()  # quiz_ended carries the ranked top entries
    await store.end_by_host("VOCAB-42")
    assert (await http.get("/quizzes/VOCAB-42")).json()["status"] == "ended"


async def test_a_new_quiz_id_can_play_a_bank_quiz(http: httpx.AsyncClient) -> None:
    """``make demo`` starts a fresh run on every call, though the bank quiz itself has started."""
    for body in ({"quizId": "VOCAB-42"}, {"quizId": "DEMO-7K3Q", "bankQuizId": "VOCAB-42"}):
        assert (await http.post("/admin/quizzes", json=body, headers=TOKEN)).status_code == 201
    bank, run = [(await http.get(f"/quizzes/{q}")).json() for q in ("VOCAB-42", "DEMO-7K3Q")]
    assert run == bank | {"quizId": "DEMO-7K3Q"}


async def test_a_run_created_again_without_its_bank_quiz_is_a_conflict(
    http: httpx.AsyncClient,
) -> None:
    """A load run that re-posts an existing run ID learns that it exists, not that it is unknown."""
    run = {"quizId": "DEMO-7K3Q", "bankQuizId": "VOCAB-42"}
    assert (await http.post("/admin/quizzes", json=run, headers=TOKEN)).status_code == 201
    again = await http.post("/admin/quizzes", json={"quizId": "DEMO-7K3Q"}, headers=TOKEN)
    assert again.status_code == 409


@pytest.mark.parametrize(
    "body",
    [{"quizId": "VOCAB-42-7K3Q"}, {"quizId": "DEMO-7K3Q", "bankQuizId": "NOPE-1"}],
    ids=["no-bank-quiz-of-that-id", "unknown-bank-quiz"],
)
async def test_a_quiz_without_a_bank_quiz_is_not_found(
    http: httpx.AsyncClient, body: dict[str, str]
) -> None:
    resp = await http.post("/admin/quizzes", json=body, headers=TOKEN)
    assert (resp.status_code, resp.json()["error"]) == (404, "QUIZ_NOT_FOUND")
    assert (await http.get(f"/quizzes/{body['quizId']}")).status_code == 404
