# AI-ASSISTED: the bots' frame shortcut, CLI, reconnect rules and a swarm run against the app.
import asyncio
import contextlib
import itertools
import json
import threading
import time
from collections.abc import Callable, Iterable, Iterator

import httpx
import pytest
import uvicorn
from pydantic import SecretStr

import bots
from bots import BOARD_HEAD, converse, parse, play, swarm
from player import DEAD_LINK, NORMAL, OVERLOAD, Backoff, BoardWait, Player, Recorder
from quiz.config import Settings
from quiz.contracts.codec import encode_broadcast
from quiz.contracts.messages import Entry, Leaderboard
from quiz.main import create_app

OPTS = parse(["--timeout-ms", "200"])
TOKENS = httpx.MockTransport(
    lambda _: httpx.Response(201, json={"sessionToken": "s", "ticket": "t"})
)


@pytest.fixture
def app_url() -> Iterator[str]:
    app = create_app(Settings(admin_mock=True, admin_token=SecretStr("load-token")))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run)
    thread.start()
    while not server.started:
        assert thread.is_alive()
        time.sleep(0.01)
    yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    server.should_exit = True
    thread.join()


def bot(deadline_s: float = 5) -> Player:
    rec = Recorder()
    return Player("VOCAB-42", "bot", rec, BoardWait(rec, 1), {}, time.monotonic() + deadline_s)


def waiting(p: Player, *, sent: bool = True) -> None:
    """An open timed answer (sent, or still in its think time) and an open board wait."""
    now = time.monotonic()
    p.answer, p.timed = (9, "sub", 0), True
    p.sent_at, p.answer_due = (now, None) if sent else (None, now + 1)
    p.board.accepted(150, now)


async def play_closes(
    monkeypatch: pytest.MonkeyPatch, p: Player, steps: Iterable[Callable[[Player], int]]
) -> None:
    """Run ``play`` with each socket replaced by the next step, which returns the close code."""
    calls = iter(steps)

    async def socket(*_: object) -> int:
        return next(calls)(p)

    monkeypatch.setattr(bots, "connect", lambda *_, **__: contextlib.nullcontext())
    monkeypatch.setattr(bots, "converse", socket)
    monkeypatch.setattr("random.random", lambda: 0.0)  # no backoff wait
    async with httpx.AsyncClient(transport=TOKENS, base_url="http://quiz") as http:
        await play(p, http, OPTS)


def test_the_board_header_regex_reads_the_servers_encoding() -> None:
    entry = Entry(rank=1, userId="u1", displayName="Ann", score=150)
    raw = encode_broadcast(
        Leaderboard(seq=12, rebase=True, playerCount=1, onlineCount=1, entries=[entry])
    ).decode()
    head = BOARD_HEAD.match(raw)
    assert head is not None
    assert (head[1], head[2]) == ("12", "true")


def test_the_cli_checks_its_options() -> None:
    opts = parse(["--url", "https://quiz.example/api/", "--quizzes", "2", "--bots", "4"])
    assert opts.quiz_ids == ("VOCAB-42", "BIZ-20")
    assert opts.ws_url == "wss://quiz.example/ws"
    for bad in ("--quizzes 4", "--bots 0", "--accuracy 1.5", "--duration -1", "--duration 0",
                "--ramp nan", "--duration inf", "--think-ms -3", "--timeout-ms 0"):  # fmt: skip
        with pytest.raises(SystemExit):
            parse(bad.split())


@pytest.mark.parametrize("sent", [True, False])
async def test_a_reconnect_drops_the_open_answer(
    monkeypatch: pytest.MonkeyPatch,
    sent: bool,  # noqa: FBT001
) -> None:
    def lost(p: Player) -> int:
        waiting(p, sent=sent)
        return DEAD_LINK

    def rejoined(p: Player) -> int:
        assert (p.answer, p.answer_due, p.board.pending) == (None, None, [])
        joined = {"type": "joined", "userId": "u", "finished": True,
                  "cursor": 9, "cursorOpen": False}  # fmt: skip
        p.handle(joined, time.monotonic(), Backoff(), 0)
        assert p.settled(time.monotonic())
        return NORMAL

    p = bot()
    await play_closes(monkeypatch, p, [lost, rejoined])
    assert (p.rec.counts["answer_missing"], p.rec.counts["reconnects"]) == (sent, 1)


@pytest.mark.parametrize("stops", ["by an error", "at the quiz end"])
async def test_a_stopping_player_counts_its_open_waits(
    monkeypatch: pytest.MonkeyPatch, stops: str
) -> None:
    def stop(p: Player) -> int:
        waiting(p)
        if stops == "by an error":
            raise KeyError
        p.ended = True
        return NORMAL

    p = bot()
    with pytest.raises(KeyError) if stops == "by an error" else contextlib.nullcontext():
        await play_closes(monkeypatch, p, [stop])
    assert (p.rec.counts["answer_missing"], p.rec.counts["board_missing"]) == (1, 1)


async def test_reconnects_end_at_a_final_close_or_after_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = bot()
    await play_closes(monkeypatch, p, [lambda _: DEAD_LINK, lambda _: 1008])
    assert (p.rec.counts["reconnects"], p.rec.counts["final_close_1008"], p.ended) == (1, 1, True)
    for closes in (itertools.repeat(lambda _: DEAD_LINK), [lambda _: OVERLOAD]):
        p = bot(deadline_s=0.1)
        await asyncio.wait_for(play_closes(monkeypatch, p, closes), 2)
        assert time.monotonic() >= p.deadline + 0.19  # the drain of 200 ms, not earlier


class Socket:
    """Takes what the bot sends; never answers."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.receives = 0

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw)["type"])

    async def recv(self) -> str:
        self.receives += 1
        await asyncio.sleep(3600)
        return ""

    async def close(self, code: int) -> None:
        pass


async def test_converse_sleeps_to_its_next_timer_and_closes_at_the_stop() -> None:
    p, ws = bot(), Socket()
    p.answer_due = time.monotonic() - 1  # left by an answer whose late reply came after a retry
    p.board.accepted(150, time.monotonic())
    code = await asyncio.wait_for(converse(ws, p, Backoff(), OPTS, time.monotonic() + 0.3), 2)  # type: ignore[arg-type]
    assert (code, ws.sent, ws.receives) == (NORMAL, ["join"], 1)


async def test_converse_sends_nothing_once_the_quiz_ended() -> None:
    p, ws = bot(), Socket()
    p.ended = True
    assert await converse(ws, p, Backoff(), OPTS, time.monotonic() + 1) == NORMAL  # type: ignore[arg-type]
    assert ws.sent == []


async def test_a_swarm_plays_whole_quizzes_against_the_app(app_url: str) -> None:
    flags = "--quizzes 2 --bots 3 --think-ms 0 --duration 1 --ramp 0 --timeout-ms 300"
    opts = parse([*flags.split(), "--url", app_url])
    async with httpx.AsyncClient(base_url=app_url, headers={"X-Admin-Token": "load-token"}) as http:
        for quiz_id in opts.quiz_ids:
            (await http.post("/admin/quizzes", json={"quizId": quiz_id})).raise_for_status()
    rec = await swarm(opts)
    assert rec.counts["cohorts"] > 3  # a slot starts a new cohort after its player finishes
    assert rec.counts["answers"] >= 30  # the first cohort of each slot answers all ten
    assert len(rec.answer_ms) == rec.counts["answers"]
    for failure in ("answer_timeout", "answer_missing", "failed_opens", "reconnects"):
        assert rec.counts[failure] == 0
