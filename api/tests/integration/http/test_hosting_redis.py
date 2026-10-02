# AI-ASSISTED: self-service hosting on two nodes sharing one Redis: one cap, the end on either.
import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis

from quiz.adapters.redis.keys import quiz_keys
from quiz.adapters.redis.store import HOSTED_KEY
from quiz.config import Settings
from quiz.main import create_app, services_of


def node(redis_url: str, node_id: str) -> FastAPI:
    settings = {"store": "redis", "redis_url": redis_url, "node_id": node_id, "hosting_max_open": 1}
    return create_app(Settings.model_validate(settings))


@pytest.fixture
async def redis(redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url, decode_responses=True)
    await client.delete(HOSTED_KEY)  # the nodes use no key prefix: start from an empty count
    yield client
    await client.delete(HOSTED_KEY)
    await client.aclose()


async def test_two_nodes_share_the_cap_and_either_ends_the_quiz(
    redis_url: str, redis: Redis
) -> None:
    one, two = node(redis_url, "n1"), node(redis_url, "n2")
    async with (
        one.router.lifespan_context(one),
        two.router.lifespan_context(two),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=one), base_url="http://one") as a,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=two), base_url="http://two") as b,
    ):
        hosted = (await a.post("/quizzes", json={"bankQuizId": "BIZ-20"})).json()
        quiz_id, token = hosted["quizId"], hosted["hostToken"]
        full = await b.post("/quizzes", json={"bankQuizId": "VOCAB-42"})
        assert (full.status_code, full.json()["error"]) == (503, "HOSTING_FULL")
        meta = await redis.hgetall(quiz_keys(quiz_id).meta)
        assert meta["hostHash"] == hashlib.sha256(token.encode()).hexdigest()
        assert token not in meta.values()
        assert await redis.pttl(HOSTED_KEY) > 0  # the count expires with its newest quiz

        assert (await b.post(f"/quizzes/{quiz_id}/end")).status_code == 403
        ended = await b.post(f"/quizzes/{quiz_id}/end", headers={"X-Host-Token": token})
        assert (ended.status_code, ended.json()["status"]) == (200, "ended")
        assert (await a.get(f"/quizzes/{quiz_id}")).json()["status"] == "ended"
        assert (await b.post("/quizzes", json={"bankQuizId": "VOCAB-42"})).status_code == 201


async def test_a_shorter_window_keeps_the_count_of_longer_ones(
    redis_url: str, redis: Redis
) -> None:
    app = node(redis_url, "n1")
    async with app.router.lifespan_context(app):
        store = services_of(app).store
        assert await store.hold_hosted("LONG-AAAA", 3_600_000, 2)
        assert await store.hold_hosted("SHORT-AAAA", 60_000, 2)  # HOSTING_WINDOW_MS lowered
        assert await redis.pttl(HOSTED_KEY) > 3_500_000  # the key outlives the long one's window
