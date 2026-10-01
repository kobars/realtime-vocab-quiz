# AI-ASSISTED: the composition root: settings in, the store, mocks and use cases wired, app out.
"""``create_app()`` is the one place that picks adapters. Later parts of the service (the
gateway, the HTTP endpoints, the fan-out tasks) read ``services_of(app)`` and add their own
start and stop hooks; stop hooks run in reverse order, also after a failed start.

``uvicorn quiz.main:app`` builds the app from the environment on first access, so importing this
module for ``create_app`` builds nothing."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI
from redis.asyncio import Redis

from quiz.adapters.memory import MemoryStore
from quiz.adapters.mock_auth import MemoryTicketStore, RedisTicketStore
from quiz.adapters.mock_questions import MockQuestionBank
from quiz.adapters.redis import RedisStore
from quiz.app.service import QuizService
from quiz.config import Settings
from quiz.ports.clock import Clock
from quiz.ports.questions import QuestionBank
from quiz.ports.store import Store
from quiz.ports.tickets import TicketStore

Hook = Callable[[], Awaitable[None]]


def wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


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


def services_of(app: FastAPI) -> Services:
    services: Services = app.state.services
    return services


def _wire(settings: Settings, clock: Clock | None) -> Services:
    bank = MockQuestionBank.load()
    if settings.store == "memory":
        quiz_clock = clock or wall_clock_ms  # quiz time; ticket and session expiry stay real
        store, tickets = MemoryStore(quiz_clock), MemoryTicketStore(wall_clock_ms)
        return Services(
            settings, quiz_clock, store, tickets, bank, QuizService(store, bank, quiz_clock)
        )
    # Redis reads its own TIME for quiz time; the wall clock only paces the resync limit.
    client = Redis.from_url(settings.redis_url, decode_responses=True)  # connects on first use
    redis_store = RedisStore(client)
    services = Services(
        settings,
        wall_clock_ms,
        redis_store,
        RedisTicketStore(client),
        bank,
        QuizService(redis_store, bank, wall_clock_ms),
    )
    services.startup.append(redis_store.start)
    services.shutdown.append(client.aclose)
    return services


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

    app = FastAPI(title="Real-time vocabulary quiz", lifespan=lifespan)
    app.state.services = services

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness: the process answers HTTP."""
        return {"status": "ok"}

    return app


def __getattr__(name: str) -> FastAPI:
    if name == "app":  # ``uvicorn quiz.main:app``
        return create_app()
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
