# AI-ASSISTED: score_answer.lua under concurrent copies of one answer or a racing skip: one closure.
import asyncio
import json
import uuid

import pytest
from redis.asyncio import Redis

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import quiz_keys
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.ports.store import Answered, Served

TASKS = 50
ONE = (Question("q0", 2),)
TWO = (*ONE, Question("q1", 0))


@pytest.mark.parametrize(
    "sids", [["s"] * TASKS, [f"s{n}" for n in range(TASKS)]], ids=["same-id", "new-ids"]
)
async def test_concurrent_copies_of_one_answer_score_once(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, sids: list[str]
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    await redis_store.create_quiz(quiz_id, ONE, window_ms=60_000, time_limit_ms=20_000)
    await redis_store.join(quiz_id, "a", "Ann", "c1")
    await redis_store.serve_next(quiz_id, "a", 0, "c1")
    calls = [redis_store.apply_answer(quiz_id, "a", 0, 2, sid, "c1") for sid in sids]
    outcomes = await asyncio.gather(*calls, return_exceptions=True)
    scored = [o.result for o in outcomes if isinstance(o, Answered)]
    refused = [o.code for o in outcomes if isinstance(o, DomainError)]
    # the same id: every copy gets the identical stored result; new ids: one scores
    assert len(scored) == (TASKS if len(set(sids)) == 1 else 1)
    assert len(set(scored)) == 1
    assert refused == [ErrorCode.ALREADY_ANSWERED] * (TASKS - len(scored))
    keys = quiz_keys(quiz_id, redis_prefix)
    assert scored[0].points > 0
    assert await redis_client.hget(keys.totals, "a") == str(scored[0].points)
    assert await redis_client.hlen(keys.answered) == 1


async def test_concurrent_answer_and_skip_close_once(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str
) -> None:
    """Each player sends an answer and a skip of question 0 at once; either may run first."""
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    await redis_store.create_quiz(quiz_id, TWO, window_ms=60_000, time_limit_ms=20_000)
    users = [f"u{n}" for n in range(TASKS)]
    for user in users:
        await redis_store.join(quiz_id, user, user, f"c-{user}")
        await redis_store.serve_next(quiz_id, user, 0, f"c-{user}")

    async def race(user: str) -> tuple[object, object]:
        answer = redis_store.apply_answer(quiz_id, user, 0, 2, f"s-{user}", f"c-{user}")
        skip = redis_store.serve_next(quiz_id, user, 1, f"c-{user}")
        return await asyncio.gather(answer, skip, return_exceptions=True)

    keys = quiz_keys(quiz_id, redis_prefix)
    races = await asyncio.gather(*(race(user) for user in users))
    for user, (answered, skipped) in zip(users, races, strict=True):
        assert isinstance(skipped, Served)  # the skip moves on whether or not the answer won
        assert skipped.question_index == 1
        row = json.loads(str(await redis_client.hget(keys.answered, f"{user}|0")))
        if isinstance(answered, Answered):  # the answer won: no skip row replaced it
            assert answered.result.points > 0
            assert row[:2] == [2, answered.result.points]
            assert await redis_client.hget(keys.totals, user) == str(answered.result.points)
        else:  # the skip won: the answer is refused and scores nothing
            assert isinstance(answered, DomainError)
            assert answered.code is ErrorCode.ALREADY_ANSWERED
            assert row[:2] == [-1, 0]
            assert int(await redis_client.hget(keys.totals, user) or 0) == 0
        assert json.loads(str(await redis_client.hget(keys.serve, user)))[0] == 1
    assert await redis_client.hlen(keys.answered) == TASKS  # one closure per player
