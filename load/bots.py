# AI-ASSISTED: the bot swarm: cohorts of bots join quizzes, answer, and time answer -> leaderboard.
"""Fill quizzes with bots and measure what a player sees.

Each ``--bots`` slot plays one player at a time, then the next cohort's player, until the run
ends; ``--procs`` splits the slots over processes. ``player.py`` holds the protocol rules.
"""

import argparse
import asyncio
import json
import math
import os
import random
import re
import resource
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from multiprocessing import get_context
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.typing import Origin, Subprotocol

from latency import report, summary
from player import DEAD_LINK, NORMAL, Backoff, BoardWait, Player, Recorder

SUBPROTOCOL = Subprotocol("quiz.v1")
OPEN_TIMEOUT_S, PING_EVERY_S, LIVENESS_S, WAKE_S = 5.0, 25.0, 50.0, 1.0
# Most frames need only their seq: read it without parsing up to 200 entries.
BOARD_HEAD = re.compile(r'^\{"v":1,"type":"leaderboard","seq":(\d+),"rebase":(true|false)')
RESULTS = Path(__file__).parent / "results"
URL = "http://localhost:8080/api"  # nginx: /api goes to the API nodes, /ws to their sockets
WINDOW_SLACK_S = 120  # a created quiz stays open this long after the run


@dataclass(frozen=True, slots=True)
class Options:
    url: str
    origin: str
    quiz_ids: tuple[str, ...]
    bots: int
    accuracy: float
    think_ms: int
    duration: float
    ramp: float
    procs: int
    timeout_ms: int
    admin_token: str | None
    label: str

    @property
    def ws_url(self) -> str:
        parts = urlsplit(self.url)
        return f"{'wss' if parts.scheme == 'https' else 'ws'}://{parts.netloc}/ws"


async def converse(
    ws: ClientConnection, p: Player, backoff: Backoff, opts: Options, stop: float
) -> int:
    """Play on one socket until the player settles or ``stop``; return its close code."""
    p.send("join", quizId=p.quiz_id, displayName=p.name)
    last_in = last_ping = time.monotonic()
    think_s = opts.think_ms / 1000
    while True:
        now = time.monotonic()
        if p.settled(now) or now >= stop:  # before the flush: nothing goes out after the end
            await ws.close(NORMAL)
            return NORMAL
        for message in p.outbox:
            await ws.send(json.dumps(message, separators=(",", ":")))
            p.rec.counts["msgs_out"] += 1
        p.outbox.clear()
        answer_due = p.answer_due if p.answer else None  # a reply can outrun a retry's timer
        retry = p.sent_at + p.board.timeout_s if p.sent_at is not None else None
        expiry = p.board.pending[0][1] + p.board.timeout_s if p.board.pending else None
        timers = [t - now for t in (answer_due, retry, expiry, p.resync_at, stop) if t is not None]
        wait = max(0.0, min([WAKE_S, *timers]))
        try:
            raw = await asyncio.wait_for(ws.recv(), wait)
        except TimeoutError:
            raw = None
        now = time.monotonic()
        if raw is not None:
            last_in = now
            p.rec.counts["msgs_in"] += 1
            # Skim only while no total can change: a frame may show it before the reply does.
            skim = not p.board.pending and p.sent_at is None
            head = BOARD_HEAD.match(raw) if isinstance(raw, str) and skim else None
            if head:
                p.on_seq(int(head[1]), head[2] == "true", now)
            else:
                p.handle(json.loads(raw), now, backoff, think_s)
        elif now - last_in > LIVENESS_S:
            return DEAD_LINK
        if now - last_ping >= PING_EVERY_S:
            p.send("ping")
            last_ping = now
        p.due(now)


