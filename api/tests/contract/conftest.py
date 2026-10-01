# AI-ASSISTED: the store fixtures of the contract suite; each store adds one harness parameter.
import asyncio
import uuid
from collections.abc import Awaitable, Callable

import pytest

from quiz.adapters.memory import MemoryStore
from quiz.ports.store import Store

# A store under test, and how to move its clock on by ms (a real clock just waits).
type Harness = tuple[Store, Callable[[int], Awaitable[None]]]

# The longest step a test may take: a real clock sleeps through every step.
MAX_ADVANCE_MS = 1_000


def memory_harness() -> Harness:
    now = [1_000_000]

    async def advance(ms: int) -> None:
        assert ms <= MAX_ADVANCE_MS, f"advance({ms}) would sleep {ms / 1000} s on a real clock"
        now[0] += ms

    return MemoryStore(lambda: now[0]), advance


async def real_advance(ms: int) -> None:
    assert ms <= MAX_ADVANCE_MS, f"advance({ms}) would sleep {ms / 1000} s"
    await asyncio.sleep(ms / 1000)


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
    return store, real_advance


@pytest.fixture
def store(harness: Harness) -> Store:
    return harness[0]


@pytest.fixture
def advance(harness: Harness) -> Callable[[int], Awaitable[None]]:
    return harness[1]


@pytest.fixture
def quiz_id() -> str:
    return f"T-{uuid.uuid4().hex[:12].upper()}"
