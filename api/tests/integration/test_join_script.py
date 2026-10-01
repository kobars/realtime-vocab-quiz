# AI-ASSISTED: join.lua on a real Redis: first-join state, dirty without seq, session replacement.
import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import QUIZ_TTL_MS, QuizKeys, quiz_keys
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.domain.standings import decode_sort_score

QUESTIONS = (Question("q0", 1), Question("q1", 3))


@pytest.fixture
def quiz_id() -> str:
    return f"T-{uuid.uuid4().hex[:12].upper()}"


@pytest.fixture
async def keys(redis_store: RedisStore, redis_prefix: str, quiz_id: str) -> QuizKeys:
    await redis_store.create_quiz(quiz_id, QUESTIONS, window_ms=60_000, time_limit_ms=20_000)
    return quiz_keys(quiz_id, redis_prefix)


@pytest.fixture
async def channels(redis_client: Redis, keys: QuizKeys) -> AsyncIterator[PubSub]:
    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(keys.events, keys.control)
    yield pubsub
    await pubsub.aclose()  # type: ignore[no-untyped-call]


async def messages(pubsub: PubSub) -> list[tuple[str, str]]:
    """Everything published in the next 300 ms (a subscribe confirmation reads as None)."""
    out, loop = [], asyncio.get_running_loop()
    deadline = loop.time() + 0.3
    while (left := deadline - loop.time()) > 0:
        if message := await pubsub.get_message(timeout=left):
            out.append((message["channel"], message["data"]))
    return out


async def test_first_join_board_score_round_trips(
    redis_store: RedisStore, redis_client: Redis, keys: QuizKeys, quiz_id: str
) -> None:
    joined = await redis_store.join(quiz_id, "a", "Ann", "c1")
    assert (joined.cursor, joined.cursor_open, joined.finished, joined.total) == (
        -1,
        False,
        False,
        0,
    )
    assert (joined.question_count, joined.time_limit_ms, joined.replaced_conn_id) == (
        2,
        20_000,
        None,
    )
    assert 0 < joined.quiz_remaining_ms <= 60_000
    score = await redis_client.zscore(keys.board, "a")
    assert score is not None
    total, reached = decode_sort_score(int(score))
    assert total == 0
    assert 0 <= reached < 60_000
    assert await redis_client.hget(keys.names, "a") == "Ann"
    assert await redis_client.hget(keys.totals, "a") == "0"
    assert await redis_client.hget(keys.serve, "a") == "[-1,0,0]"
    for key in (keys.names, keys.totals, keys.board, keys.serve, keys.present, keys.dirty):
        assert QUIZ_TTL_MS - 5_000 < await redis_client.pttl(key) <= QUIZ_TTL_MS


async def test_join_sets_dirty_without_seq_or_events(
    redis_store: RedisStore, redis_client: Redis, keys: QuizKeys, channels: PubSub, quiz_id: str
) -> None:
    await redis_store.join(quiz_id, "a", "Ann", "c1")
    await redis_store.join(quiz_id, "b", "Bo", "c2")
    assert await redis_client.get(keys.dirty) == "1"
    assert await redis_client.get(keys.seq) == "0"
    assert await messages(channels) == []


async def test_reconnect_keeps_player_state_and_replaces_old_connection(
    redis_store: RedisStore, redis_client: Redis, keys: QuizKeys, channels: PubSub, quiz_id: str
) -> None:
    await redis_store.join(quiz_id, "a", "Ann", "c1")
    score = await redis_client.zscore(keys.board, "a")
    await asyncio.sleep(0.01)
    joined = await redis_store.join(quiz_id, "a", "Other name", "c2")
    assert joined.replaced_conn_id == "c1"
    assert await redis_client.hget(keys.names, "a") == "Ann"
    assert await redis_client.zscore(keys.board, "a") == score
    assert json.loads(str(await redis_client.hget(keys.present, "a")))[0] == "c2"
    [(channel, data)] = await messages(channels)
    assert channel == keys.control
    assert json.loads(data) == {"type": "session_replaced", "uid": "a", "connId": "c1"}


@pytest.mark.usefixtures("keys")
async def test_repeat_join_on_same_connection_replaces_nothing(
    redis_store: RedisStore, channels: PubSub, quiz_id: str
) -> None:
    await redis_store.join(quiz_id, "a", "Ann", "c1")
    assert (await redis_store.join(quiz_id, "a", "Ann", "c1")).replaced_conn_id is None
    assert await messages(channels) == []


async def test_join_after_deadline_is_quiz_ended(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, quiz_id: str
) -> None:
    await redis_store.create_quiz(quiz_id, QUESTIONS, window_ms=1, time_limit_ms=20_000)
    await asyncio.sleep(0.01)
    with pytest.raises(DomainError) as info:
        await redis_store.join(quiz_id, "a", "Ann", "c1")
    assert (info.value.code, info.value.end_seq) == (ErrorCode.QUIZ_ENDED, None)
    assert not await redis_client.exists(quiz_keys(quiz_id, redis_prefix).serve)


async def test_join_after_announced_end_carries_end_seq(
    redis_store: RedisStore, redis_client: Redis, keys: QuizKeys, quiz_id: str
) -> None:
    await redis_client.hset(keys.meta, mapping={"endedMs": 1, "endSeq": 7})
    with pytest.raises(DomainError) as info:
        await redis_store.join(quiz_id, "a", "Ann", "c1")
    assert (info.value.code, info.value.end_seq) == (ErrorCode.QUIZ_ENDED, 7)
    assert not await redis_client.exists(keys.serve, keys.present, keys.dirty)