async def play(p: Player, http: httpx.AsyncClient, opts: Options) -> None:
    """One cohort's player: a mock session, then connects until it finishes or must stop."""
    stop = p.deadline + opts.timeout_ms / 1000  # time for the last replies, then give up
    backoff = Backoff()
    session = (await http.post("/sessions", json={"displayName": p.name})).raise_for_status()
    auth = {"Authorization": f"Bearer {session.json()['sessionToken']}"}
    while True:
        try:
            reply = (await http.post("/tickets", headers=auth)).raise_for_status()
            async with connect(
                f"{opts.ws_url}?ticket={reply.json()['ticket']}",
                origin=Origin(opts.origin),
                subprotocols=[SUBPROTOCOL],
                open_timeout=OPEN_TIMEOUT_S,
                ping_interval=None,
                compression=None,
                max_size=2**20,
            ) as ws:
                code = await converse(ws, p, backoff, opts, stop)
        except ConnectionClosed as closed:
            code = closed.rcvd.code if closed.rcvd else DEAD_LINK
        except OSError, TimeoutError, InvalidHandshake, httpx.HTTPError:
            code = DEAD_LINK  # a failed open, like a refused upgrade in the browser
            p.rec.counts["failed_opens"] += 1
        finally:  # also when play() raises
            p.disconnected()
        if code == NORMAL or p.ended:
            return
        wait = backoff.closed(code, time.monotonic(), random.random())  # noqa: S311
        if wait is None:
            p.rec.counts[f"final_close_{code}"] += 1
            p.ended = True  # its slot stops too, as a closed browser tab would
            return
        await asyncio.sleep(min(wait, max(0.0, stop - time.monotonic())))
        if time.monotonic() >= stop:  # never cut a wait short to start the next cohort
            return
        p.rec.counts["reconnects"] += 1


def _rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (2**20 if sys.platform == "darwin" else 2**10), 1)  # bytes vs KiB


async def swarm(opts: Options, proc: int = 0) -> tuple[Recorder, dict[str, float]]:
    """Run this process's bot slots until the deadline; their samples and its CPU and memory."""
    rec, key = Recorder(), dict[str, int]()
    start = time.monotonic()
    deadline = start + opts.ramp + opts.duration

    async def steady_cpu(slots: asyncio.Future[list[None]]) -> float:
        """This process's CPU share from the end of the ramp to the deadline, or to the end of
        its slots if a quiz ends first: idle time after them would hide a busy swarm."""
        ramp_left = start + opts.ramp - time.monotonic()
        if ramp_left > 0:  # else sample now: the slots first run at this coroutine's first await
            await asyncio.wait([slots], timeout=ramp_left)
            if slots.done():  # no steady window
                return 0.0
        cpu0, t0 = time.process_time(), time.monotonic()
        await asyncio.wait([slots], timeout=max(0.0, deadline - t0))
        return 100 * (time.process_time() - cpu0) / max(time.monotonic() - t0, 1e-9)

    async def slot(index: int, http: httpx.AsyncClient) -> None:
        """One bot slot: cohort after cohort until the deadline, the quiz's end or a final close."""
        await asyncio.sleep(max(0.0, start + opts.ramp * index / opts.bots - time.monotonic()))
        cohort = 0
        while time.monotonic() < deadline:
            quiz_id = opts.quiz_ids[index % len(opts.quiz_ids)]
            board = BoardWait(rec, opts.timeout_ms / 1000)
            name = f"bot-{index}-{cohort}"
            p = Player(quiz_id, name, rec, board, key, deadline, accuracy=opts.accuracy)
            try:
                await play(p, http, opts)
            except OSError, httpx.HTTPError, ValueError, KeyError:  # ValueError: not JSON
                rec.counts["bot_errors"] += 1
                await asyncio.sleep(1)
            cohort += 1
            rec.counts["cohorts"] += 1
            if p.ended:
                rec.counts["slots_ended_early"] += time.monotonic() < deadline
                return

    limits = httpx.Limits(max_connections=100)
    async with httpx.AsyncClient(base_url=opts.url, timeout=10, limits=limits) as http:
        slots = asyncio.gather(*(slot(i, http) for i in range(proc, opts.bots, opts.procs)))
        cpu_pct = await steady_cpu(slots)
        await slots
    return rec, {"cpu_pct": round(cpu_pct, 1), "rss_mb": _rss_mb()}


def worker(opts: Options, proc: int) -> tuple[Recorder, dict[str, float]]:
    return asyncio.run(swarm(opts, proc))


