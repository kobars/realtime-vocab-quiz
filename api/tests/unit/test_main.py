# AI-ASSISTED: the composition root: store choice, lifespan hooks and the liveness route.
import httpx
import pytest
from fastapi import FastAPI

import quiz.main
from quiz.adapters.memory import MemoryStore
from quiz.adapters.mock_auth import MemoryTicketStore, RedisTicketStore
from quiz.adapters.redis import RedisStore
from quiz.config import Settings
from quiz.main import Hook, create_app, services_of


async def test_memory_store_uses_the_injected_clock() -> None:
    app = create_app(Settings(store="memory"), clock=lambda: 42)
    services = services_of(app)
    assert isinstance(services.store, MemoryStore)
    assert isinstance(services.tickets, MemoryTicketStore)
    assert services.clock() == 42
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
    services.shutdown += [hook("stop-a"), hook("stop-b")]
    with pytest.raises(RuntimeError, match="start-b"):
        async with app.router.lifespan_context(app):
            pass
    assert calls == ["start-a", "start-b", "stop-b", "stop-a"]


async def test_healthz_answers() -> None:
    transport = httpx.ASGITransport(app=create_app(Settings()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert (resp.status_code, resp.json()) == (200, {"status": "ok"})


def test_module_app_is_built_on_first_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE", "memory")
    assert isinstance(quiz.main.app, FastAPI)
