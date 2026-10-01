# AI-ASSISTED: both stores deliver each published broadcast to their subscribers, encoded once.
import json
import time
import uuid

import pytest

from quiz.adapters.memory import MemoryStore
from quiz.adapters.redis import RedisStore
from quiz.domain.session import Question
from quiz.ports.store import FeedStore, Limits


@pytest.fixture(params=["memory", "redis"])
def store(request: pytest.FixtureRequest, redis_store: RedisStore) -> FeedStore:
    limits = Limits(top_n=1, full_list_max=2)
    if request.param == "memory":
        return MemoryStore(lambda: time.time_ns() // 1_000_000, limits)
    redis_store.limits = limits
    return redis_store


async def test_subscribers_get_each_broadcast_with_the_scorers_ranks(store: FeedStore) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    await store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
    for user in ("a", "b", "c"):  # three players: above full_list_max, a frame holds the top 1
        await store.join(quiz_id, user, user.upper(), f"c-{user}")
    async with store.subscribe(quiz_id) as messages:
        totals: dict[str, int] = {}
        for user in ("b", "c"):  # two scorers: the second one is outside the frame's top 1
            await store.serve_next(quiz_id, user, 0, f"c-{user}")
            answer = await store.apply_answer(quiz_id, user, 0, 1, str(uuid.uuid4()), f"c-{user}")
            totals[user] = answer.result.total
        assert (await store.publish_if_dirty(quiz_id, "n1")).seq == 1
        first = json.loads(await anext(messages))
        await store.end_quiz(quiz_id, "host")
        assert (await store.end_quiz(quiz_id, "host")).seq == 2
        ended = json.loads(await anext(messages))
    assert (first["frame"]["type"], first["frame"]["seq"]) == ("leaderboard", 1)
    (top,) = [e["userId"] for e in first["frame"]["entries"]]
    (other,) = set(totals) - {top}  # a scorer, ranked 2: its rank rides with the frame
    assert first["ranks"] == [[other, 2, totals[other]]]
    assert (ended["frame"]["type"], ended["frame"]["seq"], ended["ranks"]) == ("quiz_ended", 2, [])
