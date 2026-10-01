# AI-ASSISTED: create_quiz.lua on a real Redis: shape checks, the written keys and their TTL.
import json
import uuid
from collections.abc import Sequence

import pytest
from redis.asyncio import Redis

from quiz.adapters.redis.keys import QUIZ_TTL_MS, QuizKeys, quiz_keys
from quiz.adapters.redis.scripts import Reply, Scripts

IDS, ANSWERS = ["q0", "q1"], [2, 0]


@pytest.fixture
async def scripts(redis_client: Redis) -> Scripts:
    scripts = Scripts(redis_client)
    await scripts.load()
    return scripts


@pytest.fixture
def keys(redis_prefix: str) -> QuizKeys:
    return quiz_keys(f"T-{uuid.uuid4().hex[:12].upper()}", redis_prefix)


async def create(
    scripts: Scripts, keys: QuizKeys, shape: tuple[list[str], Sequence[object], int], window_ms: int
) -> Reply:
    """Call with the four ARGV of docs/spec/redis.md §3; the TTL is the script's own constant."""
    ids, answers, limit_ms = shape
    return await scripts.call(
        "create_quiz", keys, json.dumps(ids), json.dumps(answers), limit_ms, window_ms
    )


GOOD = (IDS, ANSWERS, 20_000)


async def test_window_above_60_min_is_rejected(scripts: Scripts, keys: QuizKeys) -> None:
    assert await create(scripts, keys, GOOD, 3_600_001) == ["INVALID_MESSAGE"]
    assert (await create(scripts, keys, GOOD, 3_600_000))[0] == "ok"


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param(([], [], 20_000), id="no-questions"),
        pytest.param((["q0", "q0"], [0, 1], 20_000), id="duplicate-ids"),
        pytest.param((IDS, ANSWERS, 0), id="zero-limit"),
        pytest.param((IDS, [0, 4], 20_000), id="choice-4"),
        pytest.param((IDS, [-1, 0], 20_000), id="choice-minus-1"),
        pytest.param((IDS, [0], 20_000), id="short-key"),
        pytest.param(([f"q{i}" for i in range(101)], [0] * 101, 20_000), id="101-questions"),
        pytest.param((["q0", "q1", "q2"], ["0x2", " 1", "2.0"], 20_000), id="numeric-strings"),
        pytest.param((IDS, ["2", "0"], 20_000), id="digit-strings"),
        pytest.param((IDS, [1.5, 0], 20_000), id="fraction"),
    ],
)
async def test_invalid_quiz_shape_is_rejected(
    scripts: Scripts,
    redis_client: Redis,
    keys: QuizKeys,
    shape: tuple[list[str], Sequence[object], int],
) -> None:
    assert await create(scripts, keys, shape, 60_000) == ["INVALID_MESSAGE"]
    assert not await redis_client.exists(keys.meta, keys.key, keys.seq)


async def test_create_twice_is_invalid_state(scripts: Scripts, keys: QuizKeys) -> None:
    await create(scripts, keys, GOOD, 60_000)
    assert await create(scripts, keys, GOOD, 60_000) == ["INVALID_STATE"]


async def test_create_writes_meta_key_and_seq_with_ttl(
    scripts: Scripts, redis_client: Redis, keys: QuizKeys
) -> None:
    status, start_ms, deadline_ms = await create(scripts, keys, GOOD, 60_000)
    assert (status, deadline_ms) == ("ok", int(start_ms or 0) + 60_000)
    fields = ("questionCount", "timeLimitMs", "windowMs", "startMs", "deadlineMs", "questionIds")
    meta = ["2", "20000", "60000", str(start_ms), str(deadline_ms), '["q0", "q1"]']
    assert await redis_client.hmget(keys.meta, fields) == meta
    assert await redis_client.hgetall(keys.key) == {"0": "2", "1": "0"}
    assert await redis_client.get(keys.seq) == "0"
    for key in (keys.meta, keys.key, keys.seq):
        assert QUIZ_TTL_MS - 5_000 < await redis_client.pttl(key) <= QUIZ_TTL_MS


async def test_whole_float_answer_is_stored_as_an_integer(
    scripts: Scripts, redis_client: Redis, keys: QuizKeys
) -> None:
    assert (await create(scripts, keys, (IDS, [2.0, 0], 20_000), 60_000))[0] == "ok"
    assert await redis_client.hgetall(keys.key) == {"0": "2", "1": "0"}
