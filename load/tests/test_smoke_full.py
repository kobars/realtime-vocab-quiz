# AI-ASSISTED: the full-stack smoke run's node pick, rejoin check and run order against the app.
import asyncio
import json
import subprocess
from dataclasses import replace
from typing import Any

import httpx
import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.protocol import State

import smoke_full
from bots import create_quizzes, parse
from quiz.obs import metrics
from smoke_full import SmokeError, check_kept, holder, open_sockets, play_one, recover, sign_in

pytest_plugins = ["app_server"]  # the app_url fixture


def test_open_sockets_reads_the_nodes_ws_connections_gauge() -> None:
    before = open_sockets(metrics.exposition()[0].decode())
    with metrics.WS_CONNECTIONS.track_inprogress():
        assert open_sockets(metrics.exposition()[0].decode()) == before + 1
    with pytest.raises(SmokeError, match="no ws_connections"):
        open_sockets("# TYPE other gauge\nother 1.0\n")


def test_the_holder_is_the_one_node_whose_sockets_grew() -> None:
    assert holder({"api-1": 2, "api-2": 0}, {"api-1": 2, "api-2": 1}) == "api-2"
    for after in ({"api-1": 2, "api-2": 0}, {"api-1": 3, "api-2": 1}):
        with pytest.raises(SmokeError, match="cannot tell"):
            holder({"api-1": 2, "api-2": 0}, after)


async def test_a_rejoin_after_the_socket_drops_resyncs_with_the_kept_score(app_url: str) -> None:
    opts = parse(["--admin-token", "load-token", "--url", app_url])
    await create_quizzes(opts)
    async with httpx.AsyncClient(base_url=app_url) as http:
        await sign_in(http)
        ws, seq, score = await play_one(http, opts)
        await ws.close()
        joined, snapshot = await recover(ws, http, opts, seq)
    assert score >= 100  # the correct choice scored
    check_kept(score, joined, snapshot)
    with pytest.raises(SmokeError, match="not kept"):
        check_kept(score + 1, joined, snapshot)


def test_compose_gives_up_on_a_command_that_never_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(command: list[str], **kwargs: Any) -> None:  # noqa: ANN401
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(SmokeError, match="docker compose exec: no exit within 120 s"):
        smoke_full.compose("exec", "-T", "api-1", "true")


def test_the_entry_is_nginxs_published_port_unless_an_option_names_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke_full, "compose", lambda *_: "127.0.0.1:18080")
    entry = parse(smoke_full.stack_entry())
    assert (entry.url, entry.origin) == ("http://127.0.0.1:18080/api", "http://127.0.0.1:18080")
    assert parse([*smoke_full.stack_entry(), "--url", "http://h/api"]).url == "http://h/api"


class _Broadcasts:  # a socket that answers nothing but a broadcast every 10 ms
    async def send(self, _: str) -> None:
        pass

    async def recv(self) -> str:
        await asyncio.sleep(0.01)
        return json.dumps({"type": "leaderboard"})


async def test_a_reply_that_never_comes_times_out_despite_broadcasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke_full, "REPLY_S", 0.05)
    async with asyncio.timeout(1):
        with pytest.raises(TimeoutError):
            await smoke_full.request(_Broadcasts(), "next", "question", questionIndex=1)  # type: ignore[arg-type]


async def test_a_failed_join_closes_its_socket(
    app_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[ClientConnection] = []

    async def connecting(*args: Any, **kwargs: Any) -> ClientConnection:  # noqa: ANN401
        opened.append(await connect(*args, **kwargs))
        return opened[-1]

    opts = replace(parse(["--url", app_url]), quiz_ids=("NOPE-1",))
    async with httpx.AsyncClient(base_url=app_url) as http:
        await sign_in(http)
        monkeypatch.setattr(smoke_full, "connect", connecting)
        with pytest.raises(SmokeError, match="join"):
            await smoke_full.join(http, opts)
    assert [ws.state for ws in opened] == [State.CLOSED]


def test_only_an_answer_that_earned_points_counts() -> None:
    result = {"correct": True, "late": False, "pointsAwarded": 120, "score": 120}
    assert smoke_full.scored(result) == 120
    for unscored in ({"correct": False}, {"late": True}, {"pointsAwarded": 0}):
        with pytest.raises(SmokeError, match="earned no points"):
            smoke_full.scored(result | unscored)


class _Stop:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b"no such service" if self.returncode else b""


@pytest.fixture
def failing() -> set[str]:
    """The compose commands the fake stack fails: a failed ``stop`` leaves the socket open."""
    return set()


@pytest.fixture
def stack(failing: set[str], monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Fake compose calls against the app: api-1 gets the socket; its stop closes the socket."""
    calls: list[tuple[str, ...]] = []
    counts = iter([{"api-1": 0, "api-2": 2}, {"api-1": 1, "api-2": 2}])
    sockets: list[ClientConnection] = []
    play = smoke_full.play_one

    async def playing(*args: object) -> tuple[ClientConnection, int, int]:
        ws, seq, score = await play(*args)  # type: ignore[arg-type]
        sockets.append(ws)
        return ws, seq, score

    async def stop(*command: str, **_: object) -> _Stop:
        calls.append(command[1:])
        if "stop" in failing:
            return _Stop(1)
        await sockets[0].close()
        return _Stop(0)

    def compose(*args: str) -> str:
        calls.append(("compose", *args))
        if args[0] in failing:
            msg = f"docker compose {args[0]}: failed"
            raise SmokeError(msg)
        return "load-token" if "printenv" in args else ""

    monkeypatch.setattr(smoke_full, "compose", compose)
    monkeypatch.setattr(smoke_full, "node_get", lambda *_: "{}")
    monkeypatch.setattr(smoke_full, "sockets_by_node", lambda: next(counts))
    monkeypatch.setattr(smoke_full, "play_one", playing)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", stop)
    monkeypatch.setattr(smoke_full, "RECOVER_S", 0.5)
    return calls


def test_the_run_stops_the_node_with_the_socket_and_starts_it_again(
    app_url: str, stack: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    """``start`` keeps the stopped container: ``up`` would recreate it without the shell's env."""
    assert smoke_full.main(["--url", app_url, "--origin", parse([]).origin]) == 0
    assert stack[-2:] == [
        ("compose", "stop", "api-1"),
        ("compose", "start", "--wait", "api-1"),
    ]
    out = capsys.readouterr().out
    assert "api-1 stopped: back in" in out
    assert out.endswith("smoke passed\n")


def test_a_failed_stop_and_start_are_reported_around_the_runs_own_failure(
    app_url: str,
    stack: list[tuple[str, ...]],
    failing: set[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    failing.update({"stop", "start"})  # the socket stays open, so the rejoin times out
    assert smoke_full.main(["--url", app_url, "--origin", parse([]).origin]) == 1
    assert stack[-1] == ("compose", "start", "--wait", "api-1")
    assert capsys.readouterr().err == (
        "smoke failed: docker compose stop: no such service; "
        "no resynced reconnect within 0 s; docker compose start: failed\n"
    )
