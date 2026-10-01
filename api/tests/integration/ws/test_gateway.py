# AI-ASSISTED: the /ws gateway rules, each driven through an in-process WebSocket client.
import io
import itertools
import json
import logging
from functools import partial
from typing import Any

import pytest
from starlette.testclient import TestClient, WebSocketDenialResponse, WebSocketTestSession

from quiz.adapters.ws.endpoint import UVICORN_LOGGERS, path_only
from quiz.config import Settings
from quiz.domain.session import Question
from quiz.main import create_app, services_of
from quiz.obs import logs

ORIGIN = {"origin": "http://localhost:8080"}
PING = '{"v":1,"type":"ping"}'


def client_of(peer: str = "testclient", **settings: Any) -> TestClient:  # noqa: ANN401
    return TestClient(create_app(Settings(**settings)), client=(peer, 40_000))


def session(client: TestClient, name: str = "Ann") -> tuple[str, str]:  # (userId, ticket)
    tickets = services_of(client.app).tickets  # type: ignore[arg-type]
    identity, token = client.portal.call(tickets.create_session, name)  # type: ignore[union-attr]
    issued = client.portal.call(tickets.issue_ticket, token)  # type: ignore[union-attr]
    assert issued is not None
    return identity.user_id, issued


def ticket(client: TestClient) -> str:
    return session(client)[1]


def connect(client: TestClient, ticket_: str | None, **kw: Any) -> Any:  # noqa: ANN401
    url = "/ws" if ticket_ is None else f"/ws?ticket={ticket_}"
    headers = {**kw.get("headers", ORIGIN)}  # copied: the client adds its own headers to it
    return client.websocket_connect(url, [kw.get("proto", "quiz.v1")], headers=headers)


def refused(client: TestClient, ticket_: str | None, **kwargs: Any) -> int:  # noqa: ANN401
    with pytest.raises(WebSocketDenialResponse) as denial, connect(client, ticket_, **kwargs):
        pass
    return denial.value.status_code


def until_close(ws: WebSocketTestSession) -> tuple[list[dict[str, Any]], int]:
    seen = []
    while (event := ws.receive())["type"] != "websocket.close":
        seen.append(json.loads(event["text"]))
    return seen, event["code"]


def test_the_upgrade_checks_origin_then_subprotocol_then_ticket() -> None:
    with client_of() as client:
        issued = ticket(client)
        for origin in ("http://evil.example", "http://localhost:8080/"):  # exact match only
            assert refused(client, issued, headers={"origin": origin}) == 403
        assert refused(client, issued, headers={}) == 403
        assert refused(client, issued, proto="chat") == 400
        with connect(client, issued) as ws:  # the refusals above did not spend the ticket
            assert ws.accepted_subprotocol == "quiz.v1"
            ws.send_text(PING)
            assert ws.receive_json() == {"v": 1, "type": "pong", "seq": None}
        for bad in (None, "unknown", issued):  # missing, unknown, used
            assert refused(client, bad) == 401


def test_the_caps_refuse_with_429_per_ip_and_503_per_process() -> None:
    with client_of(max_connections=3, per_ip_conn_cap=2) as one:
        other = TestClient(one.app, client=("10.0.0.9", 1))
        with connect(one, ticket(one)), connect(one, ticket(one)):
            assert refused(one, ticket(one)) == 429
            with connect(other, ticket(one)):
                assert refused(other, ticket(one)) == 503
        with connect(one, ticket(one)):  # closed sockets free their slots
            pass


def test_x_forwarded_for_counts_real_clients_only_behind_the_trusted_proxy() -> None:
    def via(ip: str) -> dict[str, str]:
        return {**ORIGIN, "x-forwarded-for": f"6.6.6.6, {ip}"}  # nginx appends its peer

    with client_of("172.18.0.2", per_ip_conn_cap=1) as nginx:  # inside the compose network
        with connect(nginx, ticket(nginx), headers=via("1.1.1.1")):
            assert refused(nginx, ticket(nginx), headers=via("1.1.1.1")) == 429
            with connect(nginx, ticket(nginx), headers=via("2.2.2.2")):
                pass
        direct = TestClient(nginx.app, client=("8.8.8.8", 1))  # untrusted: the header is ignored
        with connect(direct, ticket(nginx), headers=via("1.1.1.1")):
            assert refused(direct, ticket(nginx), headers=via("2.2.2.2")) == 429


