# AI-ASSISTED: the store and feed ports of docs/spec/redis.md §3 and §5; both stores implement them.
"""The quiz store: every write that changes quiz state, behind one interface.

The store reads its own clock and computes points itself: no method takes a time or
points from the caller. Refusals raise ``DomainError`` and write nothing; a ``QUIZ_ENDED``
refusal carries ``end_seq``, None while no ``quiz_ended`` was published yet.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol

from quiz.contracts.messages import FULL_LIST_MAX, TOP_N, Entry
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.events import AnswerScored
from quiz.domain.session import Question


@dataclass(frozen=True, slots=True)
class Limits:
    """The standings policy a store applies; the composition root fills it from the settings."""

    tick_ms: int = 200  # the tick token's life: at most one leaderboard per quiz per tick
    top_n: int = TOP_N  # the entries of a frame above full_list_max players
    full_list_max: int = FULL_LIST_MAX  # up to this many players, a frame carries everyone


@dataclass(frozen=True, slots=True)
class Created:
    start_ms: int
    deadline_ms: int


@dataclass(frozen=True, slots=True)
class Joined:
    at_seq: int
    cursor: int
    cursor_open: bool
    finished: bool
    total: int
    question_count: int
    time_limit_ms: int
    quiz_remaining_ms: int
    display_name: str  # the stored name: a rejoin keeps the first join's name
    replaced_conn_id: str | None  # the older connection of this user, now replaced


@dataclass(frozen=True, slots=True)
class Served:
    at_seq: int
    question_index: int
    question_id: str
    remaining_ms: int


@dataclass(frozen=True, slots=True)
class Finished:
    at_seq: int
    total: int
    rank: int
    player_count: int


@dataclass(frozen=True, slots=True)
class Answered:
    result: AnswerScored  # a replay returns the stored result unchanged
    step_back: bool  # the clock stepped back since the serve; never stored
    replay: bool  # the stored result of an earlier scoring of this submissionId


@dataclass(frozen=True, slots=True)
class Row:
    rank: int
    user_id: str
    display_name: str
    score: int

    def entry(self) -> Entry:
        return Entry(
            rank=self.rank, userId=self.user_id, displayName=self.display_name, score=self.score
        )


@dataclass(frozen=True, slots=True)
class Page:
    at_seq: int
    player_count: int
    final: bool
    rows: tuple[Row, ...]


@dataclass(frozen=True, slots=True)
class Ranks:
    at_seq: int
    status: Literal["open", "ended"]
    player_count: int
    rows: Mapping[str, Row | None]  # per asked user id; None if that user is not a player


@dataclass(frozen=True, slots=True)
class Snapshot:
    at_seq: int
    status: Literal["open", "ended"]
    player_count: int
    online_count: int
    rows: tuple[Row, ...]  # every player up to full_list_max, else the top_n
    you: Row | None


@dataclass(frozen=True, slots=True)
class Publish:
    status: Literal["published", "clean", "busy", "ended"]
    seq: int | None = None  # published: the new seq; ended: the end seq, if announced
    retry_ms: int = 0  # busy: how long the tick token still holds


@dataclass(frozen=True, slots=True)
class Renewed:
    status: Literal["renewed", "ended"]
    removed: int = 0  # renewed: how many stale presence entries were dropped


@dataclass(frozen=True, slots=True)
class End:
    status: Literal["marked", "ended", "not_due"]
    seq: int | None = None  # ended: the seq of quiz_ended


def announced(end: End) -> int:
    """The seq of ``quiz_ended`` after a host end; anything else is an ``UNAVAILABLE`` refusal."""
    if end.status != "ended" or end.seq is None:  # the mark was lost: the host retries
        raise DomainError(ErrorCode.UNAVAILABLE, "the end was not announced; retry")
    return end.seq


class Store(Protocol):
    async def create_quiz(
        self, quiz_id: str, questions: tuple[Question, ...], *, window_ms: int, time_limit_ms: int
    ) -> Created: ...

    async def join(self, quiz_id: str, user_id: str, display_name: str, conn_id: str) -> Joined: ...

    async def leave(self, quiz_id: str, user_id: str, conn_id: str) -> bool:
        """Remove the presence only if ``conn_id`` still holds it; False when stale."""
        ...

    async def serve_next(
        self, quiz_id: str, user_id: str, question_index: int, conn_id: str
    ) -> Served | Finished: ...

    async def apply_answer(  # noqa: PLR0913, PLR0917 - the answer message's fields plus the fence
        self,
        quiz_id: str,
        user_id: str,
        question_index: int,
        choice_index: int,
        submission_id: str,
        conn_id: str,
    ) -> Answered: ...

    async def standings_page(self, quiz_id: str, offset: int, limit: int) -> Page: ...

    async def read_seq(self, quiz_id: str) -> int | None:
        """The quiz's ``seq`` counter, a plain read; None when the quiz is unknown."""
        ...

    async def ranks_of(self, quiz_id: str, user_ids: Sequence[str]) -> Ranks:
        """The rank and score of each user, read at the same seq as ``at_seq``."""
        ...

    async def snapshot(self, quiz_id: str, user_id: str | None) -> Snapshot: ...

    async def publish_if_dirty(self, quiz_id: str, node_id: str) -> Publish:
        """Broadcast one leaderboard frame if the standings changed and no tick holds."""
        ...

    async def end_quiz(self, quiz_id: str, reason: Literal["deadline", "host"]) -> End:
        """Announce the end once; a first host call only marks it (docs/spec/redis.md §3.1)."""
        ...

    async def end_by_host(self, quiz_id: str) -> int:
        """The host's "end now": mark, wait for the mark to be durable, announce; the end seq.

        Raises ``DomainError(UNAVAILABLE)`` when the mark is not durable or the end is not
        announced; nothing is announced then, and a retry is safe (redis.md §3.1 step 3)."""
        ...

    async def renew_presence(
        self, quiz_id: str, stale_ms: int, pairs: Sequence[tuple[str, str]]
    ) -> Renewed:
        """Renew each (user id, connection id) still held; drop entries unseen for ``stale_ms``."""
        ...

    async def mark_dirty(self, quiz_id: str) -> None:
        """Make the next tick publish, as after a Redis restart (docs/spec/redis.md §5)."""
        ...


class Feed(Protocol):
    def subscribe(self, quiz_id: str) -> AbstractAsyncContextManager[AsyncIterator[str]]:
        """The quiz's broadcasts as published, ``{"frame": …, "ranks": [[uid, rank, score], …]}``,
        and, from a store shared by several nodes, its control messages
        ``{"type": "session_replaced", "uid": …, "connId": …}``.

        Subscribed once entered: every later broadcast arrives, in ``seq`` order. The quiz need
        not exist yet: its broadcasts arrive once it is created. Read the iterator in the task
        that entered; leaving the context closes it, so a later read ends the iteration. The
        iterator raises ``ConnectionError`` once the subscription dropped, even if the client
        reconnected on its own: the broadcasts published meanwhile are lost.
        """
        ...


class FeedStore(Store, Feed, Protocol):
    """A store that also delivers its quiz broadcasts: what the fan-out runs on."""

    limits: Limits
