# AI-ASSISTED: the bot swarm: cohorts of bots join quizzes, answer, and time answer -> leaderboard.
"""Fill quizzes with bots and measure what a player sees.

Each ``--bots`` slot plays one player at a time, then the next cohort's player, until the run
ends. ``player.py`` holds the protocol rules.
"""

import argparse
import asyncio
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.typing import Origin, Subprotocol

from player import DEAD_LINK, NORMAL, Backoff, BoardWait, Player, Recorder

SUBPROTOCOL = Subprotocol("quiz.v1")
OPEN_TIMEOUT_S, PING_EVERY_S, LIVENESS_S, WAKE_S = 5.0, 25.0, 50.0, 1.0
# Most frames need only their seq: read it without parsing up to 200 entries.
BOARD_HEAD = re.compile(r'^\{"v":1,"type":"leaderboard","seq":(\d+),"rebase":(true|false)')
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
    timeout_ms: int

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


async def swarm(opts: Options) -> Recorder:
    """Run every bot slot until the deadline; the samples and counts of all of them."""
    rec, key = Recorder(), dict[str, int]()
    start = time.monotonic()
    deadline = start + opts.ramp + opts.duration

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
                return

    limits = httpx.Limits(max_connections=100)
    async with httpx.AsyncClient(base_url=opts.url, timeout=10, limits=limits) as http:
        await asyncio.gather(*(slot(i, http) for i in range(opts.bots)))
    return rec


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
    add("--timeout-ms", type=int, default=5000, help="a sample slower than this times out")
    a = cli.parse_args(argv)
    ids = tuple(q.strip() for q in a.quiz_ids.split(",") if q.strip())
    if not 1 <= a.quizzes <= len(ids):
        cli.error(f"--quizzes must be 1..{len(ids)} (the number of --quiz-ids)")
    if a.bots < 1 or not 0 <= a.accuracy <= 1:
        cli.error("need --bots >= 1 and 0 <= --accuracy <= 1")
    finite = math.isfinite(a.ramp + a.duration)  # also an overflowing sum
    if not finite or a.duration <= 0 or a.ramp < 0 or a.think_ms < 0 or a.timeout_ms <= 0:
        cli.error("need finite --duration > 0 and --ramp >= 0, --think-ms >= 0, --timeout-ms > 0")
    rest = {k: v for k, v in vars(a).items() if k not in {"url", "quiz_ids", "quizzes"}}
    return Options(url=a.url.rstrip("/"), quiz_ids=ids[: a.quizzes], **rest)
