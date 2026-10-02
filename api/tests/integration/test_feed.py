# AI-ASSISTED: both stores deliver each published broadcast to their subscribers, encoded once.
import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from quiz.adapters.memory import MemoryStore
from quiz.adapters.redis import RedisStore
from quiz.domain.session import Question
from quiz.ports.store import FeedStore, Limits

READ_TIMEOUT_S = 2
TICK_MS = 10


@pytest.fixture(params=["memory", "redis"])
def store(request: pytest.FixtureRequest) -> FeedStore:
    limits = Limits(tick_ms=TICK_MS, top_n=1, full_list_max=2)
    if request.param == "memory":
        return MemoryStore(lambda: time.time_ns() // 1_000_000, limits)
    redis_store: RedisStore = request.getfixturevalue("redis_store")
    redis_store.limits = limits
    return redis_store


@pytest.fixture
def quiz_id() -> str:
    return f"T-{uuid.uuid4().hex[:12].upper()}"


async def create(store: FeedStore, quiz_id: str) -> None:
    await store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)


async def publish(store: FeedStore, quiz_id: str) -> int | None:
    return (await store.publish_if_dirty(quiz_id, "n1")).seq


async def read(messages: AsyncIterator[str]) -> Any:  # noqa: ANN401 - a decoded events message
    return json.loads(await asyncio.wait_for(anext(messages), READ_TIMEOUT_S))


async def test_subscribers_get_each_broadcast_with_the_scorers_ranks(
    store: FeedStore, quiz_id: str
) -> None:
    await create(store, quiz_id)
    for user in ("a", "b", "c"):  # three players: above full_list_max, a frame holds the top 1
        await store.join(quiz_id, user, user.upper(), f"c-{user}")
    async with store.subscribe(quiz_id) as messages:
        totals: dict[str, int] = {}
        for user in ("b", "c"):  # two scorers: the second one is outside the frame's top 1
            await store.serve_next(quiz_id, user, 0, f"c-{user}")
            answer = await store.apply_answer(quiz_id, user, 0, 1, str(uuid.uuid4()), f"c-{user}")
            totals[user] = answer.result.total
        assert await publish(store, quiz_id) == 1
        first = await read(messages)
        await store.join(quiz_id, "d", "D", "c-d")  # dirty again, with no new scorer
        await asyncio.sleep(2 * TICK_MS / 1000)  # past the first frame's tick token
        assert await publish(store, quiz_id) == 2
        second = await read(messages)
        await store.end_quiz(quiz_id, "host")
        assert (await store.end_quiz(quiz_id, "host")).seq == 3
        ended = await read(messages)
    assert (first["frame"]["type"], first["frame"]["seq"]) == ("leaderboard", 1)
    (top,) = [e["userId"] for e in first["frame"]["entries"]]
    (other,) = set(totals) - {top}  # a scorer, ranked 2: its rank rides with the frame
    assert first["ranks"] == [[other, 2, totals[other]]]
    assert (second["frame"]["seq"], second["ranks"]) == (2, [])  # no scorer repeats
    assert (ended["frame"]["type"], ended["frame"]["seq"], ended["ranks"]) == ("quiz_ended", 3, [])


async def test_a_subscription_before_the_quiz_exists_gets_its_broadcasts(
    store: FeedStore, quiz_id: str
) -> None:
    async with store.subscribe(quiz_id) as messages:
        await create(store, quiz_id)
        await store.join(quiz_id, "a", "A", "c-a")
        assert await publish(store, quiz_id) == 1
        assert (await read(messages))["frame"]["seq"] == 1


async def test_a_read_after_leaving_ends_the_feed(store: FeedStore, quiz_id: str) -> None:
    async with store.subscribe(quiz_id) as messages:
        pass
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(messages), READ_TIMEOUT_S)


async def test_the_redis_feed_also_carries_session_replaced(
    redis_store: RedisStore, quiz_id: str
) -> None:
    await create(redis_store, quiz_id)
    async with redis_store.subscribe(quiz_id) as messages:
        await redis_store.join(quiz_id, "a", "A", "c-1")
        await redis_store.join(quiz_id, "a", "A", "c-2")  # replaces c-1, on any node
        assert await read(messages) == {"type": "session_replaced", "uid": "a", "connId": "c-1"}
