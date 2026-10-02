# AI-ASSISTED: the composition root on Redis: the start hook loads every Lua script; a join burst
# above the connection pool's size waits for a connection instead of failing; readiness needs a
# write that Redis accepts.
import asyncio
import hashlib
import uuid

import httpx
from redis.asyncio import Redis

from quiz.adapters.redis.scripts import SCRIPTS, source
from quiz.app.service import Connection
from quiz.config import Settings
from quiz.contracts import messages as m
from quiz.domain.session import Question
from quiz.main import create_app, services_of


async def test_start_hook_loads_every_script(redis_url: str) -> None:
    shas = [hashlib.sha1(source(name).encode()).hexdigest() for name in SCRIPTS]  # noqa: S324
    async with Redis.from_url(redis_url) as probe:
        await probe.script_flush()
        app = create_app(Settings(store="redis", redis_url=redis_url))
        async with app.router.lifespan_context(app):
            assert await probe.script_exists(*shas) == [True] * len(shas)


async def test_a_join_burst_above_the_pool_size_waits_for_a_connection(redis_url: str) -> None:
    settings = Settings(store="redis", redis_url=redis_url, redis_max_connections=10)
    app = create_app(settings)
    services, quiz_id = services_of(app), f"B-{uuid.uuid4().hex[:8].upper()}"
    async with app.router.lifespan_context(app):
        create = services.store.create_quiz
        await create(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
        joins = (
            services.service.handle(
                Connection(f"c{i}", f"u{i}"), m.Join(quizId=quiz_id, displayName=f"P{i}")
            )
            for i in range(5 * settings.redis_max_connections)
        )
        outcomes = await asyncio.gather(*joins)
    assert {type(outcome.replies[0]) for outcome in outcomes} == {m.Joined}


async def test_readyz_answers_503_while_redis_refuses_writes(redis_url: str) -> None:
    app = create_app(Settings(store="redis", redis_url=redis_url))
    transport = httpx.ASGITransport(app=app)
    async with (
        Redis.from_url(redis_url) as admin,
        httpx.AsyncClient(transport=transport, base_url="http://node") as client,
    ):
        assert (await client.get("/readyz")).status_code == 200
        await admin.config_set("min-replicas-to-write", 1)  # every write now fails: NOREPLICAS
        try:
            down = await client.get("/readyz")
        finally:
            await admin.config_set("min-replicas-to-write", 0)
        assert (down.status_code, down.json()) == (503, {"status": "unavailable"})
        assert (await client.get("/readyz")).status_code == 200
