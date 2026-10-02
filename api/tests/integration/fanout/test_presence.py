# AI-ASSISTED: the presence renew loop: another node drops presence that no live node renews.
import asyncio
import uuid
from typing import cast

import pytest
from fastapi import WebSocket
from redis.asyncio import Redis

from quiz.adapters.redis import RedisStore
from quiz.adapters.redis.keys import quiz_keys
from quiz.adapters.ws.registry import Registry
from quiz.adapters.ws.sender import Sender
from quiz.app.service import Connection
from quiz.config import KIB
from quiz.domain.session import Question
from quiz.fanout.presence import PresenceRenewer
from quiz.ports.store import Store

GRACE_MS, RENEW_MS = 100, 50  # entries go stale 150 ms after their last renew


class Quiet:  # a socket that takes every frame
    async def send_text(self, text: str) -> None:
        pass

    async def close(self, code: int) -> None:
        pass


class LeaveFails:  # the store as the grace timer of a node whose leave cannot reach Redis
    async def leave(self, *_: str) -> bool:
        msg = "redis is down"
        raise ConnectionError(msg)


def joined(registry: Registry, quiz_id: str, user: str) -> Connection:
    conn = Connection(f"c-{user}", user, quiz_id, present=True)
    registry.bind(conn, Sender(cast("WebSocket", Quiet()), 64 * KIB, 256 * KIB))
    return conn


async def test_another_nodes_renew_drops_presence_that_no_live_node_renews(
    redis_store: RedisStore, redis_client: Redis, redis_prefix: str
) -> None:
    quiz_id = f"T-{uuid.uuid4().hex[:12].upper()}"
    keys = quiz_keys(quiz_id, redis_prefix)
    create = redis_store.create_quiz
    await create(quiz_id, (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
    for user in ("a", "b", "c"):
        await redis_store.join(quiz_id, user, user.upper(), f"c-{user}")
    stopped, live = Registry(cast("Store", LeaveFails()), 1), Registry(redis_store, GRACE_MS)
    stopped.drop(joined(stopped, quiz_id, "a"))  # its leave fails
    joined(stopped, quiz_id, "c")  # held by a node that renews nothing: it stopped
    joined(live, quiz_id, "b")
    await redis_client.delete(keys.dirty)
    renewer = PresenceRenewer(redis_store, live, GRACE_MS, RENEW_MS)
    await renewer.start()
    await asyncio.sleep(0.4)
    await renewer.stop()
    assert await redis_client.hkeys(keys.present) == ["b"]  # the live connection stays
    assert await redis_client.get(keys.dirty) == "1"


async def test_a_failed_renew_is_logged_and_the_next_one_still_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Down:
        calls = 0

        async def renew_presence(self, *_: object) -> None:
            self.calls += 1
            msg = "redis is down"
            raise ConnectionError(msg)

    registry, store = Registry(cast("Store", None), GRACE_MS), Down()
    joined(registry, "VOCAB-42", "a")
    renewer = PresenceRenewer(cast("Store", store), registry, GRACE_MS, RENEW_MS)
    await renewer.start()
    await asyncio.sleep(0.18)
    await renewer.stop()
    assert store.calls >= 2
    assert "presence renew of quiz VOCAB-42 failed" in caplog.text
