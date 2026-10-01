# AI-ASSISTED: the script loader (EVALSHA, one reload on NOSCRIPT) and the key schema.
import pytest
from redis.asyncio import Redis
from redis.exceptions import NoScriptError

from quiz.adapters.redis.keys import QUIZ_TTL_MS, quiz_keys
from quiz.adapters.redis.scripts import Scripts

ARGS = ('["q0"]', "[0]", 20_000, 60_000, QUIZ_TTL_MS)


def test_every_key_shares_the_quiz_hash_tag() -> None:
    keys = quiz_keys("VOCAB-42", "p:")
    assert keys.meta == "p:quiz:{VOCAB-42}:meta"
    assert all(key == f"p:quiz:{{VOCAB-42}}:{name}" for name, key in keys._asdict().items())


async def test_noscript_after_flush_reloads_and_retries(
    redis_client: Redis, redis_prefix: str
) -> None:
    scripts = Scripts(redis_client)
    await scripts.load()
    await redis_client.script_flush()  # what a Redis restart does to the script cache
    reply = await scripts.call("create_quiz", quiz_keys("T-A", redis_prefix), *ARGS)
    assert reply[0] == "ok"


async def test_noscript_twice_is_raised(
    redis_client: Redis, redis_prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripts = Scripts(redis_client)
    await scripts.load()
    loads = 0

    async def flush_after_load() -> None:
        nonlocal loads
        loads += 1
        await redis_client.script_flush()  # the reload does not stick

    monkeypatch.setattr(scripts, "load", flush_after_load)
    await redis_client.script_flush()
    with pytest.raises(NoScriptError):
        await scripts.call("create_quiz", quiz_keys("T-B", redis_prefix), *ARGS)
    assert loads == 1
