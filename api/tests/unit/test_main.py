# AI-ASSISTED: the composition root: store choice, lifespan hooks and the liveness route.
import time

import httpx
import pytest
from fastapi import FastAPI

import quiz.main
from quiz.adapters.memory import MemoryStore
from quiz.adapters.mock_auth import MemoryTicketStore, RedisTicketStore
from quiz.adapters.redis import RedisStore
from quiz.config import Settings
from quiz.main import Hook, create_app, module_app, services_of
from quiz.ports.store import Limits


async def test_memory_store_runs_on_the_injected_clock_and_tickets_on_real_time() -> None:
    now = [0]
    services = services_of(create_app(Settings(store="memory"), clock=lambda: now[0]))
    assert isinstance(services.store, MemoryStore)
    assert isinstance(services.tickets, MemoryTicketStore)
    ticket = await services.tickets.issue_ticket((await services.tickets.create_session("Ann"))[1])
    now[0] += 60_000  # quiz time jumps past the 30 s ticket life; the ticket stays valid
    assert ticket is not None
    assert await services.tickets.redeem(ticket) is not None
    assert services.clock() == 60_000
    assert await services.bank.questions("VOCAB-42")


def test_redis_store_is_built_without_connecting() -> None:
    services = services_of(create_app(Settings(store="redis", redis_url="redis://unused:1/0")))
    assert isinstance(services.store, RedisStore)
    assert isinstance(services.tickets, RedisTicketStore)
    assert len(services.startup) == len(services.shutdown) == 1  # load scripts, close client


async def test_hooks_run_in_order_and_shutdown_runs_after_a_failed_start() -> None:
    app = create_app(Settings())
    calls: list[str] = []

    def hook(name: str, *, fail: bool = False) -> Hook:
        async def run() -> None:
            calls.append(name)
            if fail:
                raise RuntimeError(name)

        return run

    services = services_of(app)
    services.startup += [hook("start-a"), hook("start-b", fail=True), hook("start-c")]
    services.shutdown += [hook("stop-a"), hook("stop-b", fail=True), hook("stop-c")]
    with pytest.raises(RuntimeError, match="start-b") as raised:
        async with app.router.lifespan_context(app):
            pass
    assert calls == ["start-a", "start-b", "stop-c", "stop-b", "stop-a"]
    assert raised.value.__notes__ == ["stop hook failed: RuntimeError('stop-b')"]


async def test_every_stop_hook_runs_when_some_fail_after_a_clean_start() -> None:
    app = create_app(Settings())
    calls: list[str] = []

    def stop(name: str) -> Hook:
        async def run() -> None:
            calls.append(name)
            raise RuntimeError(name)

        return run

    services_of(app).shutdown += [stop("stop-a"), stop("stop-b")]
    with pytest.raises(ExceptionGroup) as raised:
        async with app.router.lifespan_context(app):
            pass
    assert calls == ["stop-b", "stop-a"]
    assert [str(error) for error in raised.value.exceptions] == ["stop-b", "stop-a"]


async def test_healthz_answers() -> None:
    transport = httpx.ASGITransport(app=create_app(Settings()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert (resp.status_code, resp.json()) == (200, {"status": "ok"})


def test_module_app_is_built_once_on_first_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE", "memory")
    module_app.cache_clear()
    try:
        assert isinstance(quiz.main.app, FastAPI)
        assert quiz.main.app is quiz.main.app
    finally:
        module_app.cache_clear()


@pytest.mark.parametrize("store", ["memory", "redis"])
def test_the_store_limits_come_from_the_settings(store: str) -> None:
    settings = Settings.model_validate(
        {"store": store, "redis_url": "redis://unused:1/0", "tick_ms": 50}
        | {"top_n": 1, "full_list_max": 2}
    )
    limits = services_of(create_app(settings)).store.limits  # type: ignore[attr-defined]
    assert limits == Limits(tick_ms=50, top_n=1, full_list_max=2)


@pytest.mark.parametrize("store", ["memory", "redis"])
def test_the_resync_limit_runs_on_a_monotonic_clock(
    monkeypatch: pytest.MonkeyPatch, store: str
) -> None:
    settings = Settings(store=store, redis_url="redis://unused:1/0")
    service = services_of(create_app(settings)).service

    def no_wall_clock() -> int:
        raise AssertionError

    monkeypatch.setattr(time, "time_ns", no_wall_clock)  # a wall-clock step cannot reach it
    first = service._clock()  # noqa: SLF001
    assert service._clock() >= first  # noqa: SLF001
