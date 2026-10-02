# AI-ASSISTED: the use cases of docs/spec/protocol.md §2.1: message in, store calls, replies out.
"""One handler per client message type, with no transport; replies are unicasts only.

``DomainError`` keeps its code, a store's ``ConnectionError`` or ``TimeoutError`` is
``UNAVAILABLE``, anything else ``INTERNAL`` with a reference that the log line repeats."""

import asyncio
import logging
import unicodedata
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from quiz.contracts import messages as m
from quiz.domain.errors import DomainError, ErrorCode
from quiz.obs import metrics
from quiz.ports.clock import Clock
from quiz.ports.questions import QuestionBank
from quiz.ports.store import Finished, Joined, Limits, Place, Ranks, Store
from quiz.ports.store import Snapshot as Shared

log = logging.getLogger(__name__)

RESYNC_INTERVAL_MS, NAME_MAX = 1_000, 32
STANDINGS_TRIES = 3  # a tick or a join between the two reads of ``standings`` makes them differ
type Standing = tuple[m.Snapshot] | tuple[m.Snapshot, m.RankUpdate]
OUTAGE_LOG_INTERVAL_MS = 1_000  # at most one store outage line per interval; the counter has all
CLOSE_INTERNAL, CLOSE_REPLACED = 1011, 4001


@dataclass(slots=True)
class Connection:  # what one socket knows: its user (from the ticket) and its quiz
    conn_id: str
    user_id: str
    quiz_id: str | None = None  # the quiz of the first successful join
    read_only: bool = False  # joined after the end: pages and resync only
    present: bool = False  # joined while open: holds the presence that its leave removes
    time_limit_ms: int = 0
    last_resync_ms: int | None = None
    bank_quiz_id: str | None = None  # the bank quiz it plays, read before the first serve


@dataclass(frozen=True, slots=True)
class Outcome:
    replies: tuple[m.ServerMessage, ...] = ()
    replaced_conn_id: str | None = None  # the user's older socket: SESSION_REPLACED, close 4001
    close_code: int | None = None


class Refused(Exception):  # noqa: N818 - a reply, not a fault
    def __init__(self, code: m.ErrorCode, text: str) -> None:
        super().__init__(text)
        self.code = code


def _error(code: m.ErrorCode, text: str, request_type: str) -> m.ProtocolError:
    return m.ProtocolError(code=code, message=text, requestType=request_type)


def _key(read: Shared | Ranks) -> tuple[int, str, int]:
    """What the cached standings are keyed by: a join moves no ``seq``, so the count is in it."""
    return read.at_seq, read.status, read.player_count


def _message(shared: Shared, you: Place | None) -> m.Snapshot:
    return m.Snapshot(
        atSeq=shared.at_seq,
        status=shared.status,
        playerCount=shared.player_count,
        onlineCount=shared.online_count,
        entries=[row.entry() for row in shared.rows],
        you=None if you is None else m.You(rank=you.rank, score=you.score),
    )


def _standing(snap: m.Snapshot) -> Standing:
    """The snapshot, then ``rank_update`` when the player is outside its entries (§4)."""
    you, count = snap.you, snap.playerCount
    if you is None or you.rank <= len(snap.entries):  # the store's limits cut the entries
        return (snap,)
    return (snap, m.RankUpdate(atSeq=snap.atSeq, rank=you.rank, score=you.score, playerCount=count))


async def _share[K, T](
    reads: dict[K, asyncio.Task[T]], key: K, read: Callable[[], Coroutine[Any, Any, T]]
) -> T:
    """Run ``read`` once for all concurrent callers with ``key``; a cancelled caller leaves it."""
    if (task := reads.get(key)) is None:
        task = reads[key] = asyncio.create_task(read())

        def forget(done: asyncio.Task[T]) -> None:
            if reads.get(key) is done:
                del reads[key]
            if not done.cancelled():
                done.exception()  # retrieved even when every waiter was cancelled

        task.add_done_callback(forget)
    return await asyncio.shield(task)


