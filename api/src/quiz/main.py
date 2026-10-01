# AI-ASSISTED: the composition root: settings in, adapters, use cases and HTTP wired, app out.
"""``create_app()`` is the one place that picks adapters and hands them their dependencies.
Start hooks run in order; stop hooks run in reverse, also after a failed start. ``quiz.main:app``
is built on first access, so importing ``create_app`` builds nothing."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI
from redis import exceptions as redis_errors
from redis.asyncio import Redis

from quiz.adapters.http import HttpDeps, install
from quiz.adapters.memory import MemoryStore
from quiz.adapters.mock_auth import MemoryTicketStore, RedisTicketStore
from quiz.adapters.mock_auth.tokens import TICKET_TTL_S
from quiz.adapters.mock_questions import MockQuestionBank
from quiz.adapters.redis import RedisStore
from quiz.app.service import QuizService
from quiz.config import Settings
from quiz.obs.logs import configure_logging
from quiz.ports.clock import Clock
from quiz.ports.questions import QuestionBank
from quiz.ports.store import Store
from quiz.ports.tickets import TicketStore

Hook = Callable[[], Awaitable[None]]
Probe = Callable[[], Awaitable[bool]]
READY_TIMEOUT_S = 1.0


def wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


async def always_ready() -> bool:
    return True


def redis_probe(client: Redis) -> Probe:
    async def ping() -> bool:
        try:
            return bool(await asyncio.wait_for(client.ping(), READY_TIMEOUT_S))
        except redis_errors.RedisError, OSError, TimeoutError:
            return False

    return ping


@dataclass(slots=True)
class Services:
    settings: Settings
    clock: Clock
    store: Store
    tickets: TicketStore
    bank: QuestionBank
    service: QuizService
    startup: list[Hook] = field(default_factory=list)
    shutdown: list[Hook] = field(default_factory=list)
    ready: Probe = always_ready


def services_of(app: FastAPI) -> Services:
    services: Services = app.state.services
    return services


def _wire(settings: Settings, clock: Clock | None) -> Services:
    bank = MockQuestionBank.load()
    if settings.store == "memory":
        quiz_clock = clock or wall_clock_ms  # quiz time; ticket and session expiry stay real
        memory = MemoryStore(quiz_clock)
        service = QuizService(memory, bank, quiz_clock)
        return Services(
            settings, quiz_clock, memory, MemoryTicketStore(wall_clock_ms), bank, service
        )
    # Redis reads its own TIME for quiz time; the wall clock only paces the resync limit.
    client = Redis.from_url(settings.redis_url, decode_responses=True)  # connects on first use
    redis, tickets = RedisStore(client), RedisTicketStore(client)
    service = QuizService(redis, bank, wall_clock_ms)
    stop: list[Hook] = [client.aclose]
    probe = redis_probe(client)
    return Services(
        settings, wall_clock_ms, redis, tickets, bank, service, [redis.start], stop, probe
    )


def create_app(settings: Settings | None = None, *, clock: Clock | None = None) -> FastAPI:
    """Build the app; ``clock`` (integer ms) replaces the wall clock for the memory store."""
    services = _wire(settings or Settings(), clock)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            for start in services.startup:
                await start()
            yield
        finally:
            for stop in reversed(services.shutdown):
                await stop()

    configure_logging()
    app = FastAPI(title="Real-time vocabulary quiz", lifespan=lifespan)
    app.state.services = services
    s = services.settings
    install(
        app,
        HttpDeps(
            services.store,
            services.tickets,
            services.bank,
            services.ready,
            TICKET_TTL_S * 1000,
            s.admin_token.get_secret_value() if s.admin_mock and s.admin_token else None,
            (
                ConnectionError,
                TimeoutError,
                redis_errors.ConnectionError,
                redis_errors.TimeoutError,
            ),
        ),
    )
    return app


def __getattr__(name: str) -> FastAPI:
    if name == "app":  # ``uvicorn quiz.main:app``
        return create_app()
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
