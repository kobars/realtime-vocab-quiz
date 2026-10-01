# AI-ASSISTED: the shared store contract (docs/spec/redis.md §3); every store must pass it.
# Time moves only through ``advance`` and no exact points are asserted: real clocks pass too.
# ``advance(-ms)`` steps the clock back; a real clock cannot, and its harness ignores it.

from collections.abc import Awaitable, Callable

import pytest

from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import Question
from quiz.ports.store import End, Finished, Publish, Row, Served, Store

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
    j = await store.join(quiz_id, "a", "A", "c-a")  # the same connection again
    assert (j.cursor, j.cursor_open, j.total, j.question_count, j.replaced_conn_id) == (
        (0, True, 0, len(QUESTIONS), None)
    )
    await store.join(quiz_id, "b", "B", "c-b")
    assert (await store.ranks_of(quiz_id, ["b"])).rows["b"] == Row(2, "b", "B", 0)  # a counts once


async def test_new_connection_replaces_and_fences_the_old(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    assert (await store.join(quiz_id, "a", "A", "c-new")).replaced_conn_id == "c-a"
    assert await refused(store.serve_next(quiz_id, "a", 0, "c-a")) == ErrorCode.SESSION_REPLACED
    old = store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")
    assert await refused(old) == ErrorCode.SESSION_REPLACED
    assert (await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-new")).result.points > 0


async def test_correct_answer_scores_once_into_the_standings(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    r = (await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")).result
    assert (r.correct, r.late, r.total, r.correct_choice) == (True, False, r.points, 0)
    assert 100 <= r.points <= 150
    assert (await store.ranks_of(quiz_id, ["a"])).rows == {"a": Row(1, "a", "A", r.total)}


async def test_wrong_and_late_score_zero(store: Store, advance: Advance, quiz_id: str) -> None:
    await started(store, quiz_id, "a", limit_ms=100)
    assert await answer(store, quiz_id, "a", 0, 3, "s1") == 0
    await store.serve_next(quiz_id, "a", 1, "c-a")
    await advance(150)
    late = (await store.apply_answer(quiz_id, "a", 1, 1, "s2", "c-a")).result
    assert (late.correct, late.late, late.points, late.total) == (True, True, 0, 0)


async def test_replay_returns_same_result(store: Store, advance: Advance, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    first = await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")
    await advance(50)
    again = await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")
    assert again.result == first.result
    assert (await store.ranks_of(quiz_id, ["a"])).rows["a"] == Row(1, "a", "A", first.result.total)


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
    closed = store.apply_answer(quiz_id, "a", 0, 0, "s2", "c-a")
    assert await refused(closed) == ErrorCode.ALREADY_ANSWERED
    await store.serve_next(quiz_id, "a", 1, "c-a")
    await store.serve_next(quiz_id, "a", 2, "c-a")  # skips question 1
    skipped = store.apply_answer(quiz_id, "a", 1, 1, "s3", "c-a")
    assert await refused(skipped) == ErrorCode.ALREADY_ANSWERED
    assert (await store.ranks_of(quiz_id, ["a"])).rows["a"] == Row(1, "a", "A", points)


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


async def test_finished_player_gets_only_the_retry_rows(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a", "b")
    for i in (1, 2):
        await store.serve_next(quiz_id, "a", i, "c-a")
    total = await answer(store, quiz_id, "a", 2, 2, "s1")  # answering the last question finishes
    retry = await store.serve_next(quiz_id, "a", 2, "c-a")  # a retry re-serves, writes nothing
    assert isinstance(retry, Served)
    assert (retry.question_index, retry.question_id) == (2, "q2")
    closed = store.apply_answer(quiz_id, "a", 2, 2, "s2", "c-a")
    assert await refused(closed) == ErrorCode.ALREADY_ANSWERED
    await store.serve_next(quiz_id, "b", len(QUESTIONS), "c-b")  # finishes with question 0 open
    assert isinstance(await store.serve_next(quiz_id, "b", 0, "c-b"), Served)
    assert await refused(store.serve_next(quiz_id, "b", 1, "c-b")) == ErrorCode.INVALID_STATE
    finished = await store.serve_next(quiz_id, "a", len(QUESTIONS), "c-a")
    assert isinstance(finished, Finished)
    assert (finished.total, finished.rank) == (total, 1)


async def test_refusals_after_the_deadline(store: Store, advance: Advance, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    first = await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")
    await store.serve_next(quiz_id, "a", 1, "c-a")
    await advance(WINDOW_MS)
    for user in ("a", "nobody"):  # the deadline check comes before the player check
        conn = f"c-{user}"
        assert await refused(store.join(quiz_id, user, "X", conn)) == ErrorCode.QUIZ_ENDED
        assert await refused(store.serve_next(quiz_id, user, 2, conn)) == ErrorCode.QUIZ_ENDED
        late = store.apply_answer(quiz_id, user, 1, 1, "s2", conn)
        assert await refused(late) == ErrorCode.QUIZ_ENDED
    again = await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")  # a replay still answers
    assert again.result == first.result
    assert not await store.leave(quiz_id, "a", "c-other")  # leave still compares the connection
    assert await store.leave(quiz_id, "a", "c-a")
    assert not await store.leave(quiz_id, "a", "c-a")


async def test_ranks_of_reads_many_users_at_one_seq(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a", "b")
    points = await answer(store, quiz_id, "b", 0, 0, "s1")
    ranks = await store.ranks_of(quiz_id, ["a", "b", "nobody"])
    assert (ranks.at_seq, ranks.player_count) == (0, 2)  # no broadcast yet
    assert ranks.rows == {"a": Row(2, "a", "A", 0), "b": Row(1, "b", "B", points), "nobody": None}


async def test_leave_compares_the_connection(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    await store.join(quiz_id, "a", "A", "c-new")
    assert not await store.leave(quiz_id, "a", "c-a")  # stale: a newer connection holds it
    assert isinstance(await store.serve_next(quiz_id, "a", 0, "c-new"), Served)
    assert await store.leave(quiz_id, "a", "c-new")
    assert not await store.leave(quiz_id, "a", "c-new")
    assert await refused(store.serve_next(quiz_id, "a", 1, "c-new")) == ErrorCode.NOT_JOINED
    assert (await store.ranks_of(quiz_id, ["a"])).rows["a"] is not None  # stays a player


async def test_standings_order_by_total_then_reached_time(
    store: Store, advance: Advance, quiz_id: str
) -> None:
    await started(store, quiz_id, "c")
    await advance(10)
    await started(store, quiz_id + "X")  # another quiz must not leak into this one
    for user in ("b", "a"):
        await store.join(quiz_id, user, user.upper(), f"c-{user}")
        await store.serve_next(quiz_id, user, 0, f"c-{user}")
        await advance(10)
    await answer(store, quiz_id, "a", 0, 0, "s1")
    page = await store.standings_page(quiz_id, 0, 10)
    assert [row.user_id for row in page.rows] == ["a", "c", "b"]  # c joined before b
    assert [row.rank for row in page.rows] == [1, 2, 3]


async def test_standings_pages(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, *"abcde")
    page = await store.standings_page(quiz_id, 1, 2)
    assert (page.at_seq, page.player_count, page.final) == (0, 5, False)
    assert [row.rank for row in page.rows] == [2, 3]
    assert (await store.standings_page(quiz_id, 5, 200)).rows == ()
    for offset, limit in ((0, 0), (0, 201), (-1, 1)):
        bad = store.standings_page(quiz_id, offset, limit)
        assert await refused(bad) == ErrorCode.INVALID_MESSAGE


async def test_snapshot_up_to_200_players_carries_all(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a", "b")
    await store.leave(quiz_id, "b", "c-b")
    snap = await store.snapshot(quiz_id, None)
    assert (snap.at_seq, snap.status, snap.player_count, snap.online_count) == (0, "open", 2, 1)
    assert [row.user_id for row in snap.rows] == ["a", "b"]
    assert snap.you is None


async def test_snapshot_above_200_players_carries_top_50(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id)
    for n in range(201):
        await store.join(quiz_id, f"u{n:03}", "U", f"c{n}")
    snap = await store.snapshot(quiz_id, "u200")
    assert (snap.player_count, snap.online_count, len(snap.rows)) == (201, 201, 50)
    assert [row.rank for row in snap.rows] == list(range(1, 51))
    assert snap.you == Row(201, "u200", "U", 0)


async def test_dirty_gates_publish_and_tick_holds(
    store: Store, advance: Advance, quiz_id: str
) -> None:
    await started(store, quiz_id, "a")
    first = await store.publish_if_dirty(quiz_id, "n1")
    assert (first.status, first.seq) == ("published", 1)
    await answer(store, quiz_id, "a", 0, 0, "s1")  # dirty again, but the token holds
    busy = await store.publish_if_dirty(quiz_id, "n2")
    assert busy.status == "busy"
    assert 0 < busy.retry_ms <= 200
    await advance(250)
    assert await store.publish_if_dirty(quiz_id, "n2") == Publish("published", 2)
    await advance(250)
    assert (await store.publish_if_dirty(quiz_id, "n1")).status == "clean"
    await store.serve_next(quiz_id, "a", 1, "c-a")
    await answer(store, quiz_id, "a", 1, 0, "s2")  # wrong, 0 points: standings unchanged
    assert (await store.publish_if_dirty(quiz_id, "n1")).status == "clean"


async def test_tick_token_holds_at_most_200_ms_after_a_clock_step_back(
    store: Store, advance: Advance, quiz_id: str
) -> None:
    await started(store, quiz_id, "a")
    assert (await store.publish_if_dirty(quiz_id, "n1")).status == "published"
    await advance(-5000)
    await store.join(quiz_id, "b", "B", "c-b")  # dirty again
    busy = await store.publish_if_dirty(quiz_id, "n2")
    assert busy.status == "busy"
    assert 0 < busy.retry_ms <= 200
    await advance(200)
    assert await store.publish_if_dirty(quiz_id, "n2") == Publish("published", 2)


async def test_seq_moves_only_with_broadcasts(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    result = (await store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")).result
    assert result.at_seq == (await store.snapshot(quiz_id, None)).at_seq == 0
    assert (await store.publish_if_dirty(quiz_id, "n1")).seq == 1
    served = await store.serve_next(quiz_id, "a", 1, "c-a")
    assert served.at_seq == (await store.standings_page(quiz_id, 0, 1)).at_seq == 1
    assert await store.end_quiz(quiz_id, "host") == End("marked")
    assert (await store.snapshot(quiz_id, None)).at_seq == 1  # the mark broadcasts nothing
    assert await store.end_quiz(quiz_id, "host") == End("ended", 2)


async def test_end_quiz_twice_announces_once(store: Store, quiz_id: str) -> None:
    await started(store, quiz_id, "a")
    assert await store.end_quiz(quiz_id, "host") == End("marked")
    assert await refused(store.join(quiz_id, "b", "B", "c-b")) == ErrorCode.QUIZ_ENDED
    assert await refused(store.serve_next(quiz_id, "a", 1, "c-a")) == ErrorCode.QUIZ_ENDED
    assert await store.publish_if_dirty(quiz_id, "n1") == Publish("ended", None)
    assert await store.end_quiz(quiz_id, "deadline") == End("not_due")  # marked, not due
    ended = await store.end_quiz(quiz_id, "host")
    assert ended == End("ended", 1)
    assert await store.end_quiz(quiz_id, "host") == ended
    assert await store.end_quiz(quiz_id, "deadline") == ended
    assert await store.publish_if_dirty(quiz_id, "n1") == Publish("ended", 1)
    snap = await store.snapshot(quiz_id, "a")
    assert (snap.status, snap.at_seq) == ("ended", 1)
    assert (await store.standings_page(quiz_id, 0, 10)).final


async def test_host_mark_survives_a_clock_step_back(
    store: Store, advance: Advance, quiz_id: str
) -> None:
    await started(store, quiz_id, "a")
    assert await store.end_quiz(quiz_id, "host") == End("marked")
    await advance(-1)
    assert (await store.snapshot(quiz_id, None)).status == "ended"
    assert (await store.standings_page(quiz_id, 0, 10)).final
    assert await refused(store.join(quiz_id, "b", "B", "c-b")) == ErrorCode.QUIZ_ENDED
    late = store.apply_answer(quiz_id, "a", 0, 0, "s1", "c-a")
    assert await refused(late) == ErrorCode.QUIZ_ENDED
    assert await store.publish_if_dirty(quiz_id, "n1") == Publish("ended", None)
    assert await store.end_quiz(quiz_id, "host") == End("ended", 1)


async def test_deadline_ends_the_quiz(store: Store, advance: Advance, quiz_id: str) -> None:
    await store.create_quiz(quiz_id, QUESTIONS, window_ms=300, time_limit_ms=LIMIT_MS)
    await store.join(quiz_id, "a", "A", "c-a")
    assert await store.end_quiz(quiz_id, "deadline") == End("not_due")
    await advance(350)
    assert await refused(store.serve_next(quiz_id, "a", 0, "c-a")) == ErrorCode.QUIZ_ENDED
    assert await store.publish_if_dirty(quiz_id, "n1") == Publish("ended", None)
    assert await store.end_quiz(quiz_id, "deadline") == End("ended", 1)
    assert await store.publish_if_dirty(quiz_id, "n1") == Publish("ended", 1)


async def test_leave_sets_dirty_only_while_open(
    store: Store, advance: Advance, quiz_id: str
) -> None:
    await started(store, quiz_id, "a", "b")
    await store.join(quiz_id, "a", "A", "c-new")
    await store.publish_if_dirty(quiz_id, "n1")
    await advance(250)
    assert not await store.leave(quiz_id, "a", "c-a")  # stale: writes nothing
    assert (await store.publish_if_dirty(quiz_id, "n1")).status == "clean"
    assert await store.leave(quiz_id, "a", "c-new")
    assert await store.publish_if_dirty(quiz_id, "n1") == Publish("published", 2)
    await advance(250)
    await store.end_quiz(quiz_id, "host")
    assert await store.leave(quiz_id, "b", "c-b")  # after the mark: the seat is still freed
    assert await store.end_quiz(quiz_id, "host") == End("ended", 3)
    assert (await store.snapshot(quiz_id, None)).online_count == 0
