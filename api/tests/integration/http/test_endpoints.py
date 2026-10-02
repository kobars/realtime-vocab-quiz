# AI-ASSISTED: the HTTP edge in process: sessions, tickets, quiz info, mock admin, probes, logs.
import io
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient

from quiz.config import Settings
from quiz.main import create_app, services_of
from quiz.obs import logs

TOKEN = {"X-Admin-Token": "admin-test-token"}
NOT_FOUND = {"error": "QUIZ_NOT_FOUND", "message": "no such quiz"}
NO_ROUTE = {"error": "NOT_FOUND", "message": "Not Found"}


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
    assert resp.json() == {"error": "UNAUTHORIZED", "message": "unknown session"}


@pytest.mark.parametrize("scheme", ["Bearer ", "bearer ", "BEARER ", "Bearer  "])
async def test_the_bearer_scheme_ignores_case_and_extra_spaces(
    http: httpx.AsyncClient, scheme: str
) -> None:
    token = (await http.post("/sessions", json={"displayName": "Ana"})).json()["sessionToken"]
    auth = {"Authorization": scheme + token}
    assert (await http.post("/tickets", headers=auth)).status_code == 201
    swapped = {"Authorization": scheme + token.swapcase()}  # the token itself keeps its case
    assert (await http.post("/tickets", headers=swapped)).status_code == 401


async def test_every_error_has_one_body_shape(http: httpx.AsyncClient) -> None:
    bodies = [{"displayName": "   "}, {"displayName": "x" * 33}, {"displayName": "x" * 129}, {}]
    for body in bodies:
        resp = await http.post("/sessions", json=body)
        assert (resp.status_code, resp.json()["error"]) == (422, "INVALID_MESSAGE"), body
        assert resp.json().keys() == {"error", "message"}, body
        assert "INVALID_MESSAGE" not in resp.json()["message"], body
    bad_json = await http.post("/sessions", content=b"{bad")
    assert (bad_json.status_code, bad_json.json()["error"]) == (422, "INVALID_MESSAGE")
    for path in ("/nope", "/quizzes"):
        resp = await http.get(path)
        assert (resp.status_code, resp.json()) == (404, NO_ROUTE), path
    wrong_method = await http.get("/sessions")
    assert (wrong_method.status_code, wrong_method.headers["Allow"]) == (405, "POST")
    assert wrong_method.json() == {"error": "METHOD_NOT_ALLOWED", "message": "Method Not Allowed"}


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


async def test_host_end_marks_then_announces_once(http: httpx.AsyncClient) -> None:
    await create(http)
    for _ in range(2):
        resp = await http.post("/admin/quizzes/VOCAB-42/end", headers=TOKEN)
        assert resp.json() == {"quizId": "VOCAB-42", "status": "ended", "endSeq": 1}
    assert (await http.get("/quizzes/VOCAB-42")).json()["status"] == "ended"
    for unknown in ("NOPE-1", "vocab-42"):
        resp = await http.post(f"/admin/quizzes/{unknown}/end", headers=TOKEN)
        assert (resp.status_code, resp.json()) == (404, NOT_FOUND), unknown


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}])
async def test_admin_needs_the_token(http: httpx.AsyncClient, headers: dict[str, str]) -> None:
    await create(http)
    body = {"quizId": "VOCAB-42"}
    assert (await http.post("/admin/quizzes", json=body, headers=headers)).status_code == 404
    assert (await http.post("/admin/quizzes/VOCAB-42/end", headers=headers)).status_code == 404
    assert (await http.get("/quizzes/VOCAB-42")).json()["status"] == "open"


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}])
async def test_admin_paths_look_like_unknown_paths_without_the_token(
    http: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    calls = [
        ("GET", "/admin/quizzes", None),  # a known path with the wrong method
        ("POST", "/admin/quizzes", b"{bad"),  # a body that does not parse
        ("POST", "/admin/nope", None),
        ("DELETE", "/admin/quizzes/VOCAB-42/end", None),
        ("GET", "/admin", None),
    ]
    for method, path, body in calls:
        resp = await http.request(method, path, content=body, headers=headers)
        assert (resp.status_code, resp.json()) == (404, NO_ROUTE), (method, path)
        assert "Allow" not in resp.headers, (method, path)


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


async def test_log_lines_are_json_with_quiz_and_request_ids(http: httpx.AsyncClient) -> None:
    out = io.StringIO()
    listener = logs.configure_logging(out)
    await create(http)
    resp = await http.get("/quizzes/VOCAB-42", headers={"X-Request-ID": "req-1"})
    await http.get("/healthz")
    assert resp.headers["X-Request-ID"] == "req-1"
    listener.stop()  # writes the queued lines
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
        ("get", "/healthz"), ("get", "/readyz"), ("get", "/metrics"),
    }  # fmt: skip
    found = {(verb, path) for path, ops in spec["paths"].items() for verb in ops}
    assert expected <= found
    assert not any(path.startswith("/admin") for path in spec["paths"])  # the mock stays hidden
    assert "CreateQuiz" not in schemas
    for verb, path in expected:
        ok = next(r for code, r in spec["paths"][path][verb]["responses"].items() if code < "300")
        [content] = ok["content"].values()
        ref = content.get("schema", {}).get("$ref", "")
        examples = schemas[ref.rsplit("/", 1)[-1]].get("examples") if ref else None
        assert "example" in content or examples, (verb, path)


def test_an_outage_in_a_websocket_route_reaches_the_websocket_layer(now: list[int]) -> None:
    app = app_with(now)

    async def broken(websocket: WebSocket) -> None:
        await websocket.accept()
        msg = "store unreachable"
        raise ConnectionError(msg)  # one of the outages that the HTTP handler maps

    app.add_api_websocket_route("/broken", broken)
    with (
        TestClient(app) as client,
        pytest.raises(ConnectionError, match="store unreachable"),
        client.websocket_connect("/broken") as ws,
    ):
        ws.receive_text()
