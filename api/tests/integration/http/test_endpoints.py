# AI-ASSISTED: the HTTP edge in process: sessions, tickets, quiz info, mock admin, probes, logs.
import io
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from quiz.config import Settings
from quiz.main import create_app, services_of
from quiz.obs import logs

TOKEN = {"X-Admin-Token": "admin-test-token"}
NOT_FOUND = {"error": "QUIZ_NOT_FOUND", "message": "no such quiz"}


def app_with(now: list[int], **settings: object) -> FastAPI:
    base = {"store": "memory", "admin_mock": True, "admin_token": TOKEN["X-Admin-Token"]}
    return create_app(Settings.model_validate(base | settings), clock=lambda: now[0])


def client_of(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def now() -> list[int]:
    return [1_800_000_000_000]


@pytest.fixture
def app(now: list[int]) -> FastAPI:
    return app_with(now)


@pytest.fixture
async def http(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with client_of(app) as client:
        yield client


async def create(
    http: httpx.AsyncClient, quiz_id: str = "VOCAB-42", window_ms: int = 600_000
) -> httpx.Response:
    body = {"quizId": quiz_id, "timeLimitMs": 20_000, "windowMs": window_ms}
    return await http.post("/admin/quizzes", json=body, headers=TOKEN)


async def test_a_ticket_belongs_to_the_session_user(app: FastAPI, http: httpx.AsyncClient) -> None:
    session = await http.post("/sessions", json={"displayName": "  Ana "})
    assert session.status_code == 201
    user_id, token = session.json()["userId"], session.json()["sessionToken"]
    ticket = await http.post("/tickets", headers={"Authorization": f"Bearer {token}"})
    assert ticket.status_code == 201
    assert ticket.json()["expiresInMs"] == 30_000
    identity = await services_of(app).tickets.redeem(ticket.json()["ticket"])
    assert identity is not None
    assert (identity.user_id, identity.display_name) == (user_id, "Ana")


@pytest.mark.parametrize("auth", [None, "Bearer nope", "Basic abc", "Bearer "])
async def test_a_ticket_needs_a_known_session(http: httpx.AsyncClient, auth: str | None) -> None:
    headers = {} if auth is None else {"Authorization": auth}
    resp = await http.post("/tickets", headers=headers)
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("name", ["   ", "x" * 33, "x" * 129])
async def test_a_session_needs_a_display_name(http: httpx.AsyncClient, name: str) -> None:
    assert (await http.post("/sessions", json={"displayName": name})).status_code == 422


async def test_quiz_info_and_unknown_ids_look_alike(http: httpx.AsyncClient) -> None:
    assert (await create(http)).status_code == 201
    assert (await create(http)).status_code == 409
    info = await http.get("/quizzes/VOCAB-42")
    expected = {"quizId": "VOCAB-42", "title": "Everyday English", "questionCount": 10}
    assert info.json() == expected | {"status": "open", "players": 0}
    for unknown in ("NOPE-1", "ACAD-10", "vocab-42", "X" * 40, "a b"):  # ACAD-10: not created
        resp = await http.get(f"/quizzes/{unknown}")
        assert (resp.status_code, resp.json()) == (404, NOT_FOUND), unknown


async def test_quiz_reports_ended_after_the_deadline_with_nobody_connected(
    http: httpx.AsyncClient, now: list[int]
) -> None:
    await create(http, window_ms=1_000)
    now[0] += 999
    assert (await http.get("/quizzes/VOCAB-42")).json()["status"] == "open"
    now[0] += 1
    assert (await http.get("/quizzes/VOCAB-42")).json()["status"] == "ended"


async def test_host_end_announces_once(http: httpx.AsyncClient) -> None:
    await create(http)
    for _ in range(2):
        resp = await http.post("/admin/quizzes/VOCAB-42/end", headers=TOKEN)
        assert resp.json() == {"quizId": "VOCAB-42", "status": "ended", "endSeq": 1}
    assert (await http.get("/quizzes/VOCAB-42")).json()["status"] == "ended"
    assert (await http.post("/admin/quizzes/NOPE-1/end", headers=TOKEN)).status_code == 404


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}])
async def test_admin_needs_the_token(http: httpx.AsyncClient, headers: dict[str, str]) -> None:
    body = {"quizId": "VOCAB-42"}
    assert (await http.post("/admin/quizzes", json=body, headers=headers)).status_code == 404
    assert (await http.post("/admin/quizzes/VOCAB-42/end", headers=headers)).status_code == 404


async def test_admin_routes_exist_only_with_admin_mock(now: list[int]) -> None:
    async with client_of(app_with(now, admin_mock=False)) as http:
        assert (await create(http)).status_code == 404
        assert "/admin/quizzes" not in (await http.get("/openapi.json")).json()["paths"]


async def test_probes_on_the_memory_store(http: httpx.AsyncClient) -> None:
    assert (await http.get("/healthz")).json() == {"status": "ok"}
    assert (await http.get("/readyz")).json() == {"status": "ready"}


async def test_readyz_and_requests_report_an_unreachable_redis(now: list[int]) -> None:
    async with client_of(app_with(now, store="redis", redis_url="redis://127.0.0.1:1/0")) as http:
        ready = await http.get("/readyz")
        assert (ready.status_code, ready.json()) == (503, {"status": "unavailable"})
        session = await http.post("/sessions", json={"displayName": "Ana"})
        assert (session.status_code, session.json()["error"]) == (503, "UNAVAILABLE")
        assert (await http.get("/healthz")).status_code == 200


async def test_log_lines_are_json_with_quiz_and_request_ids(http: httpx.AsyncClient) -> None:
    out = io.StringIO()
    logs.configure_logging(out)
    await create(http)
    resp = await http.get("/quizzes/VOCAB-42", headers={"X-Request-ID": "req-1"})
    await http.get("/healthz")
    assert resp.headers["X-Request-ID"] == "req-1"
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert all({"quiz_id", "request_id", "event", "level"} <= line.keys() for line in lines)
    get = [line for line in lines if line.get("path") == "/quizzes/VOCAB-42"]
    assert [(g["quiz_id"], g["request_id"], g["status"]) for g in get] == [
        ("VOCAB-42", "req-1", 200)
    ]
    made = next(line for line in lines if line.get("path") == "/admin/quizzes")
    assert made["quiz_id"] == "VOCAB-42"
    served = [line["request_id"] for line in lines if line["logger"] == "quiz.http"]
    assert len(set(served)) == len(served) == 3  # one line and one fresh id per request


async def test_openapi_shows_every_endpoint_with_an_example(http: httpx.AsyncClient) -> None:
    spec = (await http.get("/openapi.json")).json()
    schemas = spec["components"]["schemas"]
    expected = {
        ("post", "/sessions"), ("post", "/tickets"), ("get", "/quizzes/{quiz_id}"),
        ("post", "/admin/quizzes"), ("post", "/admin/quizzes/{quiz_id}/end"),
        ("get", "/healthz"), ("get", "/readyz"), ("get", "/metrics"),
    }  # fmt: skip
    found = {(verb, path) for path, ops in spec["paths"].items() for verb in ops}
    assert expected <= found
    for verb, path in expected:
        ok = next(r for code, r in spec["paths"][path][verb]["responses"].items() if code < "300")
        [content] = ok["content"].values()
        ref = content.get("schema", {}).get("$ref", "")
        examples = schemas[ref.rsplit("/", 1)[-1]].get("examples") if ref else None
        assert "example" in content or examples, (verb, path)
