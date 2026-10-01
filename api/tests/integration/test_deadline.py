# AI-ASSISTED: end_quiz.lua on a real Redis: the host mark, then one quiz_ended broadcast.
import json
import uuid

import pytest
from redis.asyncio import Redis

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import quiz_keys
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.ports.store import End, Publish


async def test_end_quiz_is_idempotent(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    await redis_store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=1)
    await redis_store.join(quiz_id, "a", "Ann", "c-a")
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(keys.events)
    confirm = await pubsub.get_message(timeout=5)
    assert confirm is not None
    assert confirm["type"] == "subscribe"
    assert await redis_store.end_quiz(quiz_id, "host") == End("marked")
    assert await redis_client.get(keys.dirty) is None
    assert await redis_store.end_quiz(quiz_id, "host") == End("ended", 1)
    for reason in ("host", "deadline"):
        assert await redis_store.end_quiz(quiz_id, reason) == End("ended", 1)
    assert await redis_store.publish_if_dirty(quiz_id, "n1") == Publish("ended", 1)
    messages = []
    while message := await pubsub.get_message(timeout=0.1):
        messages.append(json.loads(message["data"]))
    await pubsub.aclose()  # type: ignore[no-untyped-call]
    head = {"v": 1, "type": "quiz_ended", "seq": 1, "playerCount": 1, "you": None}
    entry = {"rank": 1, "userId": "a", "displayName": "Ann", "score": 0}
    assert messages == [{"frame": {**head, "entries": [entry]}, "ranks": []}]
    assert await redis_client.get(keys.seq) == "1"
    assert await redis_client.hget(keys.meta, "endSeq") == "1"


async def test_host_end_announces_only_after_the_mark_is_fsynced(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    await redis_store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=1)
    seen, wait = [], redis_store._fsynced  # noqa: SLF001 - the WAITAOF step under test

    async def watched(conn: Redis) -> int:
        end_seq = await redis_client.hget(keys.meta, "endSeq")
        seen.append((end_seq, await redis_client.get(keys.seq)))
        return await wait(conn)  # the real WAITAOF 1 0 2000 (the test Redis runs with AOF on)

    monkeypatch.setattr(redis_store, "_fsynced", watched)
    assert await redis_store.end_by_host(quiz_id) == 1
    assert seen == [(None, "0")]  # marked, not yet announced, while it waited
    assert await redis_store.end_by_host(quiz_id) == 1  # idempotent; no second wait
    assert len(seen) == 1


async def test_host_end_without_the_fsync_announces_nothing(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    await redis_store.create_quiz(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=1)

    async def no_fsync(_: Redis) -> int:
        return 0

    monkeypatch.setattr(redis_store, "_fsynced", no_fsync)
    with pytest.raises(DomainError) as refused:
        await redis_store.end_by_host(quiz_id)
    assert refused.value.code is ErrorCode.UNAVAILABLE
    assert await redis_client.hget(keys.meta, "endSeq") is None
    assert await redis_client.get(keys.seq) == "0"
