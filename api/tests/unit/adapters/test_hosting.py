# AI-ASSISTED: self-service hosting over HTTP on the memory store: banks, create, end, every limit.
import hashlib
import io
import re
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from quiz.adapters.http import hosting
from quiz.config import Settings
from quiz.main import create_app, services_of
from quiz.obs import logs

ADMIN = {"X-Admin-Token": "admin-test-token"}
NOW = 1_800_000_000_000
NO_ROUTE = {"error": "NOT_FOUND", "message": "Not Found"}
RUN_ID = re.compile(r"VOCAB-42-[A-HJ-NP-Z2-9]{4}")


def app_with(now: list[int], **settings: object) -> FastAPI:
    base = {"store": "memory", "admin_mock": True, "admin_token": ADMIN["X-Admin-Token"]}
    return create_app(Settings.model_validate(base | settings), clock=lambda: now[0])


def client_of(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def now() -> list[int]:
    return [NOW]


@pytest.fixture
def app(now: list[int]) -> FastAPI:
    return app_with(now)


@pytest.fixture
async def http(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with client_of(app) as client:
        yield client


async def host(http: httpx.AsyncClient, bank: str = "VOCAB-42", **headers: str) -> httpx.Response:
    return await http.post("/quizzes", json={"bankQuizId": bank}, headers=headers)


async def end(http: httpx.AsyncClient, quiz_id: str, token: str | None) -> httpx.Response:
    headers = {} if token is None else {"X-Host-Token": token}
    return await http.post(f"/quizzes/{quiz_id}/end", headers=headers)


async def test_banks_lists_the_quizzes_a_visitor_may_host(http: httpx.AsyncClient) -> None:
    resp = await http.get("/banks")
    assert resp.status_code == 200
    assert [(b["id"], b["questionCount"]) for b in resp.json()] == [
        ("VOCAB-42", 10),
        ("BIZ-20", 10),
        ("ACAD-10", 10),
    ]
    assert resp.json()[0]["title"] == "Everyday English"


async def test_hosting_starts_a_run_and_keeps_only_the_token_hash(
    app: FastAPI, http: httpx.AsyncClient
) -> None:
    resp = await host(http)
    assert resp.status_code == 201
    body = resp.json()
    assert RUN_ID.fullmatch(body["quizId"])
    assert body["sharePath"] == f"/q/{body['quizId']}"
    assert (body["windowMs"], body["endsAtMs"]) == (1_800_000, NOW + 1_800_000)
    assert len(body["hostToken"]) >= 43  # 32 random bytes in base64url
    stored = await services_of(app).store.host_token_hash(body["quizId"])
    assert stored == hashlib.sha256(body["hostToken"].encode()).hexdigest()
    info = (await http.get(f"/quizzes/{body['quizId']}")).json()
    assert (info["status"], info["title"]) == ("open", "Everyday English")


@pytest.mark.parametrize(
    "body",
    [{}, {"bankQuizId": "NOPE-1"}, {"bankQuizId": 42}, {"bankQuizId": "VOCAB-42", "windowMs": 1}],
    ids=["missing", "unknown-bank", "wrong-type", "extra-field"],
)
async def test_a_bad_hosting_body_is_invalid(http: httpx.AsyncClient, body: object) -> None:
    resp = await http.post("/quizzes", json=body)
    assert (resp.status_code, resp.json()["error"]) == (422, "INVALID_MESSAGE")


async def test_a_run_code_already_taken_is_drawn_again(
    http: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken = {"quizId": "VOCAB-42-AAAA", "bankQuizId": "VOCAB-42"}
    assert (await http.post("/admin/quizzes", json=taken, headers=ADMIN)).status_code == 201
    codes = iter(["AAAA", "BBBB"])
    monkeypatch.setattr(hosting, "run_code", lambda: next(codes))
    assert (await host(http)).json()["quizId"] == "VOCAB-42-BBBB"
    monkeypatch.setattr(hosting, "run_code", lambda: "AAAA")  # every draw taken
    resp = await host(http)
    assert (resp.status_code, resp.json()["error"]) == (503, "UNAVAILABLE")


# A self-hosted winner keeps its place (cap 2: its run and the loser's next one fill it); the
# member of a winner without a host token was the loser's alone and is released (cap 1).
@pytest.mark.parametrize(("winner", "cap"), [("hosted", 2), ("admin", 1)])
async def test_a_run_code_taken_meanwhile_keeps_only_the_winners_place(
    now: list[int], monkeypatch: pytest.MonkeyPatch, winner: str, cap: int
) -> None:
    app = app_with(now, hosting_max_open=cap)
    store = services_of(app).store
    async with client_of(app) as http:
        monkeypatch.setattr(hosting, "run_code", lambda: "AAAA")
        if winner == "hosted":
            assert (await host(http)).status_code == 201
        else:
            taken = {"quizId": "VOCAB-42-AAAA", "bankQuizId": "VOCAB-42"}
            assert (await http.post("/admin/quizzes", json=taken, headers=ADMIN)).status_code == 201
        codes = iter(["AAAA", "BBBB"])
        monkeypatch.setattr(hosting, "run_code", lambda: next(codes))

        async def unseen(_quiz_id: str) -> None:  # the winner's create lands after this read
            return None

        monkeypatch.setattr(store, "read_seq", unseen)
        assert (await host(http)).json()["quizId"] == "VOCAB-42-BBBB"
        monkeypatch.setattr(hosting, "run_code", lambda: "CCCC")
        full = await host(http)
        assert (full.status_code, full.json()["error"]) == (503, "HOSTING_FULL")


async def test_a_bank_quiz_left_out_of_hosting_banks_cannot_be_hosted(now: list[int]) -> None:
    async with client_of(app_with(now, hosting_banks="BIZ-20")) as http:
        assert [b["id"] for b in (await http.get("/banks")).json()] == ["BIZ-20"]
        assert (await host(http)).status_code == 422
        assert (await host(http, "BIZ-20")).status_code == 201


async def test_creations_are_limited_per_client_address(now: list[int]) -> None:
    async with client_of(app_with(now, hosting_per_ip=2)) as http:
        ana, bob = {"X-Forwarded-For": "203.0.113.7"}, {"X-Forwarded-For": "203.0.113.8"}
        assert [(await host(http, **ana)).status_code for _ in range(2)] == [201, 201]
        refused = await host(http, **ana)
        assert (refused.status_code, refused.json()["error"]) == (429, "RATE_LIMITED")
        assert refused.headers["Retry-After"] == "300"  # 600 s for 2 creations
        assert (await host(http, **bob)).status_code == 201  # another address has its own


async def test_the_cap_of_open_hosted_quizzes_answers_hosting_full(now: list[int]) -> None:
    async with client_of(app_with(now, hosting_max_open=1)) as http:
        first = (await host(http)).json()
        full = await host(http)
        assert (full.status_code, full.json()["error"]) == (503, "HOSTING_FULL")
        assert (await end(http, first["quizId"], first["hostToken"])).status_code == 200
        assert (await host(http)).status_code == 201  # the host's end freed the place
        now[0] += 1_800_000
        assert (await host(http)).status_code == 201  # and so does the end of the window


async def test_the_admin_end_also_frees_the_place(now: list[int]) -> None:
    async with client_of(app_with(now, hosting_max_open=1)) as http:
        first = (await host(http)).json()
        path = f"/admin/quizzes/{first['quizId']}/end"
        assert (await http.post(path, headers=ADMIN)).status_code == 200
        assert (await host(http)).status_code == 201


async def test_a_retried_end_frees_the_place_its_first_try_kept(
    now: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = app_with(now, hosting_max_open=1)
    store = services_of(app).store
    release = store.release_hosted
    failures = iter([ConnectionError("store unreachable")])

    async def flaky(quiz_id: str) -> None:
        if (error := next(failures, None)) is not None:
            raise error
        await release(quiz_id)

    monkeypatch.setattr(store, "release_hosted", flaky)
    async with client_of(app) as http:
        first = (await host(http)).json()
        assert (await end(http, first["quizId"], first["hostToken"])).status_code == 503
        again = await end(http, first["quizId"], first["hostToken"])
        assert (again.status_code, again.json()["error"]) == (409, "QUIZ_ENDED")
        assert (await host(http)).status_code == 201


async def test_the_host_token_ends_the_quiz_once(http: httpx.AsyncClient) -> None:
    hosted = (await host(http)).json()
    resp = await end(http, hosted["quizId"], hosted["hostToken"])
    assert resp.status_code == 200
    assert resp.json() == {"quizId": hosted["quizId"], "status": "ended", "endSeq": 1}
    assert (await http.get(f"/quizzes/{hosted['quizId']}")).json()["status"] == "ended"
    again = await end(http, hosted["quizId"], hosted["hostToken"])
    assert (again.status_code, again.json()["error"]) == (409, "QUIZ_ENDED")


async def test_a_quiz_past_its_window_cannot_be_ended(
    http: httpx.AsyncClient, now: list[int]
) -> None:
    hosted = (await host(http)).json()
    now[0] += hosted["windowMs"]
    resp = await end(http, hosted["quizId"], hosted["hostToken"])
    assert (resp.status_code, resp.json()["error"]) == (409, "QUIZ_ENDED")


async def test_ending_needs_the_host_token_of_that_quiz(http: httpx.AsyncClient) -> None:
    hosted, other = (await host(http)).json(), (await host(http)).json()
    admin = {"quizId": "ADMIN-RUN", "bankQuizId": "VOCAB-42"}
    assert (await http.post("/admin/quizzes", json=admin, headers=ADMIN)).status_code == 201
    for quiz_id, token in [
        (hosted["quizId"], None),
        (hosted["quizId"], ""),
        (hosted["quizId"], other["hostToken"]),
        ("ADMIN-RUN", hosted["hostToken"]),  # an admin quiz has no host token
    ]:
        resp = await end(http, quiz_id, token)
        assert (resp.status_code, resp.json()["error"]) == (403, "FORBIDDEN"), (quiz_id, token)
    assert (await http.get(f"/quizzes/{hosted['quizId']}")).json()["status"] == "open"
    for quiz_id in ["NOPE-1234", "lower-case"]:
        missing = await end(http, quiz_id, hosted["hostToken"])
        assert (missing.status_code, missing.json()["error"]) == (404, "QUIZ_NOT_FOUND")


async def test_a_request_from_another_origin_is_forbidden(http: httpx.AsyncClient) -> None:
    hosted = (await host(http, Origin="http://localhost:8080")).json()
    evil = {"Origin": "https://evil.example"}
    resp = await host(http, **evil)
    assert (resp.status_code, resp.json()["error"]) == (403, "FORBIDDEN")
    path = f"/quizzes/{hosted['quizId']}/end"
    ended = await http.post(path, headers=evil | {"X-Host-Token": hosted["hostToken"]})
    assert ended.status_code == 403


async def test_hosting_off_removes_the_routes(now: list[int]) -> None:
    async with client_of(app_with(now, public_hosting=False)) as http:
        for resp in [
            await host(http),
            await http.get("/banks"),
            await end(http, "VOCAB-42-AAAA", "token"),
        ]:
            assert (resp.status_code, resp.json()) == (404, NO_ROUTE)
        assert "/banks" not in (await http.get("/openapi.json")).json()["paths"]


async def test_no_log_line_carries_the_host_token(http: httpx.AsyncClient) -> None:
    out = io.StringIO()
    listener = logs.configure_logging(out)
    hosted = (await host(http)).json()
    await end(http, hosted["quizId"], hosted["hostToken"])
    listener.stop()  # writes the queued lines
    assert hosted["quizId"] in out.getvalue()
    assert hosted["hostToken"] not in out.getvalue()
