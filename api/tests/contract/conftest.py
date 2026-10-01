# AI-ASSISTED: the store fixtures of the contract suite; each store adds one harness parameter.
import uuid
from collections.abc import Awaitable, Callable

import pytest

from quiz.adapters.memory import MemoryStore
from quiz.ports.store import Store

# A store under test, and how to move its clock on by ms (a real clock just waits).
type Harness = tuple[Store, Callable[[int], Awaitable[None]]]


class ManualClock:
    def __init__(self) -> None:
        self.now = 1_000_000

    def __call__(self) -> int:
        return self.now


def memory_harness() -> Harness:
    clock = ManualClock()

    async def advance(ms: int) -> None:
        clock.now += ms

    return MemoryStore(clock), advance


@pytest.fixture(params=[pytest.param(memory_harness, id="memory")])
def harness(request: pytest.FixtureRequest) -> Harness:
    make: Callable[[], Harness] = request.param
    return make()


@pytest.fixture
def store(harness: Harness) -> Store:
    return harness[0]


@pytest.fixture
def advance(harness: Harness) -> Callable[[int], Awaitable[None]]:
    return harness[1]


@pytest.fixture
def quiz_id() -> str:
    return f"T-{uuid.uuid4().hex[:12].upper()}"
