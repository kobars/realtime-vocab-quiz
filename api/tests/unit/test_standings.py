# AI-ASSISTED: example tests of the standings order, reached time and sorted-set score.
import pytest

from quiz.domain.standings import (
    MAX_REACHED_REL_MS,
    MAX_TOTAL,
    Standing,
    decode_sort_score,
    encode_sort_score,
    record_points,
    standings,
)


def test_order_total_then_reached_then_user() -> None:
    entries = [
        Standing("carol", total=250, reached_rel_ms=9_000),
        Standing("bob", total=250, reached_rel_ms=4_000),
        Standing("alice", total=250, reached_rel_ms=4_000),
        Standing("dave", total=300, reached_rel_ms=12_000),
        Standing("erin", total=0, reached_rel_ms=100),
    ]
    order = [row.standing.user_id for row in standings(entries)]
    assert order == ["dave", "alice", "bob", "carol", "erin"]


def test_ranks_are_unique_1_to_n() -> None:
    entries = [Standing(f"u{i}", total=100, reached_rel_ms=0) for i in range(5)]
    assert [row.rank for row in standings(entries)] == [1, 2, 3, 4, 5]


def test_empty_standings() -> None:
    assert standings([]) == []


def test_duplicate_user_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        standings([Standing("a", 0, 0), Standing("a", 100, 5)])


def test_wrong_answer_keeps_the_tie_break_time() -> None:
    start = Standing("a", total=133, reached_rel_ms=7_000)
    assert record_points(start, points=0, at_rel_ms=30_000) == start


def test_scoring_answer_moves_total_and_reached_time() -> None:
    start = Standing("a", total=133, reached_rel_ms=7_000)
    assert record_points(start, points=120, at_rel_ms=30_000) == Standing("a", 253, 30_000)


def test_reached_time_after_clock_step_back_is_clamped() -> None:
    start = Standing("a", total=0, reached_rel_ms=0)
    assert record_points(start, points=150, at_rel_ms=-20) == Standing("a", 150, 0)


def test_sort_score_layout() -> None:
    assert encode_sort_score(0, 0) == 2**30 * 2**22
    assert encode_sort_score(133, 6_800) == (2**30 - 133) * 2**22 + 6_800
    assert encode_sort_score(MAX_TOTAL, MAX_REACHED_REL_MS) < 2**53


def test_sort_score_decodes() -> None:
    assert decode_sort_score(encode_sort_score(1_234, 56_789)) == (1_234, 56_789)


@pytest.mark.parametrize(
    ("total", "reached_rel_ms"),
    [(-1, 0), (MAX_TOTAL + 1, 0), (0, -1), (0, MAX_REACHED_REL_MS + 1)],
)
def test_sort_score_rejects_out_of_range(total: int, reached_rel_ms: int) -> None:
    with pytest.raises(ValueError, match="out of range"):
        encode_sort_score(total, reached_rel_ms)


@pytest.mark.parametrize("score", [-1, (2**30 + 1) * 2**22])
def test_decode_rejects_out_of_range(score: int) -> None:
    with pytest.raises(ValueError, match="out of range"):
        decode_sort_score(score)
