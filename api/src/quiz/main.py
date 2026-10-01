# AI-ASSISTED: the composition root: settings in, the store, mocks and use cases wired, app out.
"""``create_app()`` is the one place that picks adapters and hands them their dependencies.
Start hooks run in order; stop hooks run in reverse, also after a failed start, and a failing
stop hook never skips the others. ``quiz.main:app`` is built once, on first access, so importing
``create_app`` builds nothing."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import cache

from fastapi import FastAPI
from redis.asyncio import Redis

from quiz.adapters.memory import MemoryStore
from quiz.adapters.mock_auth import MemoryTicketStore, RedisTicketStore
from quiz.adapters.mock_questions import MockQuestionBank
from quiz.adapters.redis import RedisStore
from quiz.adapters.ws.endpoint import Gateway
from quiz.app.service import QuizService
from quiz.config import Settings
from quiz.ports.clock import Clock
from quiz.ports.questions import QuestionBank
from quiz.ports.store import Limits, Store
from quiz.ports.tickets import TicketStore

Hook = Callable[[], Awaitable[None]]


def wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


def monotonic_ms() -> int:
    """Paces the resync limit: a wall-clock step never refuses or allows resyncs."""
    return time.monotonic_ns() // 1_000_000


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
    limits = Limits(settings.tick_ms, settings.top_n, settings.full_list_max)
    if settings.store == "memory":
        quiz_clock = clock or wall_clock_ms  # quiz time; ticket and session expiry stay real
        memory = MemoryStore(quiz_clock, limits)
        service = QuizService(memory, bank, clock or monotonic_ms)
        return Services(
            settings, quiz_clock, memory, MemoryTicketStore(wall_clock_ms), bank, service
        )
    # Redis reads its own TIME for quiz time; the monotonic clock only paces the resync limit.
    client = Redis.from_url(settings.redis_url, decode_responses=True)  # connects on first use
    redis, tickets = RedisStore(client, limits=limits), RedisTicketStore(client)
    service = QuizService(redis, bank, monotonic_ms)
    stop: list[Hook] = [client.aclose]
    return Services(settings, wall_clock_ms, redis, tickets, bank, service, [redis.start], stop)


async def _stop_all(hooks: Sequence[Hook], pending: BaseException | None) -> None:
    """Run every stop hook in reverse; a failure joins ``pending`` as a note, else is raised."""
    errors: list[Exception] = []
    for stop in reversed(hooks):
        try:
            await stop()
        except Exception as error:  # noqa: BLE001 - the remaining hooks must still run
            errors.append(error)
    if not errors:
        return
    if pending is None:
        msg = "stop hooks failed"
        raise ExceptionGroup(msg, errors)
    for error in errors:
        pending.add_note(f"stop hook failed: {error!r}")


def create_app(settings: Settings | None = None, *, clock: Clock | None = None) -> FastAPI:
    """Build the app; ``clock`` (integer ms) replaces the wall clock for the memory store."""
    services = _wire(settings or Settings(), clock)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            for start in services.startup:
                await start()
            yield
        except BaseException as error:
            await _stop_all(services.shutdown, error)
            raise
        await _stop_all(services.shutdown, None)

    app = FastAPI(title="Real-time vocabulary quiz", lifespan=lifespan)
    app.state.services = services
    app.state.gateway = gateway = Gateway(services.settings, services.tickets, services.service)
    app.add_api_websocket_route("/ws", gateway.endpoint)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness: the process answers HTTP."""
        return {"status": "ok"}

    return app


@cache
def module_app() -> FastAPI:
    """The one app of ``uvicorn quiz.main:app``, with one store and one Redis pool."""
    return create_app()


def __getattr__(name: str) -> FastAPI:
    if name == "app":
        return module_app()
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
