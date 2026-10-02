# AI-ASSISTED: the demo seed against a fake admin API on a local socket.
"""``scripts/seed.py`` posts to a stand-in for ``POST /admin/quizzes`` that answers each request
from a queue of status codes and records what it was sent."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast, override

import pytest

import seed
from quiz.adapters.http.routes import QUIZ_ID

TOKEN = "seed-test-token"  # noqa: S105 - the fake server's token


class FakeAdmin(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.statuses: list[int] = []
        self.received: list[tuple[str, str, dict[str, Any]]] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/api"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        admin = cast("FakeAdmin", self.server)
        admin.received.append((self.path, self.headers["X-Admin-Token"], body))
        self.send_response(admin.statuses.pop(0))
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Keep the test output free of request lines."""


@pytest.fixture
def admin() -> Iterator[FakeAdmin]:
    server = FakeAdmin()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_each_call_starts_a_new_run_of_the_bank_quiz_for_the_longest_window(
    admin: FakeAdmin, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    admin.statuses = [201, 201]
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("QUIZ_PORT", "9090")
    assert seed.main(["--api-url", admin.url]) == 0
    assert seed.main(["--api-url", admin.url]) == 0
    (path, token, first), (_, _, second) = admin.received
    assert (path, token) == ("/api/admin/quizzes", TOKEN)
    assert first["windowMs"] == second["windowMs"] == 60 * 60_000
    assert first["quizId"] != second["quizId"]
    for body in (first, second):
        assert body["quizId"].startswith("VOCAB-42-")
        assert QUIZ_ID.fullmatch(body["quizId"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == [
        f"Quiz ID:    {first['quizId']} (open for 60 min)",
        f"Player URL: http://localhost:9090/q/{first['quizId']}",
    ]


def test_a_run_code_already_taken_is_drawn_again(admin: FakeAdmin) -> None:
    admin.statuses = [409, 201]
    codes = iter(["AAAA", "BBBB"])
    assert seed.create_quiz(admin.url, TOKEN, "BIZ-20", lambda: next(codes)) == "BIZ-20-BBBB"
    assert [body["quizId"] for _, _, body in admin.received] == ["BIZ-20-AAAA", "BIZ-20-BBBB"]


def test_another_refusal_stops_with_the_status(
    admin: FakeAdmin, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    admin.statuses = [404]
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    assert seed.main(["--api-url", admin.url]) == 1
    err = capsys.readouterr().err
    assert "HTTP 404" in err
    assert "Is the stack up?" not in err  # it answered


def test_an_unreachable_stack_points_at_make_demo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    assert seed.main(["--api-url", "http://127.0.0.1:9/api"]) == 1
    assert "make demo starts it" in capsys.readouterr().err


def test_no_token_stops_before_any_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert seed.main(["--api-url", "http://127.0.0.1:9/api"]) == 2
    assert "set ADMIN_TOKEN" in capsys.readouterr().err
