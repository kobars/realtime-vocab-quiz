# AI-ASSISTED: Hypothesis properties of the scoring rule and of a player's running total.
from hypothesis import given
from hypothesis import strategies as st

from quiz.domain.scoring import score_answer
from quiz.domain.standings import Standing, record_points

time_limits = st.integers(min_value=1, max_value=600_000)


def _bonus(elapsed_ms: int, time_limit_ms: int) -> int:
    return score_answer(correct=True, elapsed_ms=elapsed_ms, time_limit_ms=time_limit_ms) - 100


@given(time_limits, st.data())
def test_bonus_never_increases_with_elapsed_time(time_limit_ms: int, data: st.DataObject) -> None:
    on_time = st.integers(min_value=-1_000, max_value=time_limit_ms)
    earlier = data.draw(on_time)
    later = data.draw(st.integers(min_value=earlier, max_value=time_limit_ms))
    assert _bonus(later, time_limit_ms) <= _bonus(earlier, time_limit_ms)


@given(time_limits, st.data())
def test_bonus_stays_in_0_to_50(time_limit_ms: int, data: st.DataObject) -> None:
    elapsed_ms = data.draw(st.integers(min_value=-(10**9), max_value=time_limit_ms))
    assert 0 <= _bonus(elapsed_ms, time_limit_ms) <= 50


@given(time_limits, st.data())
def test_late_or_wrong_scores_zero(time_limit_ms: int, data: st.DataObject) -> None:
    late = data.draw(st.integers(min_value=time_limit_ms + 1, max_value=10**9))
    any_elapsed = data.draw(st.integers(min_value=-(10**9), max_value=10**9))
    assert score_answer(correct=True, elapsed_ms=late, time_limit_ms=time_limit_ms) == 0
    assert score_answer(correct=False, elapsed_ms=any_elapsed, time_limit_ms=time_limit_ms) == 0


answers = st.tuples(st.booleans(), st.integers(min_value=-1_000, max_value=25_000))


@given(st.lists(answers, max_size=10), st.integers(min_value=0, max_value=60_000))
def test_game_total_is_the_sum_of_its_points(
    game: list[tuple[bool, int]], joined_at_rel_ms: int
) -> None:
    points = [score_answer(correct=c, elapsed_ms=e, time_limit_ms=20_000) for c, e in game]
    standing = Standing("p", total=0, reached_rel_ms=joined_at_rel_ms)
    for i, awarded in enumerate(points):
        standing = record_points(standing, points=awarded, at_rel_ms=joined_at_rel_ms + i * 1_000)
    assert standing.total == sum(points)
