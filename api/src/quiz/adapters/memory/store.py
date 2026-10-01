# AI-ASSISTED: the in-memory store: the domain state machine behind the store and feed ports.
"""The Redis store's single-process twin: per quiz, one lock, one clock read per command."""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Literal

from quiz.contracts import messages as m
from quiz.contracts.codec import encode_broadcast
from quiz.contracts.messages import FULL_LIST_MAX
from quiz.domain import events as ev
from quiz.domain import session as s
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.standings import standings
from quiz.ports import store as port
from quiz.ports.clock import Clock
from quiz.ports.store import Answered, Created, Finished, Joined, Limits, Row, Served

MAX_QUESTIONS, CHOICES = 100, 4


@dataclass(slots=True)
class _Quiz:
    state: s.QuizState
    deadline_ms: int  # as created; a host mark moves only state.deadline_ms
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    names: dict[str, str] = field(default_factory=dict)
    present: dict[str, str] = field(default_factory=dict)  # user id -> connection id
    replaced: set[str] = field(default_factory=set)  # connection ids a newer join took over
    tick_until_ms: int = 0  # the tick token, limits.tick_ms long
    end_seq: int | None = None  # the seq of quiz_ended, once announced
    scored: set[str] = field(default_factory=set)  # who scored since the last broadcast

    def fence(self, user_id: str, conn_id: str) -> None:
        if (held := self.present.get(user_id)) is None:
            raise DomainError(ErrorCode.NOT_JOINED, f"{user_id} is not present")
        if held != conn_id:
            raise DomainError(ErrorCode.SESSION_REPLACED, f"{conn_id} was replaced")

    def rows(self) -> list[Row]:
        ranked = standings(player.standing for player in self.state.players.values())
        return [
            Row(r.rank, r.standing.user_id, self.names[r.standing.user_id], r.standing.total)
            for r in ranked
        ]


async def _drain(feed: asyncio.Queue[str]) -> AsyncGenerator[str]:
    while True:
        yield await feed.get()