def test_the_identity_comes_from_the_ticket_only() -> None:
    with client_of() as client:
        (user_id, issued), (other_id, _) = session(client), session(client, "Bob")
        store = services_of(client.app).store  # type: ignore[arg-type]
        create = partial(store.create_quiz, window_ms=60_000, time_limit_ms=20_000)
        client.portal.call(create, "VOCAB-42", (Question("q0", 1),))  # type: ignore[union-attr]
        join = {"v": 1, "type": "join", "quizId": "VOCAB-42", "displayName": "Ann"}
        with connect(client, issued) as ws:
            ws.send_json({**join, "userId": other_id})
            assert ws.receive_json()["code"] == "INVALID_MESSAGE"
            ws.send_json(join)
            assert ws.receive_json()["userId"] == user_id


def test_a_frame_above_16_kib_gets_message_too_large_then_close_1009() -> None:
    with client_of() as client, connect(client, ticket(client)) as ws:
        ws.send_text('{"v":1,"type":"ping","pad":"' + "x" * 16_384 + '"}')
        seen, code = until_close(ws)
    assert ([f["code"] for f in seen], code) == (["MESSAGE_TOO_LARGE"], 1009)


def test_the_token_bucket_runs_before_the_parser() -> None:
    with client_of() as client:
        client.app.state.gateway.clock = lambda: 0  # type: ignore[attr-defined]
        with connect(client, ticket(client)) as ws:
            for _ in range(40):  # the burst
                ws.send_text(PING)
                assert ws.receive_json()["type"] == "pong"
            ws.send_text("not json")
            error = ws.receive_json()
    assert (error["code"], error["requestType"]) == ("RATE_LIMITED", None)


def test_ten_seconds_of_abuse_get_rate_limited_then_close_1008() -> None:
    with client_of(rate_limit_per_s=1, rate_limit_burst=1) as client:
        client.app.state.gateway.clock = itertools.count(0, 250).__next__  # type: ignore[attr-defined]
        with connect(client, ticket(client)) as ws:
            for _ in range(42):  # 4 frames per second against 1 token per second
                ws.send_text(PING)
            seen, code = until_close(ws)
    assert [f["type"] for f in seen].count("pong") == 11  # one per token
    assert [f["code"] for f in seen if f["type"] == "error"] == ["RATE_LIMITED"] * 11
    assert code == 1008


def test_logs_hold_the_path_but_never_the_ticket(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="quiz")
    for name in UVICORN_LOGGERS:  # create_app() must attach the filter itself
        logging.getLogger(name).removeFilter(path_only)
    with client_of() as client:
        issued = ticket(client)
        refused(client, issued, proto="chat")
        with connect(client, issued):
            pass
    assert all(path_only in logging.getLogger(name).filters for name in UVICORN_LOGGERS)
    args = ("1.2.3.4:5", f"/ws?ticket={issued}", 403)  # a uvicorn handshake line
    line = logging.LogRecord("uvicorn.error", 20, "", 0, '%s - "WebSocket %s" %d', args, None)
    scope = {"type": "websocket", "path": "/ws", "query_string": f"ticket={issued}".encode()}
    started = ("1.2.3.4:5 - ASGI", 1, scope)  # uvicorn's trace line when a connection starts
    trace = logging.LogRecord("uvicorn.asgi", 5, "", 0, "%s [%d] Started scope=%s", started, None)
    assert all(logging.getLogger(r.name).filter(r) for r in (line, trace))
    lines = [r.getMessage() for r in [*caplog.records, line, trace]]
    assert len(lines) == 4
    assert all("/ws" in text and issued not in text and "?" not in text for text in lines)


def test_an_unreachable_ticket_store_answers_503() -> None:
    app = create_app(Settings(store="redis", redis_url="redis://127.0.0.1:1/0"))
    client = TestClient(app)  # no lifespan, so no script load: the ticket redeem is the first call
    assert refused(client, "some-ticket") == 503


def test_the_close_line_carries_the_quiz_id_and_the_connection_id() -> None:
    with client_of() as client:
        store = services_of(client.app).store  # type: ignore[arg-type]
        create = partial(store.create_quiz, window_ms=60_000, time_limit_ms=20_000)
        client.portal.call(create, "VOCAB-42", (Question("q0", 1),))  # type: ignore[union-attr]
        out = io.StringIO()
        logs.configure_logging(out)
        with connect(client, ticket(client)) as ws:
            ws.send_json({"v": 1, "type": "join", "quizId": "VOCAB-42", "displayName": "Ann"})
            assert ws.receive_json()["type"] == "joined"
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    [closed] = [line for line in lines if line["event"].startswith("ws /ws closed")]
    assert closed["quiz_id"] == "VOCAB-42"
    assert closed["request_id"]  # the connection's id
