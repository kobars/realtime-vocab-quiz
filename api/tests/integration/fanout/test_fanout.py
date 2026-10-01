# AI-ASSISTED: the coalescing tick and the relay on one node, on the memory and the Redis store.
import asyncio
import json
import time
import uuid
from collections import defaultdict
from itertools import pairwise
from typing import Any, cast

import pytest

from quiz.adapters.memory import MemoryStore
from quiz.adapters.redis import RedisStore
from quiz.adapters.ws.registry import Registry
from quiz.adapters.ws.sender import Sender
from quiz.app.service import Connection
from quiz.domain.session import Question
from quiz.fanout.tick import Ticker
from quiz.ports.store import FeedStore

QUESTIONS = (Question("q0", 1), Question("q1", 3))


class Sink:
    """This node's sockets: a set of local players; it records what each one gets."""

    def __init__(self, *players: str) -> None:
        self.local = set(players)
        self.frames: list[dict[str, Any]] = []
        self.updates: defaultdict[str, list[tuple[float, dict[str, Any]]]] = defaultdict(list)

    def broadcast(self, _quiz_id: str, data: bytes, *, leaderboard: bool) -> None:
        assert leaderboard
        self.frames.append(json.loads(data))

    def players(self, _quiz_id: str) -> set[str]:
        return self.local

    def send_to(self, _quiz_id: str, user_id: str, data: bytes) -> None:
        self.updates[user_id].append((time.monotonic(), json.loads(data)))


@pytest.fixture(params=["memory", "redis"])
def store(request: pytest.FixtureRequest, redis_store: RedisStore) -> FeedStore:
    if request.param == "memory":
        return MemoryStore(lambda: time.time_ns() // 1_000_000)
    return redis_store


async def quiz_with(store: FeedStore, *users: str) -> str:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    await store.create_quiz(quiz_id, QUESTIONS, window_ms=60_000, time_limit_ms=20_000)
    for user in users:
        await store.join(quiz_id, user, user.upper(), f"c-{user}")
    return quiz_id


async def score(store: FeedStore, quiz_id: str, user: str, *questions: int) -> None:
    for i in questions:
        await store.serve_next(quiz_id, user, i, f"c-{user}")
        choice = QUESTIONS[i].correct_choice
        await store.apply_answer(quiz_id, user, i, choice, str(uuid.uuid4()), f"c-{user}")


async def test_100_answers_in_1_s_make_at_most_6_frames_ending_on_the_standings(
    store: FeedStore,
) -> None:
    users = [f"p{n:02}" for n in range(100)]
    quiz_id = await quiz_with(store, *users)
    for user in users:
        await store.serve_next(quiz_id, user, 0, f"c-{user}")
    sink = Sink()
    (ticker := Ticker(store, sink, "n1")).open(quiz_id)
    await asyncio.sleep(0.4)  # the joins' frame
    sink.frames.clear()
    start = time.monotonic()
    for n, user in enumerate(users):
        await asyncio.sleep(max(0.0, start + n * 0.0098 - time.monotonic()))
        await store.apply_answer(quiz_id, user, 0, n % 4, str(uuid.uuid4()), f"c-{user}")
    assert time.monotonic() - start < 1.0
    await asyncio.sleep(0.5)
    await ticker.stop()
    assert 1 <= len(sink.frames) <= 6
    final = await store.snapshot(quiz_id, None)
    rows = [[r.rank, r.user_id, r.display_name, r.score] for r in final.rows]
    last = sink.frames[-1]
    assert (last["seq"], last["playerCount"], len(last["entries"])) == (final.at_seq, 100, 100)
    assert [[e["rank"], e["userId"], e["displayName"], e["score"]] for e in last["entries"]] == rows


async def test_the_tick_runs_only_while_the_quiz_has_local_sockets(store: FeedStore) -> None:
    quiz_id = await quiz_with(store, "a")
    sink, registry = Sink(), Registry(store, 0)  # no grace: a dropped player leaves at once
    registry.watcher = Ticker(store, sink, "n1")
    sender = cast("Sender", object())  # the registry only stores it here
    first, second = Connection("c1", "a", quiz_id), Connection("c2", "b", quiz_id)
    await asyncio.sleep(0.3)
    assert sink.frames == []  # no local socket: no tick
    for conn in (first, second):
        registry.bind(conn, sender)
    await asyncio.sleep(0.3)
    assert [f["playerCount"] for f in sink.frames] == [1]
    registry.drop(first)
    await store.join(quiz_id, "b", "B", "c-b")
    await asyncio.sleep(0.3)
    assert [f["playerCount"] for f in sink.frames] == [1, 2]  # one socket left: still ticking
    registry.drop(second)
    await asyncio.sleep(0.05)
    await store.join(quiz_id, "c", "C", "c-c")
    await asyncio.sleep(0.3)
    assert len(sink.frames) == 2  # the last socket left: no tick, nothing relayed
    assert (await store.publish_if_dirty(quiz_id, "n2")).status == "published"


async def test_players_outside_the_top_50_get_rank_updates(
    store: FeedStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    users = [f"u{n:03}" for n in range(201)]  # the join order is the rank
    quiz_id = await quiz_with(store, *users)
    for user in users[:60]:
        await score(store, quiz_id, user, 0, 1)  # two answers: ahead of any single scorer
    reads: list[int] = []
    ranks_of = store.ranks_of

    async def counted(quiz_id: str, user_ids: list[str]) -> object:
        reads.append(len(user_ids))
        return await ranks_of(quiz_id, user_ids)

    monkeypatch.setattr(store, "ranks_of", counted)
    sink = Sink("u000", "u120", "u150")
    (ticker := Ticker(store, sink, "n1")).open(quiz_id)
    await asyncio.sleep(0.3)
    started = time.monotonic()
    for user in ("u150", "u160", "u170"):  # each shifts u120 down by one, a tick apart
        await score(store, quiz_id, user, 0)
        await asyncio.sleep(0.25)
    await asyncio.sleep(1.2)
    await ticker.stop()
    elapsed = time.monotonic() - started
    (scored,) = [update for _, update in sink.updates["u150"] if update["rank"] == 61]
    frame = next(f for f in sink.frames if f["seq"] == scored["atSeq"])
    assert (len(frame["entries"]), frame["playerCount"], scored["playerCount"]) == (50, 201, 201)
    shifted = sink.updates["u120"]
    assert (shifted[-1][1]["rank"], shifted[-1][1]["score"]) == (124, 0)  # the newest value
    assert all(b[0] - a[0] >= 0.9 for a, b in pairwise(shifted))
    assert "u000" not in sink.updates  # in the top 50: the frame shows it
    assert reads == [3] * len(reads)
    assert len(reads) <= elapsed + 1.5  # one read per second for all local players
