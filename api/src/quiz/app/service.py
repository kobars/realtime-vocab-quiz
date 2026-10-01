# AI-ASSISTED: the use cases of docs/spec/protocol.md §2.1: message in, store calls, replies out.
"""One handler per client message type, with no transport; replies are unicasts only.

``DomainError`` keeps its code, a store's ``ConnectionError`` or ``TimeoutError`` is
``UNAVAILABLE``, anything else ``INTERNAL`` with a reference that the log line repeats."""

import logging
import unicodedata
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass

from quiz.contracts import messages as m
from quiz.domain.errors import DomainError, ErrorCode
from quiz.ports.clock import Clock
from quiz.ports.questions import QuestionBank
from quiz.ports.store import Finished, Joined, Row, Store
from quiz.ports.store import Snapshot as Shared

log = logging.getLogger(__name__)

RESYNC_INTERVAL_MS, NAME_MAX = 1_000, 32
CLOSE_INTERNAL, CLOSE_REPLACED = 1011, 4001


@dataclass(slots=True)
class Connection:  # what one socket knows: its user (from the ticket) and its quiz
    conn_id: str
    user_id: str
    quiz_id: str | None = None  # the quiz of the first successful join
    read_only: bool = False  # joined after the end: pages and resync only
    time_limit_ms: int = 0
    last_resync_ms: int | None = None


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


def _entry(row: Row) -> m.Entry:
    return m.Entry(rank=row.rank, userId=row.user_id, displayName=row.display_name, score=row.score)


def _bound(conn: Connection, *, write: bool = False) -> str:
    if conn.quiz_id is None:
        raise Refused(m.ErrorCode.NOT_JOINED, "send join first")
    if write and conn.read_only:
        raise Refused(m.ErrorCode.QUIZ_ENDED, "the quiz has ended")
    return conn.quiz_id


class QuizService:
    def __init__(self, store: Store, bank: QuestionBank, clock: Clock) -> None:
        self._store, self._bank, self._clock = store, bank, clock
        self._shared: dict[str, Shared] = {}  # per quiz: the standings at its latest seq

    def drop_cache(self, quiz_id: str | None = None) -> None:
        """Forget the cached standings of one quiz, or of all quizzes.

        A store restart can lose writes without moving ``seq``, so the reconnect and
        resubscribe path calls this before it sends its repair snapshots (redis.md §5).
        """
        if quiz_id is None:
            self._shared.clear()
        else:
            self._shared.pop(quiz_id, None)

    async def _write[T](self, quiz_id: str, call: Awaitable[T]) -> T:
        """Run a store write; its refusal at the deadline announces the end (redis.md §3.1)."""
        try:
            return await call
        except DomainError as error:
            if error.code is ErrorCode.QUIZ_ENDED and error.end_seq is None:
                await self._store.end_quiz(quiz_id, "deadline")  # not_due: a host mark only
            raise

    async def handle(self, conn: Connection, msg: m.ClientMessage) -> Outcome:
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
        conn.quiz_id, conn.time_limit_ms = quiz_id, j.time_limit_ms
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
        serve = self._store.serve_next(quiz_id, conn.user_id, msg.questionIndex, conn.conn_id)
        s = await self._write(quiz_id, serve)
        if isinstance(s, Finished):
            return m.Finished(
                atSeq=s.at_seq, score=s.total, rank=s.rank, playerCount=s.player_count
            )
        if (questions := await self._bank.questions(quiz_id)) is None:
            text = f"the question bank has no quiz {quiz_id}"
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
        quiz_id, user_id = _bound(conn, write=True), conn.user_id
        answer = (msg.questionIndex, msg.choiceIndex, msg.submissionId)
        apply = self._store.apply_answer(quiz_id, user_id, *answer, conn.conn_id)
        answered = await self._write(quiz_id, apply)
        r = answered.result
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
        snap = await self.snapshot(quiz_id, conn.user_id)
        you, count = snap.you, snap.playerCount
        if you is None or count <= m.FULL_LIST_MAX or you.rank <= len(snap.entries):
            return Outcome((snap,))  # above 200 players and outside the entries: rank_update (§4)
        update = m.RankUpdate(atSeq=snap.atSeq, rank=you.rank, score=you.score, playerCount=count)
        return Outcome((snap, update))

    async def _on_get_leaderboard(self, conn: Connection, msg: m.GetLeaderboard) -> m.ServerMessage:
        page = await self._store.standings_page(_bound(conn), msg.offset, msg.limit)
        return m.LeaderboardPage(
            atSeq=page.at_seq,
            offset=msg.offset,
            playerCount=page.player_count,
            final=page.final,
            entries=[_entry(row) for row in page.rows],
        )

    async def _head(self, quiz_id: str) -> tuple[int, str, int]:
        page = await self._store.standings_page(quiz_id, 0, 1)
        return page.at_seq, "ended" if page.final else "open", page.player_count

    async def snapshot(self, quiz_id: str, user_id: str | None) -> m.Snapshot:
        """The standings cached per (quiz, seq, status, player count); the own row read fresh.

        A join moves no ``seq``, so the player count is part of the key. If the own row was
        read at another seq or count than the cached part, both are read again together.
        """
        head, shared = await self._head(quiz_id), self._shared.get(quiz_id)
        if shared is None or (shared.at_seq, shared.status, shared.player_count) != head:
            shared = self._shared[quiz_id] = await self._store.snapshot(quiz_id, None)
        users = () if user_id is None else (user_id,)
        ranks = await self._store.ranks_of(quiz_id, users)
        you = next(iter(ranks.rows.values()), None)
        if (ranks.at_seq, ranks.player_count) != (shared.at_seq, shared.player_count):
            shared = self._shared[quiz_id] = await self._store.snapshot(quiz_id, user_id)
            you = shared.you
        return m.Snapshot(
            atSeq=shared.at_seq,
            status=shared.status,
            playerCount=shared.player_count,
            onlineCount=shared.online_count,
            entries=[_entry(row) for row in shared.rows],
            you=None if you is None else m.You(rank=you.rank, score=you.score),
        )
