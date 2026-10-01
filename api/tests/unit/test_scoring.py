# AI-ASSISTED: example and exhaustive tests of the integer scoring rule (docs/spec/domain.md §4).
from fractions import Fraction
from math import floor

import pytest

from quiz.domain.scoring import DEFAULT_TIME_LIMIT_MS, score_answer

T = DEFAULT_TIME_LIMIT_MS


@pytest.mark.parametrize(
    ("elapsed_ms", "points"),
    [(0, 150), (6_800, 133), (20_000, 100), (20_001, 0)],
)
def test_worked_examples(elapsed_ms: int, points: int) -> None:
    assert score_answer(correct=True, elapsed_ms=elapsed_ms, time_limit_ms=T) == points


def test_late_by_one_ms_scores_zero() -> None:
    assert score_answer(correct=True, elapsed_ms=T + 1, time_limit_ms=T) == 0
    assert score_answer(correct=True, elapsed_ms=T, time_limit_ms=T) == 100


def test_clock_step_back_scores_full_bonus() -> None:
    assert score_answer(correct=True, elapsed_ms=-50, time_limit_ms=T) == 150


@pytest.mark.parametrize("elapsed_ms", [-50, 0, 6_800, 20_000, 20_001])
def test_wrong_answer_scores_zero(elapsed_ms: int) -> None:
    assert score_answer(correct=False, elapsed_ms=elapsed_ms, time_limit_ms=T) == 0


def test_textbook_float_form_would_be_wrong_at_6800() -> None:
    # The float form rounds e / T first; the rule must not depend on it.
    assert floor(50 * (1 - 6_800 / T)) == 32
    assert score_answer(correct=True, elapsed_ms=6_800, time_limit_ms=T) == 133


@pytest.mark.parametrize("time_limit_ms", [0, -1])
def test_non_positive_time_limit_is_rejected(time_limit_ms: int) -> None:
    with pytest.raises(ValueError, match="time_limit_ms"):
        score_answer(correct=True, elapsed_ms=0, time_limit_ms=time_limit_ms)


def _exact_points(elapsed_ms: int, time_limit_ms: int) -> int:
    e = max(0, elapsed_ms)
    if e > time_limit_ms:
        return 0
    return 100 + floor(Fraction(50 * (time_limit_ms - e), time_limit_ms))


def test_every_elapsed_matches_exact_fraction_arithmetic() -> None:
    mismatches = [
        e
        for e in range(-1_000, T + 2)
        if score_answer(correct=True, elapsed_ms=e, time_limit_ms=T) != _exact_points(e, T)
    ]
    assert mismatches == []
