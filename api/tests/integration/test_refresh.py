# AI-ASSISTED: the quiz TTL on a real Redis: scripts re-expire the data keys only once the meta TTL
# has dropped by the margin, and a key a script creates gets the meta's TTL at once.
import uuid

from redis.asyncio import Redis

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import NO_QUIZ_TTL, QuizKeys, quiz_keys
from quiz.adapters.redis.scripts import REFRESH_MARGIN_MS
from quiz.domain.session import Question
from quiz.ports.store import QUIZ_TTL_MS

QUESTIONS = tuple(Question(f"q{i}", 1) for i in range(3))


async def pexpires(redis_client: Redis) -> int:
    """How often Redis ran PEXPIRE since its start, from scripts too."""
    stats = await redis_client.info("commandstats")
    return int(stats.get("cmdstat_pexpire", {}).get("calls", 0))


async def data_ttls(redis_client: Redis, keys: QuizKeys) -> dict[str, int]:
    """The PTTL of every data key that exists."""
    ttls = {name: await redis_client.pttl(getattr(keys, name)) for name in QuizKeys._fields}
    return {name: ttl for name, ttl in ttls.items() if name not in NO_QUIZ_TTL and ttl != -2}


async def played(store: RedisStore, quiz_id: str, prefix: str) -> QuizKeys:
    """A quiz whose two players took over, served, answered and left, which creates every
    data key after ``create_quiz``."""
    await store.create_quiz(quiz_id, QUESTIONS, window_ms=60_000, time_limit_ms=20_000)
    await store.join(quiz_id, "a", "Ann", "c-a")
    await store.join(quiz_id, "a", "Ann", "c-a2")  # replaced: creates the replaced set
    await store.join(quiz_id, "b", "Bob", "c-b")
    await store.serve_next(quiz_id, "a", 0, "c-a2")
    await store.apply_answer(quiz_id, "a", 0, 1, str(uuid.uuid4()), "c-a2")
    await store.leave(quiz_id, "b", "c-b")
    return quiz_keys(quiz_id, prefix)


async def test_an_answer_and_a_next_re_expire_no_key_while_the_meta_ttl_is_fresh(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    await played(redis_store, quiz_id, redis_prefix)
    before = await pexpires(redis_client)
    await redis_store.serve_next(quiz_id, "a", 1, "c-a2")
    await redis_store.apply_answer(quiz_id, "a", 1, 1, str(uuid.uuid4()), "c-a2")
    # 13 per script before; now none, as every key they write has its TTL already
    assert await pexpires(redis_client) == before


async def test_a_created_key_gets_the_meta_ttl_and_none_outlives_the_quiz(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = await played(redis_store, quiz_id, redis_prefix)
    ttls = await data_ttls(redis_client, keys)
    assert set(ttls) == set(QuizKeys._fields) - NO_QUIZ_TTL  # every data key was created
    assert all(0 < ttl <= ttls["meta"] for ttl in ttls.values()), ttls


async def test_the_next_write_re_expires_every_key_once_the_meta_ttl_dropped_by_the_margin(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = await played(redis_store, quiz_id, redis_prefix)
    low = QUIZ_TTL_MS - REFRESH_MARGIN_MS - 1_000
    for key in await data_ttls(redis_client, keys):
        await redis_client.pexpire(getattr(keys, key), low)
    await redis_store.serve_next(quiz_id, "a", 1, "c-a2")
    ttls = await data_ttls(redis_client, keys)
    assert all(QUIZ_TTL_MS - 5_000 < ttl <= QUIZ_TTL_MS for ttl in ttls.values()), ttls
