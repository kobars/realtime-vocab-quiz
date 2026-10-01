# AI-ASSISTED: the Redis feed refuses an unconfirmed subscription and maps redis-py errors.
from collections.abc import AsyncIterator

import pytest
from redis import exceptions as redis_errors

from quiz.adapters.redis import RedisStore


class StubPubSub:
    def __init__(self, confirmation: dict[str, object] | None) -> None:
        self.confirmation = confirmation
        self.closed = False

    async def subscribe(self, *_: str) -> None:
        pass

    async def get_message(self, **_: float) -> dict[str, object] | None:
        return self.confirmation

    async def listen(self) -> AsyncIterator[dict[str, object]]:
        yield {"type": "message", "data": "first"}
        raise redis_errors.ConnectionError

    async def aclose(self) -> None:
        self.closed = True


class StubRedis:
    def __init__(self, pubsub: StubPubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self) -> StubPubSub:
        return self._pubsub


async def test_unconfirmed_subscription_is_unreachable_and_closed() -> None:
    pubsub = StubPubSub(confirmation=None)
    store = RedisStore(StubRedis(pubsub))  # type: ignore[arg-type]
    with pytest.raises(ConnectionError):
        async with store.subscribe("VOCAB-42"):
            pytest.fail("entered without a confirmed subscription")
    assert pubsub.closed


async def test_a_dropped_feed_raises_the_builtin_connection_error() -> None:
    pubsub = StubPubSub(confirmation={"type": "subscribe"})
    store = RedisStore(StubRedis(pubsub))  # type: ignore[arg-type]
    async with store.subscribe("VOCAB-42") as messages:
        assert await anext(messages) == "first"
        with pytest.raises(ConnectionError) as raised:
            await anext(messages)
    assert not isinstance(raised.value, redis_errors.RedisError)
    assert pubsub.closed
