# AI-ASSISTED: memory-store behavior that needs a clock that steps back, which Redis cannot fake.
from quiz.adapters.memory import MemoryStore
from quiz.domain.session import Question


class SteppingClock:
    def __init__(self) -> None:
        self.now = 10_000

    def __call__(self) -> int:
        return self.now


async def test_clock_step_back_returns_flag_outside_stored_reply() -> None:
    clock = SteppingClock()
    store = MemoryStore(clock)
    await store.create_quiz("VOCAB-1", (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
    await store.join("VOCAB-1", "a", "A", "c1")
    await store.serve_next("VOCAB-1", "a", 0, "c1")
    clock.now -= 50
    first = await store.apply_answer("VOCAB-1", "a", 0, 1, "s1", "c1")
    assert (first.step_back, first.result.points) == (True, 150)
    replay = await store.apply_answer("VOCAB-1", "a", 0, 1, "s1", "c1")
    assert (replay.step_back, replay.result) == (False, first.result)


async def test_join_after_clock_step_back_clamps_reached_time() -> None:
    clock = SteppingClock()
    store = MemoryStore(clock)
    await store.create_quiz("VOCAB-1", (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
    await store.join("VOCAB-1", "a", "A", "c1")  # reached at 0 ms
    clock.now -= 50
    await store.join("VOCAB-1", "z", "Z", "c2")  # -50 ms is clamped to 0: a tie, so a ranks first
    first, second = await store.rank_of("VOCAB-1", "a"), await store.rank_of("VOCAB-1", "z")
    assert (first and first.rank, second and second.rank) == (1, 2)
