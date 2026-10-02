# AI-ASSISTED: the bots' frame shortcut, CLI, reconnect rules and swarm runs against the app.
import asyncio
import contextlib
import itertools
import json
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from pydantic import SecretStr

import bots
from bots import BOARD_HEAD, converse, create_quizzes, main, parse, play, swarm
from latency import summary
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
    token = SecretStr("load-token")
    app = create_app(Settings(admin_mock=True, admin_token=token, allowed_origins=(OPTS.origin,)))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run)
    thread.start()
    while not server.started:
        assert thread.is_alive()
        time.sleep(0.01)
    yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    server.should_exit = True
    thread.join()


@pytest.fixture
def exported_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shell that exports the stack's port must not change the origins the app accepts."""
    monkeypatch.setenv("QUIZ_PORT", "18080")


def bot(deadline_s: float = 5) -> Player:
    rec = Recorder()
    return Player("VOCAB-42", "bot", rec, BoardWait(rec, 1), {}, time.monotonic() + deadline_s)


def waiting(p: Player, *, sent: bool = True) -> None:
    """An open timed answer (sent, or still in its think time) and an open board wait."""
    now = time.monotonic()
    p.answer, p.timed, p.sent = (9, "sub", 0), True, sent
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
    for bad in ("--quizzes 4", "--bots 0", "--procs 11", "--accuracy 1.5", "--duration -1",
                "--duration 0", "--ramp nan", "--duration inf", "--think-ms -3", "--timeout-ms 0",
                "--label baseline/2proc"):  # fmt: skip
        with pytest.raises(SystemExit):
            parse(bad.split())


@pytest.mark.parametrize("sent", [True, False])
async def test_a_reconnect_resends_a_sent_answer_and_drops_an_unsent_one(
    monkeypatch: pytest.MonkeyPatch,
    sent: bool,  # noqa: FBT001
) -> None:
    def lost(p: Player) -> int:
        waiting(p, sent=sent)
        return DEAD_LINK

    def rejoined(p: Player) -> int:
        kept = (9, "sub", 0) if sent else None
        assert (p.answer, p.answer_due, p.timed, p.board.pending) == (kept, None, False, [])
        joined = {"type": "joined", "userId": "u", "finished": True,
                  "cursor": 9, "cursorOpen": False}  # fmt: skip
        p.handle(joined, now := time.monotonic(), Backoff(), 0)
        p.due(now)
        resent = [m["submissionId"] for m in p.outbox if m["type"] == "answer"]
        assert (resent, p.settled(now)) == ((["sub"], False) if sent else ([], True))
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
    """Takes what the bot sends; answers with ``frames``, then nothing."""

    def __init__(self, *frames: str) -> None:
        self.sent: list[str] = []
        self.receives = 0
        self.frames = list(frames)

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw)["type"])

    async def recv(self) -> str:
        self.receives += 1
        if self.frames:
            return self.frames.pop(0)
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


async def test_converse_reads_frames_in_full_while_an_answer_is_out() -> None:
    entry = Entry(rank=1, userId="u1", displayName="Ann", score=150)
    raw = encode_broadcast(
        Leaderboard(seq=3, rebase=False, playerCount=1, onlineCount=1, entries=[entry])
    ).decode()
    p, ws = bot(), Socket(raw)
    p.user_id, p.answer, p.sent_at = "u1", (0, "sub", 0), time.monotonic()
    await asyncio.wait_for(converse(ws, p, Backoff(), OPTS, time.monotonic() + 0.1), 2)  # type: ignore[arg-type]
    assert p.board.best == 150  # the total before its reply: the reply will not wait for it


async def test_converse_sends_nothing_once_the_quiz_ended() -> None:
    p, ws = bot(), Socket()
    p.ended = True
    assert await converse(ws, p, Backoff(), OPTS, time.monotonic() + 1) == NORMAL  # type: ignore[arg-type]
    assert ws.sent == []


@pytest.mark.parametrize("timer", ["answer", "retry"])
async def test_a_timer_at_the_stop_counts_no_missing_answer(timer: str) -> None:
    p, ws = bot(0.05), Socket()
    stop = p.deadline + OPTS.timeout_ms / 1000  # as play() sets it
    p.answer, p.timed = (9, "sub", 0), True
    if timer == "answer":  # its think time ends at the stop: never sent
        p.answer_due = stop
    else:  # sent, and its retry timer runs out at the stop: timed out
        p.sent, p.sent_at = True, stop - p.board.timeout_s
    assert await converse(ws, p, Backoff(), OPTS, stop) == NORMAL  # type: ignore[arg-type]
    p.disconnected()  # as play() does after the socket
    counts = p.rec.counts
    assert (ws.sent, counts["answer_missing"], counts["answer_timeout"]) == (
        ["join"],
        0,
        timer == "retry",
    )


