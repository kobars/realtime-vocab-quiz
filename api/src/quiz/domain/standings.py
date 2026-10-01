# AI-ASSISTED: the standings order, reached time and sorted-set score of docs/spec/domain.md §6.
"""Leaderboard order with unique ranks, and its Redis sorted-set encoding.

Order: total descending, then ``reached_rel_ms`` ascending (when the player
reached that total, in ms since the quiz start), then ``user_id`` ascending.
The sorted-set score ``(2^30 - total) * 2^22 + reached_rel_ms``, read in
ascending order with ties broken by member (the user id), gives the same order.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace

TOTAL_BITS = 30
REACHED_BITS = 22
MAX_TOTAL = 1 << TOTAL_BITS
MAX_REACHED_REL_MS = (1 << REACHED_BITS) - 1


@dataclass(frozen=True, slots=True)
class Standing:
    user_id: str
    total: int
    reached_rel_ms: int


@dataclass(frozen=True, slots=True)
class RankedStanding:
    rank: int
    standing: Standing


def record_points(standing: Standing, *, points: int, at_rel_ms: int) -> Standing:
    """Add the points of one answer; the reached time moves only when points > 0."""
    if points <= 0:
        return standing
    return replace(standing, total=standing.total + points, reached_rel_ms=max(0, at_rel_ms))


def standings(entries: Iterable[Standing]) -> list[RankedStanding]:
    """Order the players and give each a unique rank, 1..N."""
    rows = list(entries)
    if len({row.user_id for row in rows}) != len(rows):
        msg = "duplicate user_id in standings"
        raise ValueError(msg)
    rows.sort(key=lambda s: (-s.total, s.reached_rel_ms, s.user_id))
    return [RankedStanding(rank, row) for rank, row in enumerate(rows, start=1)]


def encode_sort_score(total: int, reached_rel_ms: int) -> int:
    """Return the sorted-set score; below 2^53, so a double holds it exactly."""
    if not 0 <= total <= MAX_TOTAL or not 0 <= reached_rel_ms <= MAX_REACHED_REL_MS:
        msg = f"total {total} or reached_rel_ms {reached_rel_ms} out of range"
        raise ValueError(msg)
    return ((MAX_TOTAL - total) << REACHED_BITS) + reached_rel_ms


def decode_sort_score(score: int) -> tuple[int, int]:
    """Return ``(total, reached_rel_ms)`` from a sorted-set score."""
    if not 0 <= score <= encode_sort_score(0, MAX_REACHED_REL_MS):
        msg = f"sort score {score} out of range"
        raise ValueError(msg)
    inverted_total, reached_rel_ms = divmod(score, 1 << REACHED_BITS)
    return MAX_TOTAL - inverted_total, reached_rel_ms
