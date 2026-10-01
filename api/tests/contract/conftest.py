# AI-ASSISTED: the store fixtures of the contract suite; each store adds one harness parameter.
import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import NamedTuple

import pytest
from redis.asyncio import Redis

from quiz.adapters.memory import MemoryStore
from quiz.adapters.redis.keys import quiz_keys
from quiz.domain.session import MAX_WINDOW_MS
from quiz.ports.store import Store

# The longest step a test may take: a real clock sleeps through every step.
MAX_ADVANCE_MS = 1_000
# Far above the 200 ms tick, so no slow step lets a held token lapse; a busy publish cuts it back.
HOLD_TICK_MS = 10_000


class Harness(NamedTuple):
    """A store under test and how a test moves its time.

    On a real clock no step races an expiry: the test sets up its state first, then the
    harness moves the expiry.
    """

    store: Store
    advance: Callable[[int], Awaitable[None]]  # the clock on by ms; a real clock just waits
    pass_deadline: Callable[[str], Awaitable[None]]  # the quiz's window is over from now on
    hold_tick: Callable[[str], Awaitable[None]]  # the tick token holds until a publish cuts it
    move_start: Callable[[str, int], Awaitable[None]]  # the quiz start lies ms after the clock


def memory_harness() -> Harness:
    now = [1_000_000]

    async def advance(ms: int) -> None:
        assert ms <= MAX_ADVANCE_MS, f"advance({ms}) would sleep {ms / 1000} s on a real clock"
        now[0] += ms

    async def pass_deadline(_: str) -> None:
        now[0] += MAX_WINDOW_MS  # past the longest window of any quiz started by now

    async def hold_tick(_: str) -> None:
        """The injected clock stands still between steps: the token already holds."""

    async def move_start(_: str, ms: int) -> None:
        now[0] -= ms  # a clock step back

    return Harness(MemoryStore(lambda: now[0]), advance, pass_deadline, hold_tick, move_start)


async def real_advance(ms: int) -> None:
    assert ms <= MAX_ADVANCE_MS, f"advance({ms}) would sleep {ms / 1000} s"
    await asyncio.sleep(ms / 1000)


def redis_harness(store: Store, client: Redis, prefix: str) -> Harness:
    async def pass_deadline(quiz_id: str) -> None:
        seconds, micros = await client.time()
        await client.hset(
            quiz_keys(quiz_id, prefix).meta, "deadlineMs", seconds * 1000 + micros // 1000
        )

    async def hold_tick(quiz_id: str) -> None:
        await client.set(quiz_keys(quiz_id, prefix).tick, "held", px=HOLD_TICK_MS)

    async def move_start(quiz_id: str, ms: int) -> None:
        await client.hincrby(quiz_keys(quiz_id, prefix).meta, "startMs", ms)

    return Harness(store, real_advance, pass_deadline, hold_tick, move_start)


@pytest.fixture(
    params=[
        pytest.param("memory", id="memory"),
        pytest.param("redis", id="redis", marks=pytest.mark.integration),
    ]
)
def harness(request: pytest.FixtureRequest) -> Harness:
    if request.param == "memory":
        return memory_harness()
    store: Store = request.getfixturevalue("redis_store")
    client: Redis = request.getfixturevalue("redis_client")
    return redis_harness(store, client, request.getfixturevalue("redis_prefix"))


@pytest.fixture
def store(harness: Harness) -> Store:
    return harness.store


@pytest.fixture
def advance(harness: Harness) -> Callable[[int], Awaitable[None]]:
    return harness.advance


@pytest.fixture
def pass_deadline(harness: Harness) -> Callable[[str], Awaitable[None]]:
    return harness.pass_deadline


@pytest.fixture
def hold_tick(harness: Harness) -> Callable[[str], Awaitable[None]]:
    return harness.hold_tick


@pytest.fixture
def move_start(harness: Harness) -> Callable[[str, int], Awaitable[None]]:
    return harness.move_start


@pytest.fixture
def quiz_id() -> str:
    return f"T-{uuid.uuid4().hex[:12].upper()}"
