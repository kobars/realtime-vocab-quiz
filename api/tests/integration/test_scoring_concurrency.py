# AI-ASSISTED: score_answer.lua under 50 concurrent copies of one answer: it scores exactly once.
import asyncio
import uuid

import pytest
from redis.asyncio import Redis

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import quiz_keys
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.ports.store import Answered

TASKS = 50
ONE = (Question("q0", 2),)


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
