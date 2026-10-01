# AI-ASSISTED: publish_leaderboard.lua on a real Redis: the dirty gate, the tick token and ranks.
import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import QuizKeys, quiz_keys
from quiz.domain.session import Question
from quiz.ports.store import Publish

QUESTIONS = (Question("q0", 1), Question("q1", 3))


@pytest.fixture
def quiz_id() -> str:
    return f"T-{uuid.uuid4().hex[:12].upper()}"


@pytest.fixture
def keys(redis_prefix: str, quiz_id: str) -> QuizKeys:
    return quiz_keys(quiz_id, redis_prefix)


@pytest.fixture
async def events(redis_client: Redis, keys: QuizKeys) -> AsyncIterator[PubSub]:
    """The events channel, subscribed: wait for Redis to confirm before anything publishes."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(keys.events)
    confirm = await pubsub.get_message(timeout=5)
    assert confirm is not None
    assert confirm["type"] == "subscribe"
    pubsub.ignore_subscribe_messages = True
    yield pubsub
    await pubsub.aclose()  # type: ignore[no-untyped-call]


async def received(pubsub: PubSub) -> list[dict[str, Any]]:
    """Every message on the channel until it stays quiet for 100 ms."""
    out = []
    while message := await pubsub.get_message(timeout=0.1):
        out.append(json.loads(message["data"]))
    return out


async def created(store: RedisStore, quiz_id: str, *users: str) -> None:
    await store.create_quiz(quiz_id, QUESTIONS, window_ms=60_000, time_limit_ms=20_000)
    for user in users:
        await store.join(quiz_id, user, user.upper(), f"c-{user}")


async def test_two_nodes_publish_one_frame_per_tick(
    redis_store: RedisStore, redis_client: Redis, events: PubSub, keys: QuizKeys, quiz_id: str
) -> None:
    await created(redis_store, quiz_id, "a", "b")
    replies = await asyncio.gather(
        *(redis_store.publish_if_dirty(quiz_id, f"n{n}") for n in range(8))
    )
    assert sorted(r.status for r in replies) == ["busy"] * 7 + ["published"]
    assert await redis_client.get(keys.seq) == "1"
    (message,) = await received(events)
    head = {"v": 1, "type": "leaderboard", "seq": 1, "rebase": False, "playerCount": 2}
    row = {"rank": 1, "userId": "a", "displayName": "A", "score": 0}
    rows = [row, {**row, "rank": 2, "userId": "b", "displayName": "B"}]
    assert message == {"frame": {**head, "onlineCount": 2, "entries": rows}, "ranks": []}
    await asyncio.sleep(0.25)
    assert (await redis_store.publish_if_dirty(quiz_id, "n1")).status == "clean"
    assert await received(events) == []


async def test_publishing_continues_after_1000_writes(
    redis_store: RedisStore, redis_client: Redis, keys: QuizKeys, quiz_id: str
) -> None:
    await created(redis_store, quiz_id, "a")
    assert (await redis_store.publish_if_dirty(quiz_id, "n1")).status == "published"
    for n in range(1000):  # each write script refreshes the data TTL
        await redis_store.join(quiz_id, "a", "A", f"c{n}")
    pttl = await redis_client.pttl(keys.tick)
    # -2: expired; 0: its last millisecond, still there; -1 (no expiry) or > 200: stretched.
    assert pttl == -2 or 0 <= pttl <= 200
    await asyncio.sleep(0.25)
    assert await redis_store.publish_if_dirty(quiz_id, "n1") == Publish("published", 2)


async def test_scorer_outside_top_50_gets_rank_in_same_frame(
    redis_store: RedisStore, redis_client: Redis, events: PubSub, keys: QuizKeys, quiz_id: str
) -> None:
    await created(redis_store, quiz_id, *(f"u{n:03}" for n in range(201)))  # join order = rank
    await redis_client.sadd(keys.scored, "u000", "u120")  # as score_answer leaves them
    assert (await redis_store.publish_if_dirty(quiz_id, "n1")).status == "published"
    (message,) = await received(events)
    assert (message["frame"]["playerCount"], len(message["frame"]["entries"])) == (201, 50)
    assert message["ranks"] == [["u120", 121, 0]]  # u000 is in the top 50: no rank of its own
    assert not await redis_client.exists(keys.scored)


async def test_tick_token_stretched_by_a_clock_step_back_is_cut_to_one_tick(
    redis_store: RedisStore, redis_client: Redis, keys: QuizKeys, quiz_id: str
) -> None:
    await created(redis_store, quiz_id, "a")
    assert (await redis_store.publish_if_dirty(quiz_id, "n1")).status == "published"
    now_s, now_us = await redis_client.time()
    # Expiry is wall-clock time: after a 10 s step back the token reads 10.2 s ahead.
    await redis_client.pexpireat(keys.tick, now_s * 1000 + now_us // 1000 + 10_200)
    await redis_store.join(quiz_id, "b", "B", "c-b")  # dirty again
    busy = await redis_store.publish_if_dirty(quiz_id, "n2")
    assert busy.status == "busy"
    assert 0 < busy.retry_ms <= 200
    assert 0 < await redis_client.pttl(keys.tick) <= 200
    await asyncio.sleep(0.25)
    assert await redis_store.publish_if_dirty(quiz_id, "n2") == Publish("published", 2)