async def create_quizzes(opts: Options) -> None:
    """MOCK admin: start each quiz with a window that covers the run, or check it is still open.

    The server rejects a window above its cap, so a run longer than a quiz never starts."""
    window_ms = int((opts.ramp + opts.duration + WINDOW_SLACK_S) * 1000)
    headers = {"X-Admin-Token": opts.admin_token or ""}
    async with httpx.AsyncClient(base_url=opts.url, timeout=10) as http:
        for quiz_id in opts.quiz_ids:
            body = {"quizId": quiz_id, "windowMs": window_ms}
            reply = await http.post("/admin/quizzes", json=body, headers=headers)
            if reply.status_code == httpx.codes.CONFLICT:  # it exists; its window may be over
                reply = await http.get(f"/quizzes/{quiz_id}")
                if reply.is_success and reply.json()["status"] != "open":
                    problem = f"quiz {quiz_id} has ended: pick other --quiz-ids"
                    raise RuntimeError(problem)
            if reply.is_error:
                problem = f"quiz {quiz_id}: HTTP {reply.status_code} {reply.text}"
                raise RuntimeError(problem)


def run(opts: Options) -> dict[str, Any]:
    started, t0 = datetime.now(UTC), time.monotonic()
    if opts.admin_token:
        asyncio.run(create_quizzes(opts))
    if opts.procs == 1:
        parts = [worker(opts, 0)]
    else:
        with ProcessPoolExecutor(opts.procs, mp_context=get_context("spawn")) as pool:
            parts = list(pool.map(worker, [opts] * opts.procs, range(opts.procs)))
    rec = Recorder()
    for part, _ in parts:
        rec.merge(part)
    options = {k: v for k, v in asdict(opts).items() if k != "admin_token"}
    meta = {"started_at": started.isoformat(timespec="seconds"), "options": options}
    wall, active = time.monotonic() - t0, opts.ramp + opts.duration
    return {"run": meta | {"wall_s": round(wall, 1)}, **summary(rec, [p for _, p in parts], active)}


def parse(argv: list[str] | None = None) -> Options:
    cli = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    add = cli.add_argument
    add("--url", default=os.environ.get("LOAD_URL", URL), help="HTTP base of the API")
    add("--origin", default="http://localhost:8080", help="the Origin header of every bot")
    add("--quiz-ids", default="VOCAB-42,BIZ-20,ACAD-10", help="comma-separated quiz IDs")
    add("--quizzes", type=int, default=1, help="spread the bots over the first N quiz IDs")
    add("--bots", type=int, default=10, help="bots playing at the same time")
    add("--accuracy", type=float, default=0.7, help="share of correct answers, 0..1")
    add("--think-ms", type=int, default=2000, help="mean think time before each answer")
    add("--duration", type=float, default=60, help="seconds of answering after the ramp")
    add("--ramp", type=float, default=10, help="seconds over which the bots start")
    add("--procs", type=int, default=1, help="processes to spread the bots over")
    add("--timeout-ms", type=int, default=5000, help="a sample slower than this times out")
    add("--admin-token", help="MOCK admin token: create the quizzes first")
    add("--label", default="run", help="name part of the result file")
    a = cli.parse_args(argv)
    ids = tuple(q.strip() for q in a.quiz_ids.split(",") if q.strip())
    if not 1 <= a.quizzes <= len(ids):
        cli.error(f"--quizzes must be 1..{len(ids)} (the number of --quiz-ids)")
    if a.bots < 1 or not 1 <= a.procs <= a.bots or not 0 <= a.accuracy <= 1:
        cli.error("need --bots >= 1, 1 <= --procs <= --bots and 0 <= --accuracy <= 1")
    finite = math.isfinite(a.ramp + a.duration)  # also an overflowing sum
    if not finite or a.duration <= 0 or a.ramp < 0 or a.think_ms < 0 or a.timeout_ms <= 0:
        cli.error("need finite --duration > 0 and --ramp >= 0, --think-ms >= 0, --timeout-ms > 0")
    if not re.fullmatch(r"[\w.-]+", a.label, re.ASCII):
        cli.error("--label may hold only letters, digits, '_', '.' and '-'")
    rest = {k: v for k, v in vars(a).items() if k not in {"url", "quiz_ids", "quizzes"}}
    return Options(url=a.url.rstrip("/"), quiz_ids=ids[: a.quizzes], **rest)


def save(result: dict[str, Any], label: str) -> Path:
    """Write the result to a new file in ``load/results/``; never over an earlier run."""
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{label}.json"
    with path.open("x", encoding="utf-8") as out:
        out.write(json.dumps(result, indent=2) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    opts = parse(argv)
    result = run(opts)
    print(report(result))  # before the save: a failed write keeps the report
    print(f"written: {save(result, opts.label)}")
    return 0 if result["valid"] and result["slo_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
