# AI-ASSISTED: score_answer.lua on a real Redis: parity with the domain rule, step back, deadline.
import asyncio
import json
import uuid
from collections.abc import Awaitable

import pytest
from redis.asyncio import Redis

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import QuizKeys, quiz_keys
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.scoring import score_answer
from quiz.domain.session import Question
from quiz.domain.standings import decode_sort_score

LIMIT_MS = 20_000
# Elapsed times around every float trap of the textbook formula, the limit and lateness.
ELAPSED = (0, 1, 6_800, 11_200, 13_600, 15_600, 16_000, 18_000, 18_400, 19_999, 20_000, 30_000)
QUESTIONS = tuple(Question(f"q{i}", i % 4) for i in range(2 * len(ELAPSED)))


@pytest.fixture
def quiz_id() -> str:
    return f"T-{uuid.uuid4().hex[:12].upper()}"


async def start(store: RedisStore, quiz_id: str, prefix: str, window_ms: int = 60_000) -> QuizKeys:
    await store.create_quiz(quiz_id, QUESTIONS, window_ms=window_ms, time_limit_ms=LIMIT_MS)
    await store.join(quiz_id, "a", "Ann", "c1")
    return quiz_keys(quiz_id, prefix)


async def serve_at(client: Redis, keys: QuizKeys, i: int, ago_ms: int) -> None:
    """Move the stored serve time of question ``i`` to ``ago_ms`` before Redis TIME."""
    sec, usec = await client.time()
    await client.hset(keys.serve, "a", json.dumps([i, sec * 1000 + usec // 1000 - ago_ms, 0]))


async def refused(call: Awaitable[object]) -> DomainError:
    with pytest.raises(DomainError) as info:
        await call
    return info.value


async def test_script_points_match_python_and_land_in_the_standings(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, quiz_id: str
) -> None:
    keys, total = await start(redis_store, quiz_id, redis_prefix), 0
    for i, question in enumerate(QUESTIONS):
        await redis_store.serve_next(quiz_id, "a", i, "c1")
        await serve_at(redis_client, keys, i, ELAPSED[i % len(ELAPSED)])
        choice = question.correct_choice if i < len(ELAPSED) else 3 - question.correct_choice
        r = (await redis_store.apply_answer(quiz_id, "a", i, choice, f"s{i}", "c1")).result
        _, points, elapsed = json.loads(str(await redis_client.hget(keys.answered, f"a|{i}")))
        correct = choice == question.correct_choice
        expected = score_answer(correct=correct, elapsed_ms=elapsed, time_limit_ms=LIMIT_MS)
        total += expected
        assert (r.points, points, r.total, r.correct) == (expected, expected, total, correct)
        assert r.late == (elapsed > LIMIT_MS)
    assert await redis_client.hget(keys.totals, "a") == str(total)
    assert decode_sort_score(int(await redis_client.zscore(keys.board, "a") or 0))[0] == total
    assert await redis_client.smembers(keys.scored) == {"a"}
    assert (await redis_client.get(keys.dirty), await redis_client.get(keys.seq)) == ("1", "0")
    assert json.loads(str(await redis_client.hget(keys.serve, "a")))[2] == 1  # the last finishes


async def test_clock_step_back_clamps_elapsed_and_flags_outside_the_stored_reply(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, quiz_id: str
) -> None:
    keys = await start(redis_store, quiz_id, redis_prefix)
    await redis_store.serve_next(quiz_id, "a", 0, "c1")
    await serve_at(redis_client, keys, 0, -5_000)  # TIME is now 5 s before the serve time
    first = await redis_store.apply_answer(quiz_id, "a", 0, 0, "s1", "c1")
    assert (first.step_back, first.result.points, first.result.late) == (True, 150, False)
    assert json.loads(str(await redis_client.hget(keys.answered, "a|0")))[2] == 0
    replay = await redis_store.apply_answer(quiz_id, "a", 0, 0, "s1", "c1")
    assert (replay.step_back, replay.result) == (False, first.result)


async def test_writes_after_the_deadline_write_nothing_and_a_replay_still_answers(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, quiz_id: str
) -> None:
    keys = await start(redis_store, quiz_id, redis_prefix, window_ms=300)
    await redis_store.serve_next(quiz_id, "a", 0, "c1")
    first = await redis_store.apply_answer(quiz_id, "a", 0, 0, "s1", "c1")
    await asyncio.sleep(0.35)
    state = await redis_client.hgetall(keys.serve), await redis_client.hgetall(keys.subs)
    for user in ("a", "nobody"):  # the deadline check comes before the player check
        serve = redis_store.serve_next(quiz_id, user, 1, "c1")
        for call in (serve, redis_store.apply_answer(quiz_id, user, 0, 1, "s2", "c1")):
            error = await refused(call)
            assert (error.code, error.end_seq) == (ErrorCode.QUIZ_ENDED, None)
    again = await redis_store.apply_answer(quiz_id, "a", 0, 0, "s1", "c1")
    assert (again.result, again.step_back) == (first.result, False)
    assert (await redis_client.hgetall(keys.serve), await redis_client.hgetall(keys.subs)) == state


async def test_unserved_index_and_stranger_are_refused_and_write_nothing(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str, quiz_id: str
) -> None:
    keys = await start(redis_store, quiz_id, redis_prefix)
    await redis_store.serve_next(quiz_id, "a", 0, "c1")
    for user, i, code in (("a", -1, ErrorCode.QUESTION_NOT_OPEN), ("b", 0, ErrorCode.NOT_JOINED)):
        assert (
            await refused(redis_store.apply_answer(quiz_id, user, i, 0, "s", "c1"))
        ).code is code
    assert not await redis_client.exists(keys.subs, keys.answered)
