# AI-ASSISTED: the HTTP edge in process: sessions, tickets, quiz info, mock admin and probes.
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from quiz.config import Settings
from quiz.main import create_app, services_of

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


async def create(http: httpx.AsyncClient, window_ms: int = 600_000) -> httpx.Response:
    body = {"quizId": "VOCAB-42", "timeLimitMs": 20_000, "windowMs": window_ms}
    return await http.post("/admin/quizzes", json=body, headers=TOKEN)


async def test_a_ticket_belongs_to_the_session_user(app: FastAPI, http: httpx.AsyncClient) -> None:
    session = await http.post("/sessions", json={"displayName": "  Ana "})
    user_id, token = session.json()["userId"], session.json()["sessionToken"]
    ticket = await http.post("/tickets", headers={"Authorization": f"Bearer {token}"})
    assert (session.status_code, ticket.status_code) == (201, 201)
    assert ticket.json()["expiresInMs"] == 30_000
    identity = await services_of(app).tickets.redeem(ticket.json()["ticket"])
    assert identity is not None
    assert (identity.user_id, identity.display_name) == (user_id, "Ana")


@pytest.mark.parametrize("auth", [None, "Bearer nope", "Basic abc", "Bearer "])
async def test_a_ticket_needs_a_known_session(http: httpx.AsyncClient, auth: str | None) -> None:
    resp = await http.post("/tickets", headers={} if auth is None else {"Authorization": auth})
    assert (resp.status_code, resp.headers["WWW-Authenticate"]) == (401, "Bearer")


async def test_a_session_needs_a_display_name(http: httpx.AsyncClient) -> None:
    for name in ("   ", "x" * 33, "x" * 129):
        assert (await http.post("/sessions", json={"displayName": name})).status_code == 422


async def test_quiz_info_and_unknown_ids_look_alike(http: httpx.AsyncClient) -> None:
    assert [(await create(http)).status_code for _ in range(2)] == [201, 409]
    info = await http.get("/quizzes/VOCAB-42")
    expected = {"quizId": "VOCAB-42", "title": "Everyday English", "questionCount": 10}
    assert info.json() == expected | {"status": "open", "players": 0}
    assert (await http.get("/readyz")).json() == {"status": "ready"}  # the memory store
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


async def test_admin_needs_the_token(http: httpx.AsyncClient) -> None:
    for headers in ({}, {"X-Admin-Token": "wrong"}):
        made = await http.post("/admin/quizzes", json={"quizId": "VOCAB-42"}, headers=headers)
        assert made.status_code == 404


async def test_admin_routes_exist_only_with_admin_mock(now: list[int]) -> None:
    async with client_of(app_with(now, admin_mock=False)) as http:
        assert (await create(http)).status_code == 404
        assert "/admin/quizzes" not in (await http.get("/openapi.json")).json()["paths"]


async def test_readyz_and_requests_report_an_unreachable_redis(now: list[int]) -> None:
    async with client_of(app_with(now, store="redis", redis_url="redis://127.0.0.1:1/0")) as http:
        ready = await http.get("/readyz")
        assert (ready.status_code, ready.json()) == (503, {"status": "unavailable"})
        session = await http.post("/sessions", json={"displayName": "Ana"})
        assert (session.status_code, session.json()["error"]) == (503, "UNAVAILABLE")
        assert (await http.get("/healthz")).status_code == 200


async def test_ready_and_tickets_on_redis(redis_url: str, now: list[int]) -> None:
    app = app_with(now, store="redis", redis_url=redis_url)
    async with app.router.lifespan_context(app), client_of(app) as http:
        assert (await http.get("/readyz")).json() == {"status": "ready"}
        session = (await http.post("/sessions", json={"displayName": "Ana"})).json()
        auth = {"Authorization": f"Bearer {session['sessionToken']}"}
        assert (await http.post("/tickets", headers=auth)).status_code == 201
