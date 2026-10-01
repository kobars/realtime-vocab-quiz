# AI-ASSISTED: the bot swarm: cohorts of bots join quizzes, answer, and time answer -> leaderboard.
"""Fill quizzes with bots and measure what a player sees (load/README.md).

Each ``--bots`` slot plays one player at a time, then the next cohort's player, until the run
ends; ``--procs`` splits the slots over processes. ``player.py`` holds the protocol rules.
"""

import argparse
import asyncio
import json
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


async def converse(ws: ClientConnection, p: Player, backoff: Backoff, opts: Options) -> int:
    """Play on one socket; return its close code."""
    p.send("join", quizId=p.quiz_id, displayName=p.name)
    last_in = last_ping = time.monotonic()
    think_s, timeout_s = opts.think_ms / 1000, opts.timeout_ms / 1000
    while True:
        for message in p.outbox:
            await ws.send(json.dumps(message, separators=(",", ":")))
        p.rec.counts["msgs_out"] += len(p.outbox)
        p.outbox.clear()
        now = time.monotonic()
        if p.settled(now):
            await ws.close(NORMAL)
            return NORMAL
        timers = [t - now for t in (p.answer_due, p.resync_at) if t is not None]
        wait = max(0.0, min([WAKE_S, *timers]))
        try:
            raw = await asyncio.wait_for(ws.recv(), wait)
        except TimeoutError:
            raw = None
        now = time.monotonic()
        if raw is not None:
            last_in = now
            p.rec.counts["msgs_in"] += 1
            head = BOARD_HEAD.match(raw) if isinstance(raw, str) and not p.board.pending else None
            if head:
                p.on_seq(int(head[1]), head[2] == "true", now)
            else:
                p.handle(json.loads(raw), now, backoff, think_s)
        elif now - last_in > LIVENESS_S:
            return DEAD_LINK
        if now - last_ping >= PING_EVERY_S:
            p.send("ping")
            last_ping = now
        p.due(now, timeout_s)


async def play(p: Player, http: httpx.AsyncClient, opts: Options) -> None:
    """One cohort's player: a mock session, then connects until it finishes or must stop."""
    session = (await http.post("/sessions", json={"displayName": p.name})).raise_for_status()
    auth = {"Authorization": f"Bearer {session.json()['sessionToken']}"}
    backoff = Backoff()
    while True:
        try:
            ticket = (await http.post("/tickets", headers=auth)).raise_for_status().json()["ticket"]
            async with connect(
                f"{opts.ws_url}?ticket={ticket}",
                origin=Origin(opts.origin),
                subprotocols=[SUBPROTOCOL],
                open_timeout=OPEN_TIMEOUT_S,
                ping_interval=None,
                compression=None,
                max_size=2**20,
            ) as ws:
                code = await converse(ws, p, backoff, opts)
        except ConnectionClosed as closed:
            code = closed.rcvd.code if closed.rcvd else DEAD_LINK
        except OSError, TimeoutError, InvalidHandshake, httpx.HTTPError:
            code = DEAD_LINK  # a failed open, like a refused upgrade in the browser
            p.rec.counts["failed_opens"] += 1
        if code == NORMAL or p.ended:
            break
        p.board.abandon()  # a wait across a reconnect would time the reconnect
        p.rec.counts["answer_missing"] += p.timed and p.sent_at is not None
        p.timed, p.sent_at = False, None  # joined re-drives next; the re-served answer goes again
        p.outbox.clear()
        p.rec.counts["reconnects"] += 1
        wait = backoff.closed(code, time.monotonic(), random.random())  # noqa: S311
        if wait is None:
            p.rec.counts[f"final_close_{code}"] += 1
            break
        await asyncio.sleep(wait)
    p.board.abandon()


def _rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (2**20 if sys.platform == "darwin" else 2**10), 1)  # bytes vs KiB


async def _worker(opts: Options, proc: int) -> tuple[Recorder, dict[str, float]]:
    rec, key = Recorder(), dict[str, int]()
    cpu0, start = time.process_time(), time.monotonic()
    deadline = start + opts.ramp + opts.duration

    async def slot(index: int, http: httpx.AsyncClient) -> None:
        """One bot slot: cohort after cohort until the deadline or the quiz's end."""
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
                return

    limits = httpx.Limits(max_connections=100)
    async with httpx.AsyncClient(base_url=opts.url, timeout=10, limits=limits) as http:
        await asyncio.gather(*(slot(i, http) for i in range(proc, opts.bots, opts.procs)))
    cpu = 100 * (time.process_time() - cpu0) / max(time.monotonic() - start, 1e-9)
    return rec, {"cpu_pct": round(cpu, 1), "rss_mb": _rss_mb()}


def worker(opts: Options, proc: int) -> tuple[Recorder, dict[str, float]]:
    return asyncio.run(_worker(opts, proc))


async def create_quizzes(opts: Options) -> None:
    """MOCK admin: start each quiz with a window that covers the run; 409 means it runs."""
    window_ms = min(3_600_000, int((opts.ramp + opts.duration + 120) * 1000))
    headers = {"X-Admin-Token": opts.admin_token or ""}
    async with httpx.AsyncClient(base_url=opts.url, timeout=10) as http:
        for quiz_id in opts.quiz_ids:
            body = {"quizId": quiz_id, "windowMs": window_ms}
            reply = await http.post("/admin/quizzes", json=body, headers=headers)
            if reply.status_code != httpx.codes.CONFLICT:
                reply.raise_for_status()


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
    wall = time.monotonic() - t0
    return {"run": meta | {"wall_s": round(wall, 1)}, **summary(rec, [p for _, p in parts], wall)}


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
    rest = {k: v for k, v in vars(a).items() if k not in {"url", "quiz_ids", "quizzes"}}
    return Options(url=a.url.rstrip("/"), quiz_ids=ids[: a.quizzes], **rest)


def main(argv: list[str] | None = None) -> int:
    opts = parse(argv)
    result = run(opts)
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS / f"{stamp}-{opts.label}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(report(result), f"\nwritten: {path}", sep="")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