@pytest.mark.usefixtures("exported_port")
async def test_a_swarm_plays_whole_quizzes_against_the_app(app_url: str) -> None:
    flags = "--quizzes 2 --bots 3 --think-ms 0 --duration 1 --ramp 0 --timeout-ms 300"
    opts = parse([*flags.split(), "--url", app_url])
    async with httpx.AsyncClient(base_url=app_url, headers={"X-Admin-Token": "load-token"}) as http:
        for quiz_id in opts.quiz_ids:
            (await http.post("/admin/quizzes", json={"quizId": quiz_id})).raise_for_status()
    rec, _ = await swarm(opts)
    assert rec.counts["cohorts"] > 3  # a slot starts a new cohort after its player finishes
    assert rec.counts["answers"] >= 30  # the first cohort of each slot answers all ten
    assert len(rec.answer_ms) == rec.counts["answers"]
    for failure in ("answer_timeout", "answer_missing", "failed_opens", "reconnects"):
        assert rec.counts[failure] == 0


async def test_a_quiz_end_before_the_deadline_ends_the_cpu_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, process_time, busy_s = list[str](), time.process_time, 0.1

    def cpu_sample() -> float:
        events.append("cpu sample")
        return process_time()

    async def busy_until_the_quiz_ends(p: Player, *_: object) -> None:
        events.append("play")
        until = process_time() + busy_s  # CPU time: a busy machine stretches only its wall time
        while process_time() < until:
            pass
        p.ended = True

    monkeypatch.setattr(time, "process_time", cpu_sample)
    monkeypatch.setattr(bots, "play", busy_until_the_quiz_ends)
    t0 = time.monotonic()
    rec, proc = await swarm(parse(["--bots", "1", "--duration", "3", "--ramp", "0"]))
    elapsed = time.monotonic() - t0
    assert elapsed < 2  # no idle wait for the deadline
    assert events[:2] == ["cpu sample", "play"]  # with no ramp, the window opens before play
    assert proc["cpu_pct"] >= round(100 * busy_s / elapsed, 1)  # it holds the whole busy run
    assert rec.counts["slots_ended_early"] == 1


def test_the_report_is_printed_before_the_result_is_saved(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def full_disk(*_: object) -> Path:
        raise OSError

    monkeypatch.setattr(bots, "run", lambda _: summary(Recorder(), [], 1))
    monkeypatch.setattr(bots, "save", full_disk)
    with pytest.raises(OSError):  # noqa: PT011 - any write error
        main([])
    assert "INVALID: no answer samples" in capsys.readouterr().out


async def test_quizzes_are_created_or_found_open(app_url: str) -> None:
    opts = parse(["--quizzes", "2", "--admin-token", "load-token", "--url", app_url])
    await create_quizzes(opts)
    await create_quizzes(opts)  # running: 409, then still open
    async with httpx.AsyncClient(base_url=app_url) as http:
        headers = {"X-Admin-Token": "load-token"}
        (await http.post("/admin/quizzes/BIZ-20/end", headers=headers)).raise_for_status()
    with pytest.raises(RuntimeError, match="BIZ-20 has ended"):
        await create_quizzes(opts)
    hour = parse(
        f"--quiz-ids ACAD-10 --duration 3600 --admin-token load-token --url {app_url}".split()
    )
    with pytest.raises(RuntimeError, match="HTTP 422"):
        await create_quizzes(hour)


def test_a_swarm_over_two_processes_writes_its_result(
    app_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bots, "RESULTS", tmp_path)
    flags = "--quizzes 2 --bots 3 --procs 2 --think-ms 20 --duration 1 --ramp 0 --timeout-ms 500"
    assert main([*flags.split(), "--admin-token", "load-token", "--url", app_url]) == 0
    [path] = tmp_path.iterdir()
    result = json.loads(path.read_text())
    counts = result["counts"]
    assert counts["cohorts"] >= 3
    assert counts["answers"] >= 30  # the first cohort of each slot answers all ten
    assert result["answer"]["samples"] == counts["answers"]
    for failure in ("answer_timeout", "answer_missing", "failed_opens", "reconnects"):
        assert counts.get(failure, 0) == 0
    assert len(result["swarm"]["procs"]) == 2
    assert result["valid"]
    assert bots.save(result, "run") != bots.save(result, "run")