def _bound(conn: Connection, *, write: bool = False) -> str:
    if conn.quiz_id is None:
        raise Refused(m.ErrorCode.NOT_JOINED, "send join first")
    if write and conn.read_only:
        raise Refused(m.ErrorCode.QUIZ_ENDED, "the quiz has ended")
    return conn.quiz_id


type PageKey = tuple[str, int, int]  # quiz id, offset, limit


class QuizService:
    def __init__(
        self, store: Store, bank: QuestionBank, clock: Clock, *, tick_ms: int = Limits().tick_ms
    ) -> None:
        self._store, self._bank, self._clock, self._tick_ms = store, bank, clock, tick_ms
        self._shared: dict[str, Shared] = {}  # per quiz: the standings at its latest seq
        self._refills: dict[str, asyncio.Task[Shared]] = {}  # per quiz: the read in flight
        self._outage_logged_ms: int | None = None
        self._pages: dict[PageKey, tuple[int, m.LeaderboardPage]] = {}  # (expires at ms, page)
        self._page_reads: dict[PageKey, asyncio.Task[m.LeaderboardPage]] = {}

    def drop_cache(self, quiz_id: str | None = None) -> None:
        """Forget the cached standings and pages of one quiz, or of all, and the reads in flight.

        A store restart can lose writes without moving ``seq``, so the reconnect and
        resubscribe path calls this before it sends its repair snapshots (redis.md §5).
        """
        if quiz_id is None:
            self._shared.clear()
            self._refills.clear()
        else:
            self._shared.pop(quiz_id, None)
            self._refills.pop(quiz_id, None)
        self._drop_pages(quiz_id)

    def _drop_pages(self, quiz_id: str | None) -> None:
        for cache in (self._pages, self._page_reads):
            for key in [key for key in cache if quiz_id in {None, key[0]}]:
                del cache[key]

    async def _write[T](self, quiz_id: str, call: Awaitable[T]) -> T:
        """Run a store write; its refusal at the deadline announces the end (redis.md §3.1).

        Before the deadline the refusal comes from a host mark that may not be durable yet,
        so it is ``UNAVAILABLE``, which clients retry, never the final ``QUIZ_ENDED``."""
        try:
            return await call
        except DomainError as error:
            if error.code is not ErrorCode.QUIZ_ENDED:
                raise
            if error.end_seq is None:
                end = await self._store.end_quiz(quiz_id, "deadline")
                if end.status == "not_due":
                    text = "the end is being confirmed"
                    raise DomainError(ErrorCode.UNAVAILABLE, text) from error
            self._drop_pages(quiz_id)  # the cached pages are not final: read them again
            raise

    async def handle(self, conn: Connection, msg: m.ClientMessage) -> Outcome:
        outcome = await self._handle(conn, msg)
        for reply in outcome.replies:
            if isinstance(reply, m.ProtocolError):
                metrics.WS_ERRORS.labels(msg.type, reply.code.value).inc()
        return outcome

    async def _handle(self, conn: Connection, msg: m.ClientMessage) -> Outcome:
        kind = msg.type
        try:
            out = await getattr(self, f"_on_{kind}")(conn, msg)
        except DomainError as error:
            code = m.ErrorCode(error.code.value)
            close = CLOSE_REPLACED if code is m.ErrorCode.SESSION_REPLACED else None
            return Outcome((_error(code, str(error), kind),), close_code=close)
        except Refused as error:
            return Outcome((_error(error.code, str(error), kind),))
        except ConnectionError, TimeoutError:
            now = self._clock()
            last = self._outage_logged_ms
            if last is None or now - last >= OUTAGE_LOG_INTERVAL_MS:
                self._outage_logged_ms = now
                log.warning("store unreachable on %s", kind, exc_info=True)
            return Outcome((_error(m.ErrorCode.UNAVAILABLE, "the store is unreachable", kind),))
        except Exception:
            ref = uuid.uuid4().hex[:12]
            log.exception("internal error on %s, ref %s", kind, ref)
            reply = _error(m.ErrorCode.INTERNAL, f"internal error, ref {ref}", kind)
            return Outcome((reply,), close_code=CLOSE_INTERNAL)
        return out if isinstance(out, Outcome) else Outcome((out,))

    async def _on_join(self, conn: Connection, msg: m.Join) -> Outcome:
        name, quiz_id = unicodedata.normalize("NFC", msg.displayName.strip()), msg.quizId
        if not 1 <= len(name) <= NAME_MAX:
            raise Refused(m.ErrorCode.INVALID_MESSAGE, f"displayName must be 1-{NAME_MAX} chars")
        if conn.quiz_id not in {None, quiz_id}:
            raise Refused(m.ErrorCode.INVALID_STATE, f"this socket serves {conn.quiz_id}")
        if (j := None if conn.read_only else await self._join(conn, quiz_id, name)) is None:
            snapshot = await self.snapshot(quiz_id, conn.user_id)
            conn.quiz_id, conn.read_only = quiz_id, True
            return Outcome((snapshot, _error(m.ErrorCode.QUIZ_ENDED, "the quiz has ended", "join")))
        conn.quiz_id, conn.time_limit_ms, conn.present = quiz_id, j.time_limit_ms, True
        reply = m.Joined(
            atSeq=j.at_seq,
            quizId=quiz_id,
            userId=conn.user_id,
            displayName=j.display_name,
            questionCount=j.question_count,
            timeLimitMs=j.time_limit_ms,
            quizRemainingMs=j.quiz_remaining_ms,
            cursor=j.cursor,
            cursorOpen=j.cursor_open,
            finished=j.finished,
            score=j.total,
        )
        return Outcome((reply,), replaced_conn_id=j.replaced_conn_id)

    async def _join(self, conn: Connection, quiz_id: str, name: str) -> Joined | None:
        try:
            return await self._write(
                quiz_id, self._store.join(quiz_id, conn.user_id, name, conn.conn_id)
            )
        except DomainError as error:
            if error.code is ErrorCode.QUIZ_ENDED:
                return None  # answered with the final snapshot
            raise

    async def _on_next(self, conn: Connection, msg: m.Next) -> m.ServerMessage:
        quiz_id = _bound(conn, write=True)
        if conn.bank_quiz_id is None:  # before the serve: a failed read must not start its timer
            conn.bank_quiz_id = await self._store.bank_quiz_id(quiz_id)
        serve = self._store.serve_next(quiz_id, conn.user_id, msg.questionIndex, conn.conn_id)
        s = await self._write(quiz_id, serve)
        if isinstance(s, Finished):
            return m.Finished(
                atSeq=s.at_seq, score=s.total, rank=s.rank, playerCount=s.player_count
            )
        if (questions := await self._bank.questions(conn.bank_quiz_id)) is None:
            text = f"the question bank has no quiz {conn.bank_quiz_id}"
            raise LookupError(text)
        q = questions[s.question_index]
        return m.Question(
            atSeq=s.at_seq,
            questionIndex=s.question_index,
            questionId=s.question_id,
            prompt=q.prompt,
            choices=list(q.choices),
            timeLimitMs=conn.time_limit_ms,
            remainingMs=s.remaining_ms,
        )

    async def _on_answer(self, conn: Connection, msg: m.Answer) -> m.ServerMessage:
        # Even read only: a stored submissionId replays, a new one gets QUIZ_ENDED (domain §5.2).
        quiz_id, user_id = _bound(conn), conn.user_id
        answer = (msg.questionIndex, msg.choiceIndex, msg.submissionId)
        apply = self._store.apply_answer(quiz_id, user_id, *answer, conn.conn_id)
        answered = await self._write(quiz_id, apply)
        if answered.step_back:  # never set on a replay, so each step counts once
            metrics.REDIS_CLOCK_STEP.inc()
        r = answered.result
        if not answered.replay:
            metrics.ANSWERS.labels("late" if r.late else "correct" if r.correct else "wrong").inc()
        return m.AnswerResult(
            atSeq=r.at_seq,
            questionIndex=r.question_index,
            submissionId=r.submission_id,
            choiceIndex=r.choice_index,
            correctChoiceIndex=r.correct_choice,
            correct=r.correct,
            late=r.late,
            pointsAwarded=r.points,
            score=r.total,
        )

    async def _on_ping(self, conn: Connection, msg: m.Ping) -> m.ServerMessage:
        del msg
        try:
            seq = None if conn.quiz_id is None else await self._store.read_seq(conn.quiz_id)
        except ConnectionError, TimeoutError:
            seq = None
        return m.Pong(seq=seq)

    async def _on_resync(self, conn: Connection, msg: m.Resync) -> Outcome:
        del msg  # lastSeq only says what the client had: the reply is always a full snapshot
        quiz_id, now = _bound(conn), self._clock()
        if conn.last_resync_ms is not None and now - conn.last_resync_ms < RESYNC_INTERVAL_MS:
            raise Refused(m.ErrorCode.RATE_LIMITED, "at most one resync per second")
        conn.last_resync_ms = now
        standing = await self.standing(quiz_id, conn.user_id)
        metrics.RESYNCS.inc()
        return Outcome(standing)

    async def standing(self, quiz_id: str, user_id: str) -> Standing:
        return _standing(await self.snapshot(quiz_id, user_id))

    async def standings(
        self, quiz_id: str, user_ids: Sequence[str]
    ) -> tuple[Ranks, dict[str, Standing]]:
        """The ``standing`` of each user, all at the seq of one rank read for all of them."""
        if (read := await self._at_one_key(quiz_id, user_ids)) is None:
            msg = "the standings moved during every read"
            raise ConnectionError(msg)
        ranks, shared = read
        return ranks, {user: _standing(_message(shared, row)) for user, row in ranks.rows.items()}

    async def _at_one_key(
        self, quiz_id: str, user_ids: Sequence[str]
    ) -> tuple[Ranks, Shared] | None:
        """A row-less rank read of ``user_ids`` and the cached standings at its key.

        The rank read gives the key; a miss refills the standings, shared by concurrent
        misses. A tick or a join between the two reads makes them differ: then both are
        read again, up to ``STANDINGS_TRIES`` times, else None."""
        for _ in range(STANDINGS_TRIES):
            ranks = await self._store.ranks_of(quiz_id, user_ids)
            shared = self._shared.get(quiz_id)
            if shared is None or _key(shared) != _key(ranks):
                shared = await self._refill(quiz_id)
            if _key(shared) == _key(ranks):
                return ranks, shared
        return None

    async def _on_get_leaderboard(self, conn: Connection, msg: m.GetLeaderboard) -> m.ServerMessage:
        """One page per (quiz, offset, limit) for one tick, shared by every viewer of it."""
        key, now = (_bound(conn), msg.offset, msg.limit), self._clock()
        if (cached := self._pages.get(key)) is not None and now < cached[0]:
            return cached[1]
        return await _share(self._page_reads, key, partial(self._read_page, key, now))

    async def _read_page(self, key: PageKey, now: int) -> m.LeaderboardPage:
        """Read the page and cache it, unless the quiz's pages were dropped during the read."""
        read = asyncio.current_task()
        page = await self._store.standings_page(*key)
        reply = m.LeaderboardPage(
            atSeq=page.at_seq,
            offset=key[1],
            playerCount=page.player_count,
            final=page.final,
            entries=[row.entry() for row in page.rows],
        )
        if self._page_reads.get(key) is read:
            for stale in [k for k, (expires_ms, _) in self._pages.items() if expires_ms <= now]:
                del self._pages[stale]
            self._pages[key] = (now + self._tick_ms, reply)
        return reply

    async def _refill(self, quiz_id: str) -> Shared:
        """Read the cached standings again; concurrent misses of one quiz share one read."""
        read = partial(self._store.snapshot, quiz_id, None)
        shared = self._shared[quiz_id] = await _share(self._refills, quiz_id, read)
        return shared

    async def snapshot(self, quiz_id: str, user_id: str | None) -> m.Snapshot:
        """The standings cached per (quiz, seq, status, player count); the own row read fresh.

        When the two never meet at one key, one full read with the user returns both."""
        if (read := await self._at_one_key(quiz_id, () if user_id is None else (user_id,))) is None:
            full = self._shared[quiz_id] = await self._store.snapshot(quiz_id, user_id)
            return _message(full, full.you)
        ranks, shared = read
        return _message(shared, next(iter(ranks.rows.values()), None))
