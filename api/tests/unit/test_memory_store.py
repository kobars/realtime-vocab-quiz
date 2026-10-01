# AI-ASSISTED: memory-store behavior that needs a clock that steps back, which Redis cannot fake.
from quiz.adapters.memory import MemoryStore
from quiz.domain.session import Question
from quiz.ports.store import Limits, Row


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
    assert (await store.ranks_of("VOCAB-1", ["z"])).rows == {"z": Row(2, "z", "Z", 0)}


async def test_snapshot_and_tick_follow_the_configured_limits() -> None:
    now = [10_000]
    store = MemoryStore(lambda: now[0], Limits(tick_ms=50, top_n=1, full_list_max=2))
    await store.create_quiz("VOCAB-1", (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
    for user in "ab":
        await store.join("VOCAB-1", user, user.upper(), f"c-{user}")
    assert len((await store.snapshot("VOCAB-1", None)).rows) == 2  # up to full_list_max: all
    await store.join("VOCAB-1", "c", "C", "c-c")
    assert len((await store.snapshot("VOCAB-1", None)).rows) == 1  # above it: the top_n
    assert (await store.publish_if_dirty("VOCAB-1", "n1")).status == "published"
    await store.join("VOCAB-1", "d", "D", "c-d")
    assert (await store.publish_if_dirty("VOCAB-1", "n1")).retry_ms == 50
