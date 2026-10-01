# AI-ASSISTED: the composition root: settings in, adapters, use cases and HTTP wired, app out.
"""``create_app()`` is the one place that picks adapters and hands them their dependencies.
Start hooks run in order; stop hooks run in reverse, also after a failed start, and a failing
stop hook never skips the others. ``quiz.main:app`` is built once, on first access, so importing
``create_app`` builds nothing."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from functools import cache

from fastapi import FastAPI
from redis import exceptions as redis_errors
from redis.asyncio import BlockingConnectionPool, Redis

from quiz.adapters.http import HttpDeps, install
from quiz.adapters.memory import MemoryStore
from quiz.adapters.mock_auth import MemoryTicketStore, RedisTicketStore
from quiz.adapters.mock_auth.tokens import TICKET_TTL_S
from quiz.adapters.mock_questions import MockQuestionBank
from quiz.adapters.redis import RedisStore
from quiz.adapters.ws.endpoint import Gateway
from quiz.adapters.ws.limits import AddressRateLimiter
from quiz.app.service import QuizService
from quiz.config import Settings
from quiz.fanout.tick import Ticker
from quiz.obs.logs import configure_logging
from quiz.ports.clock import Clock
from quiz.ports.questions import QuestionBank
from quiz.ports.store import FeedStore, Limits
from quiz.ports.tickets import TicketStore

Hook = Callable[[], Awaitable[None]]
Probe = Callable[[], Awaitable[bool]]
READY_TIMEOUT_S = 1.0
IDENTITY_REFILL_S = 60  # the per-address bucket of POST /sessions and POST /tickets refills in it
# The errors that mean the store is unreachable: HTTP 503.
OUTAGES = (ConnectionError, TimeoutError, redis_errors.ConnectionError, redis_errors.TimeoutError)


def wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


def monotonic_ms() -> int:
    """Paces the resync limit: a wall-clock step never refuses or allows resyncs."""
    return time.monotonic_ns() // 1_000_000


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
    store: FeedStore
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
    limits = Limits(settings.tick_ms, settings.top_n, settings.full_list_max)
    if settings.store == "memory":
        quiz_clock = clock or wall_clock_ms  # quiz time; ticket and session expiry stay real
        memory = MemoryStore(quiz_clock, limits)
        service = QuizService(memory, bank, clock or monotonic_ms)
        return Services(
            settings, quiz_clock, memory, MemoryTicketStore(wall_clock_ms), bank, service
        )
    # Redis reads its own TIME for quiz time; the monotonic clock only paces the resync limit.
    pool = BlockingConnectionPool.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        timeout=settings.redis_pool_timeout_ms / 1000,
    )
    client = Redis.from_pool(pool)  # connects on first use; aclose() closes the pool too
    redis, tickets = RedisStore(client, limits=limits), RedisTicketStore(client)
    service = QuizService(redis, bank, monotonic_ms)
    start: list[Hook] = [redis.start]
    stop: list[Hook] = [client.aclose]
    probe = redis_probe(client)
    return Services(settings, wall_clock_ms, redis, tickets, bank, service, start, stop, probe)


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
    for failure in errors:
        pending.add_note(f"stop hook failed: {failure!r}")


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

    configure_logging()
    app = FastAPI(title="Real-time vocabulary quiz", lifespan=lifespan)
    app.state.services = services
    app.state.gateway = gateway = Gateway(
        services.settings, services.tickets, services.service, services.store
    )
    app.add_api_websocket_route("/ws", gateway.endpoint)
    ticker = Ticker(services.store, gateway.registry, services.settings.node_id)
    gateway.registry.watcher = ticker
    services.shutdown.append(ticker.stop)  # stop hooks run in reverse: before the store closes
    s, ttl_ms = services.settings, TICKET_TTL_S * 1000
    token = s.admin_token.get_secret_value() if s.admin_mock and s.admin_token else None
    burst = 2 * s.per_ip_conn_cap  # a session and a ticket for each socket one address may hold
    limit = AddressRateLimiter(burst / IDENTITY_REFILL_S, burst, monotonic_ms)
    deps = HttpDeps(services.store, services.tickets, services.bank, services.ready, ttl_ms, limit)
    proxies = s.trusted_proxies
    install(app, replace(deps, trusted_proxies=proxies, admin_token=token, outages=OUTAGES))
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
