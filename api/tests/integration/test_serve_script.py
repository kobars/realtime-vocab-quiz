# AI-ASSISTED: serve_question.lua on a real Redis: TIME serve time, retries, skips and finishing.
import asyncio
import json
import uuid

import pytest
from redis.asyncio import Redis

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import QuizKeys, quiz_keys
from quiz.adapters.redis.scripts import Scripts
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.ports.store import Finished

QUESTIONS = (Question("q0", 1), Question("q1", 3), Question("q2", 2))
LIMIT_MS = 20_000


@pytest.fixture
def quiz_id() -> str:
    return f"T-{uuid.uuid4().hex[:12].upper()}"


@pytest.fixture
async def keys(redis_store: RedisStore, redis_prefix: str, quiz_id: str) -> QuizKeys:
    await redis_store.create_quiz(quiz_id, QUESTIONS, window_ms=60_000, time_limit_ms=LIMIT_MS)
    await redis_store.join(quiz_id, "a", "Ann", "c1")
    return quiz_keys(quiz_id, redis_prefix)


async def test_serve_stores_redis_time_and_a_retry_returns_it(
    redis_client: Redis, keys: QuizKeys
) -> None:
    scripts = Scripts(redis_client)
    await scripts.load()
    sec, usec = await redis_client.time()
    reply = await scripts.call("serve_question", keys, "a", 0, "c1")
    assert reply == ["ok", "question", 0, "q0", LIMIT_MS, 0]  # no correct choice in the reply
    stored = await redis_client.hget(keys.serve, "a")
    cursor, serve_ms, finished = json.loads(str(stored))
    assert (cursor, finished) == (0, 0)
    assert serve_ms >= sec * 1000 + usec // 1000
    await asyncio.sleep(0.05)
    retry = await scripts.call("serve_question", keys, "a", 0, "c1")
    assert int(retry[4] or 0) <= LIMIT_MS - 50  # counted from the stored serve time
    assert await redis_client.hget(keys.serve, "a") == stored


async def test_skip_closes_the_open_question_but_never_an_answered_one(
    redis_store: RedisStore, redis_client: Redis, keys: QuizKeys, quiz_id: str
) -> None:
    await redis_store.serve_next(quiz_id, "a", 0, "c1")
    await redis_store.serve_next(quiz_id, "a", 1, "c1")  # skips question 0
    assert json.loads(str(await redis_client.hget(keys.answered, "a|0")))[:2] == [-1, 0]
    with pytest.raises(DomainError) as info:
        await redis_store.apply_answer(quiz_id, "a", 0, 1, "s1", "c1")
    assert info.value.code is ErrorCode.ALREADY_ANSWERED
    await redis_store.apply_answer(quiz_id, "a", 1, 3, "s2", "c1")
    await redis_store.serve_next(quiz_id, "a", 2, "c1")  # question 1 is answered: no skip row
    assert json.loads(str(await redis_client.hget(keys.answered, "a|1")))[0] == 3
    assert await redis_client.get(keys.seq) == "0"


async def test_finished_player_cannot_be_served_again(
    redis_store: RedisStore, redis_client: Redis, keys: QuizKeys, quiz_id: str
) -> None:
    await redis_store.serve_next(quiz_id, "a", 0, "c1")
    finished = await redis_store.serve_next(quiz_id, "a", len(QUESTIONS), "c1")
    assert finished == Finished(0, total=0, rank=1, player_count=1)
    state = await redis_client.hgetall(keys.serve), await redis_client.hgetall(keys.answered)
    with pytest.raises(DomainError) as info:
        await redis_store.serve_next(quiz_id, "a", 1, "c1")
    assert info.value.code is ErrorCode.INVALID_STATE
    assert await redis_store.serve_next(quiz_id, "a", len(QUESTIONS), "c1") == finished
    after = await redis_client.hgetall(keys.serve), await redis_client.hgetall(keys.answered)
    assert after == state
