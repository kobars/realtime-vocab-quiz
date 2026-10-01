# AI-ASSISTED: memory-store behavior that needs a clock that steps back, which Redis cannot fake.
from quiz.adapters.memory import MemoryStore
from quiz.domain.session import Question
from quiz.ports.store import Row


async def one_question_quiz() -> tuple[MemoryStore, list[int]]:
    now = [10_000]  # the clock; a test steps it back by hand
    store = MemoryStore(lambda: now[0])
    await store.create_quiz("VOCAB-1", (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
    return store, now


async def test_clock_step_back_returns_flag_outside_stored_reply() -> None:
    store, now = await one_question_quiz()
    await store.join("VOCAB-1", "a", "A", "c1")
    await store.serve_next("VOCAB-1", "a", 0, "c1")
    now[0] -= 50
    first = await store.apply_answer("VOCAB-1", "a", 0, 1, "s1", "c1")
    assert (first.step_back, first.result.points) == (True, 150)
    replay = await store.apply_answer("VOCAB-1", "a", 0, 1, "s1", "c1")
    assert (replay.step_back, replay.result) == (False, first.result)


async def test_join_after_clock_step_back_clamps_reached_time() -> None:
    store, now = await one_question_quiz()
    await store.join("VOCAB-1", "a", "A", "c1")  # reached at 0 ms
    now[0] -= 50
    await store.join("VOCAB-1", "z", "Z", "c2")  # -50 ms is clamped to 0: a tie, so a ranks first
    assert await store.rank_of("VOCAB-1", "z") == Row(2, "z", "Z", 0)
