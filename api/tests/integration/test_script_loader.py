# AI-ASSISTED: the script loader (EVALSHA, a reload of the missing script on NOSCRIPT), the key
# schema and the prelude.
import asyncio
import json

import pytest
from redis.asyncio import Redis
from redis.exceptions import NoScriptError

from quiz.adapters.redis import scripts as scripts_module
from quiz.adapters.redis.keys import NO_QUIZ_TTL, QuizKeys, quiz_keys
from quiz.adapters.redis.scripts import Scripts, compose, source
from quiz.ports.store import QUIZ_TTL_MS

ARGS = ('["q0"]', "[0]", 20_000, 60_000)


def test_every_key_shares_the_quiz_hash_tag() -> None:
    keys = quiz_keys("VOCAB-42", "p:")
    assert keys.meta == "p:quiz:{VOCAB-42}:meta"
    assert all(key == f"p:quiz:{{VOCAB-42}}:{name}" for name, key in keys._asdict().items())


async def test_lua_key_indexes_follow_quiz_keys(redis_client: Redis) -> None:
    lua = json.loads(await redis_client.eval(compose("return cjson.encode(K)"), 0))
    assert lua == {name: i for i, name in enumerate(QuizKeys._fields, 1)}


async def test_refresh_gives_every_data_key_the_quiz_ttl(
    redis_client: Redis, redis_prefix: str
) -> None:
    keys = quiz_keys("T-TTL", redis_prefix)
    for key in keys:
        await redis_client.set(key, 1)
    await redis_client.eval(compose("refresh() return 1"), len(keys), *keys)
    for name, key in keys._asdict().items():
        ttl = await redis_client.pttl(key)
        if name in NO_QUIZ_TTL:
            assert ttl == -1, name
        else:
            assert QUIZ_TTL_MS - 5_000 < ttl <= QUIZ_TTL_MS, name
    assert set(NO_QUIZ_TTL) == {"tick", "events", "control"}


async def test_check_player_ends_the_quiz_at_the_deadline_ms_itself(
    redis_client: Redis, redis_prefix: str
) -> None:
    keys = quiz_keys("T-END", redis_prefix)
    body = """
    local meta, deadline = {'0', ARGV[1]}, tonumber(ARGV[1])
    local before = check_player(meta, deadline - 1, 'a', 'c')
    return {before[1], check_player(meta, deadline, 'a', 'c')[1]}
    """
    replies = await redis_client.eval(compose(body), len(keys), *keys, 1_000_000)
    assert replies == ["NOT_JOINED", "QUIZ_ENDED"]  # one ms before, the player check runs


async def test_test_redis_runs_with_aof_on(redis_client: Redis) -> None:
    assert await redis_client.config_get("appendonly") == {"appendonly": "yes"}


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
    loads, load = 0, redis_client.script_load

    async def flush_after_load(script: str) -> str:
        nonlocal loads
        loads += 1
        sha = await load(script)
        await redis_client.script_flush()  # the reload does not stick
        return sha

    monkeypatch.setattr(redis_client, "script_load", flush_after_load)
    await redis_client.script_flush()
    with pytest.raises(NoScriptError):
        await scripts.call("create_quiz", quiz_keys("T-B", redis_prefix), *ARGS)
    assert loads == 1


async def test_noscript_reloads_only_the_missing_script_without_reading_files(
    redis_client: Redis, redis_prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripts, keys = Scripts(redis_client), quiz_keys("T-C", redis_prefix)
    await scripts.load()
    assert (await scripts.call("create_quiz", keys, *ARGS))[0] == "ok"
    await redis_client.script_flush()
    loaded, load, expected = [], redis_client.script_load, source("read_standings")

    async def counted(script: str) -> str:
        loaded.append(script)
        return await load(script)

    def no_files(*_: object) -> str:
        pytest.fail("composed a script during the recovery")

    monkeypatch.setattr(redis_client, "script_load", counted)
    monkeypatch.setattr(scripts_module, "compose", no_files)
    read = ("read_standings", keys, 0, -1, 50, 200)
    replies = await asyncio.gather(*(scripts.call(*read) for _ in range(100)))
    assert all(reply[0] == "ok" for reply in replies)
    assert 1 <= len(loaded) <= 100
    assert set(loaded) == {expected}
