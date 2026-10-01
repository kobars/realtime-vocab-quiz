# AI-ASSISTED: the quiz key schema of docs/spec/redis.md §2, built in one place.
"""Every Redis key and channel of one quiz, in the fixed order the scripts read as KEYS."""

from typing import NamedTuple

QUIZ_TTL_MS = 24 * 60 * 60 * 1000  # the TTL that every write script sets on the data keys


class QuizKeys(NamedTuple):
    meta: str
    key: str
    names: str
    present: str
    totals: str
    board: str
    serve: str
    subs: str
    answered: str
    seq: str
    dirty: str
    scored: str
    tick: str
    events: str  # pub/sub channel, not a key: it has no TTL
    control: str  # pub/sub channel, not a key: it has no TTL


# The fields that refresh() leaves alone: the tick token keeps its own 200 ms expiry.
NO_QUIZ_TTL = frozenset({"tick", "events", "control"})


def quiz_keys(quiz_id: str, prefix: str = "") -> QuizKeys:
    """Build ``<prefix>quiz:{<quiz_id>}:<name>``; the braces keep a quiz in one cluster slot."""
    return QuizKeys(*(f"{prefix}quiz:{{{quiz_id}}}:{name}" for name in QuizKeys._fields))
