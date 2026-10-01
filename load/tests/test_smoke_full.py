# AI-ASSISTED: the full-stack smoke run's node pick, rejoin check and run order against the app.
import asyncio

import httpx
import pytest
from websockets.asyncio.client import ClientConnection

import smoke_full
from bots import create_quizzes, parse
from quiz.obs import metrics
from smoke_full import SmokeError, check_kept, holder, open_sockets, play_one, recover, sign_in


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


class _Stop:
    async def wait(self) -> int:
        return 0


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Fake compose calls against the app: api-1 gets the socket; its stop closes the socket."""
    calls: list[tuple[str, ...]] = []
    counts = iter([{"api-1": 0, "api-2": 2}, {"api-1": 1, "api-2": 2}])
    sockets: list[ClientConnection] = []
    play = smoke_full.play_one

    async def playing(*args: object) -> tuple[ClientConnection, int, int]:
        ws, seq, score = await play(*args)  # type: ignore[arg-type]
        sockets.append(ws)
        return ws, seq, score

    async def stop(*command: str) -> _Stop:
        calls.append(command[1:])
        await sockets[0].close()
        return _Stop()

    def compose(*args: str) -> str:
        calls.append(("compose", *args))
        return "load-token" if "printenv" in args else ""

    monkeypatch.setattr(smoke_full, "compose", compose)
    monkeypatch.setattr(smoke_full, "node_get", lambda *_: "{}")
    monkeypatch.setattr(smoke_full, "sockets_by_node", lambda: next(counts))
    monkeypatch.setattr(smoke_full, "play_one", playing)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", stop)
    return calls


def test_the_run_stops_the_node_with_the_socket_and_starts_it_again(
    app_url: str, stack: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert smoke_full.main(["--url", app_url]) == 0
    assert stack[-2:] == [
        ("compose", "stop", "api-1"),
        ("compose", "up", "--detach", "--wait", "api-1"),
    ]
    out = capsys.readouterr().out
    assert "api-1 stopped: back in" in out
    assert out.endswith("smoke passed\n")
