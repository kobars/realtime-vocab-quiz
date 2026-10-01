# AI-ASSISTED: the shared store contract (docs/spec/redis.md §3); every store must pass it.
"""Each test runs once per store. Time moves only through the ``advance`` fixture, and no
exact point value is asserted, so a store on a real clock passes the same tests."""

from collections.abc import Awaitable, Callable

import pytest

from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.ports.store import Finished, Served, Store

type Advance = Callable[[int], Awaitable[None]]

QUESTIONS = tuple(Question(f"q{i}", i % 4) for i in range(3))
WINDOW_MS, LIMIT_MS = 600_000, 20_000


async def refused(call: Awaitable[object]) -> ErrorCode:
    with pytest.raises(DomainError) as info:
        await call
    return info.value.code


async def started(store: Store, quiz_id: str, *users: str, limit_ms: int = LIMIT_MS) -> None:
    await store.create_quiz(quiz_id, QUESTIONS, window_ms=WINDOW_MS, time_limit_ms=limit_ms)
    for user in users:
        await store.join(quiz_id, user, user.upper(), f"c-{user}")
        await store.serve_next(quiz_id, user, 0, f"c-{user}")


async def answer(  # noqa: PLR0913, PLR0917
    store: Store, quiz_id: str, user: str, i: int, choice: int, sid: str
) -> int:
    return (await store.apply_answer(quiz_id, user, i, choice, sid, f"c-{user}")).result.points


async def score_of(store: Store, quiz_id: str, user: str) -> int:
    row = await store.rank_of(quiz_id, user)
    assert row is not None
    return row.score


async def test_unknown_quiz_is_not_found(store: Store, quiz_id: str) -> None:
    assert await refused(store.join(quiz_id, "a", "A", "c-a")) == ErrorCode.QUIZ_NOT_FOUND


@pytest.mark.parametrize(
    ("questions", "limit_ms"),
    [((), LIMIT_MS), ((QUESTIONS[0], QUESTIONS[0]), LIMIT_MS), (QUESTIONS, 0)],
    ids=["no-questions", "duplicate-ids", "zero-limit"],
)
async def test_invalid_quiz_shape_is_rejected(
    store: Store, quiz_id: str, questions: tuple[Question, ...], limit_ms: int
) -> None:
    create = store.create_quiz(quiz_id, questions, window_ms=1000, time_limit_ms=limit_ms)
    assert await refused(create) == ErrorCode.INVALID_MESSAGE


async def test_create_twice_is_invalid_state(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id)
    again = store.create_quiz(quiz_id, QUESTIONS, window_ms=1000, time_limit_ms=LIMIT_MS)
    assert await refused(again) == ErrorCode.INVALID_STATE


