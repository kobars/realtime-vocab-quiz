# AI-ASSISTED: the composition root on Redis: the start hook loads every Lua script; a join burst
# above the connection pool's size waits for a connection instead of failing; quiz subscriptions
# never take the command pool's connections; readiness needs a write that Redis accepts; a ticket
# renews its session's expiry; a node with every subscription taken refuses a join to a new quiz;
# a Redis that stops answering fails a request with 503 after the command timeout, while a quiet
# subscription waits past that timeout for its next message.
import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack, ExitStack
from functools import partial

import httpx
import pytest
from redis.asyncio import Redis
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from quiz.adapters.mock_auth import tokens
from quiz.adapters.mock_auth.redis_store import SESSION_KEY
from quiz.adapters.redis.keys import quiz_keys
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


async def test_a_paused_redis_answers_503_within_the_command_timeout(redis_url: str) -> None:
    settings = Settings(store="redis", redis_url=redis_url, redis_socket_timeout_ms=2_500)
    timeout_s = settings.redis_socket_timeout_ms / 1000
    pause_ms = settings.redis_socket_timeout_ms + 1_500  # CLIENT UNPAUSE would wait for it too
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    session = {"displayName": "Ana"}
    async with (
        Redis.from_url(redis_url) as admin,
        app.router.lifespan_context(app),  # its stop hooks close both Redis pools
        httpx.AsyncClient(transport=transport, base_url="http://node") as client,
    ):
        assert (await client.post("/sessions", json=session)).status_code == 201  # connected
        await admin.client_pause(pause_ms, all=True)
        started = time.monotonic()
        try:
            stuck = await client.post("/sessions", json=session)
            waited_s = time.monotonic() - started
        finally:
            await admin.ping()  # returns when the pause is over
    assert (stuck.status_code, stuck.json()["error"]) == (503, "UNAVAILABLE")
    assert timeout_s <= waited_s < pause_ms / 1000


async def test_a_quiet_subscription_outlives_the_command_timeout(redis_url: str) -> None:
    settings = Settings(store="redis", redis_url=redis_url, redis_socket_timeout_ms=2_500)
    app, quiz_id = create_app(settings), f"Q-{uuid.uuid4().hex[:8].upper()}"
    store = services_of(app).store
    async with (
        Redis.from_url(redis_url) as admin,
        app.router.lifespan_context(app),
        store.subscribe(quiz_id) as messages,
    ):
        waiting = asyncio.ensure_future(anext(messages))
        await asyncio.sleep(settings.redis_socket_timeout_ms / 1000 + 0.5)
        await admin.publish(quiz_keys(quiz_id).events, "frame")
        assert await asyncio.wait_for(waiting, 1) == "frame"


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


async def test_a_ticket_renews_its_session_for_the_full_lifetime(redis_url: str) -> None:
    app = create_app(Settings(store="redis", redis_url=redis_url))
    tickets = services_of(app).tickets
    async with Redis.from_url(redis_url) as admin, app.router.lifespan_context(app):
        _, token = await tickets.create_session("Ana")
        key = SESSION_KEY + tokens.digest(token)
        await admin.expire(key, 60)  # 1 h 59 min old
        assert await tickets.issue_ticket(token) is not None
        assert await admin.ttl(key) == tokens.SESSION_TTL_S


def test_a_join_to_a_quiz_past_the_subscription_limit_is_unavailable(
    redis_url: str, metric: Callable[..., float]
) -> None:
    settings = Settings(store="redis", redis_url=redis_url, redis_max_connections=1)
    app = create_app(settings)
    services, replies, opened = services_of(app), [], []
    quizzes = [f"F-{uuid.uuid4().hex[:8].upper()}" for _ in range(2)]
    create = partial(services.store.create_quiz, window_ms=60_000, time_limit_ms=20_000)

    async def ticket() -> str | None:
        return await services.tickets.issue_ticket((await services.tickets.create_session("A"))[1])

    with TestClient(app) as client, ExitStack() as sockets:
        portal = client.portal
        assert portal is not None
        before = metric("feed_subscribe_failures_total", reason="limit")
        for quiz_id in quizzes:  # both sockets stay open: the first quiz keeps its subscription
            portal.call(create, quiz_id, (Question("q0", 1),))
            url, origin = f"/ws?ticket={portal.call(ticket)}", {"origin": "http://localhost:8080"}
            ws = sockets.enter_context(client.websocket_connect(url, ["quiz.v1"], headers=origin))
            ws.send_text(
                json.dumps({"v": 1, "type": "join", "quizId": quiz_id, "displayName": "A"})
            )
            replies.append(ws.receive_json())
            opened.append(ws)
        with pytest.raises(WebSocketDisconnect) as closed:  # to reconnect, maybe to another node
            opened[-1].receive_json()
    assert closed.value.code == 1013
    assert replies[0]["type"] == "joined"
    assert (replies[1]["type"], replies[1]["code"]) == ("error", "UNAVAILABLE")
    assert metric("feed_subscribe_failures_total", reason="limit") == before + 1
