# AI-ASSISTED: the integer scoring rule of docs/spec/domain.md §4.
"""Points for one answer, in exact integer arithmetic.

A correct answer at elapsed time ``e`` (ms) under the limit ``T`` scores
``100 + (50 * (T - e)) // T``. A wrong answer or a late one (``e > T``) scores 0.
A negative ``e`` (the server clock stepped back) counts as 0. The float form
``50 * (1 - e / T)`` is never used: it rounds ``e / T`` first and gives 132 at
``e = 6800``, ``T = 20000``.
"""

DEFAULT_TIME_LIMIT_MS = 20_000
BASE_POINTS = 100
MAX_SPEED_BONUS = 50


def score_answer(*, correct: bool, elapsed_ms: int, time_limit_ms: int) -> int:
    """Return the points (0 or 100-150) for a player's first answer to a question."""
    if time_limit_ms <= 0:
        msg = f"time_limit_ms must be positive, got {time_limit_ms}"
        raise ValueError(msg)
    elapsed_ms = max(0, elapsed_ms)
    if not correct or elapsed_ms > time_limit_ms:
        return 0
    return BASE_POINTS + (MAX_SPEED_BONUS * (time_limit_ms - elapsed_ms)) // time_limit_ms