async def test_join_is_idempotent(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    joined = await store.join(quiz_id, "a", "A", "c-a")
    assert (joined.cursor, joined.cursor_open, joined.total) == (0, True, 0)
    assert joined.question_count == len(QUESTIONS)
    assert joined.replaced_conn_id is None
    await store.join(quiz_id, "b", "B", "c-b")
    row = await store.rank_of(quiz_id, "b")
    assert row is not None
    assert row.rank == 2  # a joined twice but counts once


async def test_new_connection_replaces_and_fences_the_old(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    assert (await store.join(quiz_id, "a", "A", "c-new")).replaced_conn_id == "c-a"
    assert await refused(store.serve_next(quiz_id, "a", 0, "c-a")) == ErrorCode.SESSION_REPLACED
    old = store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")
    assert await refused(old) == ErrorCode.SESSION_REPLACED
    assert (await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-new")).result.points > 0


async def test_correct_answer_scores_once_into_the_standings(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    result = (await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")).result
    assert result.correct
    assert not result.late
    assert 100 <= result.points <= 150
    assert (result.total, result.correct_choice) == (result.points, 0)
    row = await store.rank_of(quiz_id, "a")
    assert row is not None
    assert (row.rank, row.score, row.display_name) == (1, result.total, "A")


async def test_wrong_and_late_answers_score_zero(
    store: Store, advance: Advance, quiz_id: str
) -> None:
    await started(store, quiz_id, "a", limit_ms=100)
    assert await answer(store, quiz_id, "a", 0, 3, "s1") == 0
    await store.serve_next(quiz_id, "a", 1, "c-a")
    await advance(150)
    late = (await store.apply_answer(quiz_id, "a", 1, 1, "s2", "c-a")).result
    assert (late.correct, late.late, late.points, late.total) == (True, True, 0, 0)


async def test_same_submission_replays_identical_result(
    store: Store, advance: Advance, quiz_id: str
) -> None:
    await started(store, quiz_id, "a")
    first = await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")
    await advance(50)
    again = await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")
    assert again.result == first.result
    assert await score_of(store, quiz_id, "a") == first.result.total


async def test_submission_reused_for_other_question(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    await answer(store, quiz_id, "a", 0, 0, "s1")
    await store.serve_next(quiz_id, "a", 1, "c-a")
    reuse = store.apply_answer(quiz_id, "a", 1, 1, "s1", "c-a")
    assert await refused(reuse) == ErrorCode.INVALID_MESSAGE
    assert await answer(store, quiz_id, "a", 1, 1, "s2") > 0  # the reuse wrote nothing


async def test_closed_question_is_already_answered(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    points = await answer(store, quiz_id, "a", 0, 0, "s1")
    assert await refused(store.apply_answer(quiz_id, "a", 0, 0, "s2", "c-a")) == (
        ErrorCode.ALREADY_ANSWERED
    )
    await store.serve_next(quiz_id, "a", 1, "c-a")
    await store.serve_next(quiz_id, "a", 2, "c-a")  # skips question 1
    skipped = store.apply_answer(quiz_id, "a", 1, 1, "s3", "c-a")
    assert await refused(skipped) == ErrorCode.ALREADY_ANSWERED
    assert await score_of(store, quiz_id, "a") == points


async def test_serve_retry_order_and_finish(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    unserved = store.apply_answer(quiz_id, "a", 1, 1, "s1", "c-a")
    assert await refused(unserved) == ErrorCode.QUESTION_NOT_OPEN
    retry = await store.serve_next(quiz_id, "a", 0, "c-a")
    assert isinstance(retry, Served)
    assert (retry.question_index, retry.question_id) == (0, "q0")
    assert 0 < retry.remaining_ms <= LIMIT_MS
    assert await refused(store.serve_next(quiz_id, "a", 2, "c-a")) == ErrorCode.INVALID_STATE
    for i in (1, 2):
        await store.serve_next(quiz_id, "a", i, "c-a")
    finished = await store.serve_next(quiz_id, "a", len(QUESTIONS), "c-a")
    assert finished == Finished(finished.at_seq, total=0, rank=1, player_count=1)


async def test_rank_of(store: Store, advance: Advance, quiz_id: str) -> None:
    await started(store, quiz_id, "c")
    await advance(10)
    await started(store, quiz_id + "X", "z")  # another quiz must not leak into this one
    for user in ("b", "a"):
        await store.join(quiz_id, user, user.upper(), f"c-{user}")
        await store.serve_next(quiz_id, user, 0, f"c-{user}")
        await advance(10)
    await answer(store, quiz_id, "a", 0, 0, "s1")
    ranks = [await store.rank_of(quiz_id, user) for user in ("a", "c", "b")]
    assert [(row.rank, row.user_id) for row in ranks if row] == [(1, "a"), (2, "c"), (3, "b")]
    assert await store.rank_of(quiz_id, "z") is None
    assert await store.rank_of(quiz_id, "nobody") is None


async def test_leave_compares_the_connection(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    await store.join(quiz_id, "a", "A", "c-new")
    assert not await store.leave(quiz_id, "a", "c-a")  # stale: a newer connection holds it
    assert isinstance(await store.serve_next(quiz_id, "a", 0, "c-new"), Served)
    assert await store.leave(quiz_id, "a", "c-new")
    assert not await store.leave(quiz_id, "a", "c-new")
    assert await refused(store.serve_next(quiz_id, "a", 1, "c-new")) == ErrorCode.NOT_JOINED
    assert await store.rank_of(quiz_id, "a") is not None  # the player stays in the standings
