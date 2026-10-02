# AI-ASSISTED: memory-store behavior Redis cannot fake (a clock that steps back), its ranking memo
# and the eviction of idle quizzes.
from collections.abc import Iterable

import pytest

from quiz.adapters.memory import MemoryStore
from quiz.adapters.memory import store as memory_store
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.domain.standings import RankedStanding, Standing, standings
from quiz.ports.store import QUIZ_TTL_MS, Limits, Row


async def one_question_quiz() -> tuple[MemoryStore, list[int]]:
    now = [10_000]  # the clock; a test steps it back by hand
    store = MemoryStore(lambda: now[0])
    await store.create_quiz("VOCAB-1", (Question("q0", 1),), window_ms=60_000, time_limit_ms=20_000)
    return store, now


async def test_step_back_and_replay_flags_stay_outside_the_stored_reply() -> None:
    store, now = await one_question_quiz()
    await store.join("VOCAB-1", "a", "A", "c1")
    await store.serve_next("VOCAB-1", "a", 0, "c1")
    now[0] -= 50
    first = await store.apply_answer("VOCAB-1", "a", 0, 1, "s1", "c1")
    assert (first.step_back, first.replay, first.result.points) == (True, False, 150)
    replay = await store.apply_answer("VOCAB-1", "a", 0, 1, "s1", "c1")
    assert (replay.step_back, replay.replay, replay.result) == (False, True, first.result)


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


def counting_standings(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count the store's full rankings; the list holds the count so far."""
    calls = [0]

    def counted(players: Iterable[Standing]) -> list[RankedStanding]:
        calls[0] += 1
        return standings(players)

    monkeypatch.setattr(memory_store, "standings", counted)
    return calls


async def test_ranks_of_no_users_ranks_nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    store, now = await one_question_quiz()
    for i in range(2_000):
        await store.join("VOCAB-1", f"u{i}", f"U{i}", f"c{i}")

    def refuse(_: Iterable[Standing]) -> list[RankedStanding]:
        pytest.fail("ranked every player")

    monkeypatch.setattr(memory_store, "standings", refuse)
    ranks = await store.ranks_of("VOCAB-1", ())
    assert (ranks.status, ranks.player_count, ranks.rows) == ("open", 2_000, {})
    now[0] += 60_000
    assert (await store.ranks_of("VOCAB-1", ())).status == "ended"


async def test_rankings_are_computed_once_per_state_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _ = await one_question_quiz()
    for user in "abc":
        await store.join("VOCAB-1", user, user.upper(), f"c-{user}")
        await store.serve_next("VOCAB-1", user, 0, f"c-{user}")
    await store.apply_answer("VOCAB-1", "a", 0, 1, "s-a", "c-a")
    calls = counting_standings(monkeypatch)
    for _ in range(50):
        await store.ranks_of("VOCAB-1", ("b",))
        await store.standings_page("VOCAB-1", 0, 10)
        await store.snapshot("VOCAB-1", "b")
    assert calls == [1]
    await store.apply_answer("VOCAB-1", "b", 0, 1, "s-b", "c-b")
    ranks = await store.ranks_of("VOCAB-1", ("b",))
    assert (calls, ranks.rows) == ([2], {"b": Row(2, "b", "B", 150)})
    await store.join("VOCAB-1", "d", "D", "c-d")
    assert ((await store.ranks_of("VOCAB-1", ("d",))).player_count, calls) == (4, [3])


async def test_an_idle_quiz_is_dropped_after_the_ttl_once_nobody_subscribes() -> None:
    store, now = await one_question_quiz()
    for user in "ab":
        await store.join("VOCAB-1", user, user.upper(), f"c-{user}")
    await store.serve_next("VOCAB-1", "a", 0, "c-a")
    await store.apply_answer("VOCAB-1", "a", 0, 1, "s-a", "c-a")
    await store.end_by_host("VOCAB-1")  # the last write
    async with store.subscribe("VOCAB-1"):
        now[0] += QUIZ_TTL_MS
        assert await store.read_seq("VOCAB-1") == 1  # a live feed keeps the quiz
    now[0] -= 1
    assert await store.read_seq("VOCAB-1") == 1  # one ms before the TTL
    now[0] += 1
    assert await store.read_seq("VOCAB-1") is None
    with pytest.raises(DomainError) as missing:
        await store.ranks_of("VOCAB-1", ())
    assert missing.value.code is ErrorCode.QUIZ_NOT_FOUND
    await store.create_quiz("VOCAB-1", (Question("q0", 1),), window_ms=60_000, time_limit_ms=1)


async def test_creating_a_quiz_drops_every_idle_quiz() -> None:
    store, now = await one_question_quiz()
    now[0] += QUIZ_TTL_MS
    await store.create_quiz("VOCAB-2", (Question("q0", 1),), window_ms=60_000, time_limit_ms=1)
    assert list(store._quizzes) == ["VOCAB-2"]  # noqa: SLF001 - what the store still holds
