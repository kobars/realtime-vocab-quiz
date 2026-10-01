# AI-ASSISTED: Hypothesis properties of the standings order and the sorted-set score encoding.
from hypothesis import given
from hypothesis import strategies as st

from quiz.domain.standings import (
    MAX_REACHED_REL_MS,
    MAX_TOTAL,
    Standing,
    decode_sort_score,
    encode_sort_score,
    record_points,
    standings,
)

totals = st.integers(min_value=0, max_value=MAX_TOTAL)
reached = st.integers(min_value=0, max_value=MAX_REACHED_REL_MS)
user_ids = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=1,
    max_size=64,
)
# Small totals and times make ties common, so every tie-break is exercised.
entries = st.lists(
    st.builds(
        Standing,
        user_id=user_ids,
        total=st.one_of(st.integers(0, 3), totals),
        reached_rel_ms=st.one_of(st.integers(0, 3), reached),
    ),
    max_size=30,
    unique_by=lambda s: s.user_id,
)


@given(entries)
def test_standings_match_a_plain_sort(rows: list[Standing]) -> None:
    expected = sorted(rows, key=lambda s: (-s.total, s.reached_rel_ms, s.user_id))
    ranked = standings(rows)
    assert [row.standing for row in ranked] == expected
    assert [row.rank for row in ranked] == list(range(1, len(rows) + 1))


@given(totals, reached)
def test_sort_score_round_trips(total: int, reached_rel_ms: int) -> None:
    score = encode_sort_score(total, reached_rel_ms)
    assert decode_sort_score(score) == (total, reached_rel_ms)
    assert float(score) == score  # exact in a double, as Redis stores it


@given(entries)
def test_sort_score_orders_like_standings(rows: list[Standing]) -> None:
    # Redis ZRANGE: ascending score, ties broken by member (the user id) ascending.
    by_score = sorted(rows, key=lambda s: (encode_sort_score(s.total, s.reached_rel_ms), s.user_id))
    assert by_score == [row.standing for row in standings(rows)]


@given(
    st.builds(Standing, user_id=user_ids, total=st.integers(0, 1_500), reached_rel_ms=reached),
    st.integers(min_value=0, max_value=150),
    st.integers(min_value=-1_000, max_value=MAX_REACHED_REL_MS),
)
def test_reached_time_changes_only_on_points(start: Standing, points: int, at_rel_ms: int) -> None:
    after = record_points(start, points=points, at_rel_ms=at_rel_ms)
    if points == 0:
        assert after == start
    else:
        assert after.total == start.total + points
        assert after.reached_rel_ms == max(0, at_rel_ms)
    assert after.user_id == start.user_id
