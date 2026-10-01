# AI-ASSISTED: the Redis scripts follow the configured standings limits, not the defaults.
import asyncio
import json
import uuid

from redis.asyncio import Redis

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import quiz_keys
from quiz.domain.session import Question
from quiz.ports.store import Limits


async def test_frames_snapshot_and_final_standings_use_the_configured_limits(
    redis_client: Redis, redis_prefix: str
) -> None:
    store = RedisStore(redis_client, prefix=redis_prefix, limits=Limits(50, 1, 2))
    await store.start()
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(keys.events)
    assert (await pubsub.get_message(timeout=5) or {}).get("type") == "subscribe"
    await store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
    for user in ("a", "b", "c"):  # three players: above full_list_max=2, so frames show top_n=1
        await store.join(quiz_id, user, user.upper(), f"c-{user}")
    await redis_client.sadd(keys.scored, "c")

    assert (await store.publish_if_dirty(quiz_id, "n1")).status == "published"
    assert 0 < await redis_client.pttl(keys.tick) <= 50  # the configured tick_ms
    frame = json.loads((await pubsub.get_message(timeout=5) or {})["data"])
    assert [e["userId"] for e in frame["frame"]["entries"]] == ["a"]
    assert frame["ranks"] == [["c", 3, 0]]
    assert [row.user_id for row in (await store.snapshot(quiz_id, None)).rows] == ["a"]

    await asyncio.sleep(0.06)  # the 50 ms token is gone: the next dirty tick publishes again
    await store.join(quiz_id, "a", "A", "c-a2")
    assert (await store.publish_if_dirty(quiz_id, "n1")).status == "published"
    await pubsub.get_message(timeout=5)

    await store.end_quiz(quiz_id, "host")
    assert (await store.end_quiz(quiz_id, "host")).status == "ended"
    ended = json.loads((await pubsub.get_message(timeout=5) or {})["data"])
    assert ended["frame"]["type"] == "quiz_ended"
    assert [e["userId"] for e in ended["frame"]["entries"]] == ["a"]
    await pubsub.aclose()  # type: ignore[no-untyped-call]