class MemoryStore:
    def __init__(self, clock: Clock, limits: Limits | None = None) -> None:
        self._clock = clock
        self.limits = limits or Limits()
        self._quizzes: dict[str, _Quiz] = {}
        self._feeds: dict[str, set[asyncio.Queue[str]]] = {}  # per quiz id, one per subscriber

    def _quiz(self, quiz_id: str) -> _Quiz:
        if (quiz := self._quizzes.get(quiz_id)) is None:
            raise DomainError(ErrorCode.QUIZ_NOT_FOUND, f"no quiz {quiz_id}")
        return quiz

    def _status(self, quiz: _Quiz) -> Literal["open", "ended"]:
        return "open" if quiz.state.is_open(self._clock()) else "ended"

    def _shown(self, rows: list[Row]) -> list[Row]:
        """A frame's entries: every row up to ``full_list_max`` players, else the top N."""
        return rows if len(rows) <= self.limits.full_list_max else rows[: self.limits.top_n]

    def _publish(self, quiz_id: str, frame: m.Broadcast, ranks: list[list[str | int]]) -> None:
        message = f'{{"frame":{encode_broadcast(frame).decode()},"ranks":{json.dumps(ranks)}}}'
        for feed in self._feeds.get(quiz_id, ()):
            feed.put_nowait(message)

    async def create_quiz(
        self, quiz_id: str, questions: tuple[s.Question, ...], *, window_ms: int, time_limit_ms: int
    ) -> Created:
        if quiz_id in self._quizzes:
            raise DomainError(ErrorCode.INVALID_STATE, f"quiz {quiz_id} exists")
        ids = {q.question_id for q in questions}
        if (
            len(ids) != len(questions)
            or len(ids) > MAX_QUESTIONS
            or not all(0 <= q.correct_choice < CHOICES for q in questions)
            or time_limit_ms > s.MAX_WINDOW_MS
        ):
            msg = "need 1-100 unique questions, answers 0-3 and a time limit of at most 60 min"
            raise DomainError(ErrorCode.INVALID_MESSAGE, msg)
        try:
            state = s.new_quiz(
                questions, start_ms=self._clock(), window_ms=window_ms, time_limit_ms=time_limit_ms
            )
        except ValueError as error:
            raise DomainError(ErrorCode.INVALID_MESSAGE, str(error)) from error
        self._quizzes[quiz_id] = _Quiz(state, state.deadline_ms)
        return Created(state.start_ms, state.deadline_ms)

    async def join(self, quiz_id: str, user_id: str, display_name: str, conn_id: str) -> Joined:
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            now = self._clock()
            step = s.transition(quiz.state, s.Join(user_id), now)
            if conn_id in quiz.replaced:
                raise DomainError(ErrorCode.SESSION_REPLACED, f"{conn_id} was replaced")
            player = step.state.players[user_id]
            name = quiz.names.setdefault(user_id, display_name)
            if (replaced := quiz.present.get(user_id)) == conn_id:
                replaced = None  # a repeat join on the same connection replaces nothing
            if replaced is not None:
                quiz.replaced.add(replaced)
            quiz.present[user_id] = conn_id
            quiz.state = state = replace(step.state, dirty=True)  # onlineCount may change
            return Joined(
                state.seq,
                player.cursor,
                player.cursor_open,
                player.finished,
                player.standing.total,
                len(state.questions),
                state.time_limit_ms,
                max(0, state.deadline_ms - now),
                name,
                replaced,
            )

    async def leave(self, quiz_id: str, user_id: str, conn_id: str) -> bool:
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            if quiz.present.get(user_id) != conn_id:
                return False
            del quiz.present[user_id]
            if quiz.state.is_open(self._clock()):
                quiz.state = replace(quiz.state, dirty=True)
            return True

    async def serve_next(
        self, quiz_id: str, user_id: str, question_index: int, conn_id: str
    ) -> Served | Finished:
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            now = self._clock()
            if quiz.state.is_open(now):
                quiz.fence(user_id, conn_id)
            step = s.transition(quiz.state, s.ServeNext(user_id, question_index), now)
            quiz.state, seq = step.state, step.state.seq
            match step.reply:
                case ev.QuestionServed(question_index=i, question_id=qid, remaining_ms=left):
                    return Served(seq, i, qid, left)
                case ev.PlayerFinished(total=total):
                    rows = quiz.rows()
                    rank = next(row.rank for row in rows if row.user_id == user_id)
                    return Finished(seq, total, rank, len(rows))
                case reply:
                    raise TypeError(reply)

    async def apply_answer(  # noqa: PLR0913, PLR0917 - the port's signature
        self,
        quiz_id: str,
        user_id: str,
        question_index: int,
        choice_index: int,
        submission_id: str,
        conn_id: str,
    ) -> Answered:
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            now = self._clock()
            player = quiz.state.players.get(user_id)
            replay = player is not None and submission_id in player.results
            if not replay and quiz.state.is_open(now):
                quiz.fence(user_id, conn_id)
            step_back = not replay and player is not None and now < player.serve_ms
            command = s.Answer(user_id, question_index, choice_index, submission_id)
            step = s.transition(quiz.state, command, now)
            if not isinstance(result := step.reply, ev.AnswerScored):
                raise TypeError(result)
            quiz.state = step.state
            if not replay and result.points > 0:
                quiz.scored.add(user_id)
            return Answered(result, step_back, replay)

    async def read_seq(self, quiz_id: str) -> int | None:
        quiz = self._quizzes.get(quiz_id)
        return None if quiz is None else quiz.state.seq

    async def ranks_of(self, quiz_id: str, user_ids: Sequence[str]) -> port.Ranks:
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            rows = {row.user_id: row for row in quiz.rows()}
            asked = {user_id: rows.get(user_id) for user_id in user_ids}
            return port.Ranks(quiz.state.seq, self._status(quiz), len(rows), asked)

    async def standings_page(self, quiz_id: str, offset: int, limit: int) -> port.Page:
        if offset < 0 or not 1 <= limit <= FULL_LIST_MAX:
            msg = f"page offset {offset}, limit {limit}"
            raise DomainError(ErrorCode.INVALID_MESSAGE, msg)
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            rows, final = quiz.rows(), not quiz.state.is_open(self._clock())
            return port.Page(quiz.state.seq, len(rows), final, tuple(rows[offset : offset + limit]))

    async def snapshot(self, quiz_id: str, user_id: str | None) -> port.Snapshot:
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            rows = quiz.rows()
            you = next((row for row in rows if row.user_id == user_id), None)
            status = self._status(quiz)
            shown = self._shown(rows)
            online = len(quiz.present)
            return port.Snapshot(quiz.state.seq, status, len(rows), online, tuple(shown), you)

    async def publish_if_dirty(self, quiz_id: str, node_id: str) -> port.Publish:
        del node_id  # one process: the tick token needs no owner
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            now = self._clock()
            if not quiz.state.is_open(now):
                return port.Publish("ended", quiz.end_seq)
            tick_ms = self.limits.tick_ms  # a clock step-back never stretches the token past it
            quiz.tick_until_ms = min(quiz.tick_until_ms, now + tick_ms)
            if now < quiz.tick_until_ms:
                return port.Publish("busy", retry_ms=quiz.tick_until_ms - now)
            if not quiz.state.dirty:
                return port.Publish("clean")
            quiz.state = s.transition(quiz.state, s.Tick(), now).state
            quiz.tick_until_ms = now + tick_ms
            rows = quiz.rows()
            shown = self._shown(rows)
            ranks: list[list[str | int]] = [
                [row.user_id, row.rank, row.score]
                for row in rows[len(shown) :]
                if row.user_id in quiz.scored
            ]
            quiz.scored.clear()
            frame = m.Leaderboard(
                seq=quiz.state.seq,
                rebase=False,
                playerCount=len(rows),
                onlineCount=len(quiz.present),
                entries=[row.entry() for row in shown],
            )
            self._publish(quiz_id, frame, ranks)
            return port.Publish("published", quiz.state.seq)

    async def end_quiz(self, quiz_id: str, reason: Literal["deadline", "host"]) -> port.End:
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            now = self._clock()
            if quiz.end_seq is not None:
                return port.End("ended", quiz.end_seq)
            if reason == "deadline" and now < quiz.deadline_ms:
                return port.End("not_due")
            if reason == "host" and not quiz.state.marked:  # refuse writes; announce next call
                deadline_ms = min(now, quiz.state.deadline_ms)
                quiz.state = replace(quiz.state, deadline_ms=deadline_ms, marked=True, dirty=False)
                return port.End("marked")
            quiz.state = s.transition(quiz.state, s.End(), now).state
            quiz.end_seq = quiz.state.seq
            rows = quiz.rows()
            top = [row.entry() for row in rows[: self.limits.top_n]]
            ended = m.QuizEnded(seq=quiz.end_seq, playerCount=len(rows), entries=top, you=None)
            self._publish(quiz_id, ended, [])
            return port.End("ended", quiz.end_seq)

    async def end_by_host(self, quiz_id: str) -> int:
        end = await self.end_quiz(quiz_id, "host")
        if end.status == "marked":  # memory has no fsync to wait for
            end = await self.end_quiz(quiz_id, "host")
        return port.announced(end)

    @asynccontextmanager
    async def subscribe(self, quiz_id: str) -> AsyncIterator[AsyncIterator[str]]:
        feeds, feed = self._feeds.setdefault(quiz_id, set()), asyncio.Queue[str]()
        feeds.add(feed)
        try:
            async with aclosing(_drain(feed)) as messages:
                yield messages
        finally:
            feeds.discard(feed)
            if not feeds:
                del self._feeds[quiz_id]

    async def renew_presence(
        self, quiz_id: str, stale_ms: int, pairs: Sequence[tuple[str, str]]
    ) -> port.Renewed:
        raise NotImplementedError

    async def mark_dirty(self, quiz_id: str) -> None:
        raise NotImplementedError
