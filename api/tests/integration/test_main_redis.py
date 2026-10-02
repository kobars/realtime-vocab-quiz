# AI-ASSISTED: the composition root on Redis: the start hook loads every Lua script; a join burst
# above the connection pool's size waits for a connection instead of failing; quiz subscriptions
# never take the command pool's connections.
import asyncio
import hashlib
import uuid
from contextlib import AsyncExitStack

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


async def test_open_subscriptions_leave_the_command_pool_free(redis_url: str) -> None:
    settings = Settings(store="redis", redis_url=redis_url, redis_max_connections=3)
    app = create_app(settings)
    services, bound_s = services_of(app), settings.redis_pool_timeout_ms / 1000 / 4
    quizzes = [f"S-{uuid.uuid4().hex[:8].upper()}" for _ in range(settings.redis_max_connections)]
    async with app.router.lifespan_context(app), AsyncExitStack() as subscriptions:
        for quiz_id in quizzes:
            create = services.store.create_quiz
            await create(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
            await subscriptions.enter_async_context(services.store.subscribe(quiz_id))
        async with asyncio.timeout(bound_s):
            assert await services.store.read_seq(quizzes[0]) == 0
        async with asyncio.timeout(bound_s):
            _, token = await services.tickets.create_session("Ana")
            ticket = await services.tickets.issue_ticket(token)
            assert ticket is not None
            assert await services.tickets.redeem(ticket) is not None
        async with asyncio.timeout(bound_s):
            assert await services.ready()
