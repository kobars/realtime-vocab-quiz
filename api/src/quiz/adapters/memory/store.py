# AI-ASSISTED: the in-memory store: the domain state machine behind the store port.
"""The Redis store's single-process twin: per quiz, one lock, one clock read per command."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from quiz.contracts.messages import FULL_LIST_MAX, TOP_N
from quiz.domain import events as ev
from quiz.domain import session as s
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.standings import standings
from quiz.ports import store as port
from quiz.ports.clock import Clock
from quiz.ports.store import Answered, Created, Finished, Joined, Row, Served

MAX_QUESTIONS, CHOICES, TICK_MS = 100, 4, 200


@dataclass(slots=True)
class _Quiz:
    state: s.QuizState
    deadline_ms: int  # as created; a host mark moves only state.deadline_ms
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    names: dict[str, str] = field(default_factory=dict)
    present: dict[str, str] = field(default_factory=dict)  # user id -> connection id
    tick_until_ms: int = 0  # the 200 ms tick token
    marked: bool = False  # a host end refuses writes before it is announced
    end_seq: int | None = None  # the seq of quiz_ended, once announced

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


class MemoryStore:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._quizzes: dict[str, _Quiz] = {}

    def _quiz(self, quiz_id: str) -> _Quiz:
        if (quiz := self._quizzes.get(quiz_id)) is None:
            raise DomainError(ErrorCode.QUIZ_NOT_FOUND, f"no quiz {quiz_id}")
        return quiz

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
            player = step.state.players[user_id]
            quiz.names.setdefault(user_id, display_name)
            replaced = quiz.present.get(user_id)
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
                replaced if replaced != conn_id else None,
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
            return Answered(result, step_back)

    async def ranks_of(self, quiz_id: str, user_ids: Sequence[str]) -> port.Ranks:
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            rows = {row.user_id: row for row in quiz.rows()}
            asked = {user_id: rows.get(user_id) for user_id in user_ids}
            return port.Ranks(quiz.state.seq, len(rows), asked)

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
            status: Literal["open", "ended"] = (
                "open" if quiz.state.is_open(self._clock()) else "ended"
            )
            shown = rows if len(rows) <= FULL_LIST_MAX else rows[:TOP_N]
            online = len(quiz.present)
            return port.Snapshot(quiz.state.seq, status, len(rows), online, tuple(shown), you)

    async def publish_if_dirty(self, quiz_id: str, node_id: str) -> port.Publish:
        del node_id  # one process: the tick token needs no owner
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            now = self._clock()
            if not quiz.state.is_open(now):
                return port.Publish("ended", quiz.end_seq)
            if now < quiz.tick_until_ms:
                return port.Publish("busy", retry_ms=quiz.tick_until_ms - now)
            if not quiz.state.dirty:
                return port.Publish("clean")
            quiz.state = s.transition(quiz.state, s.Tick(), now).state
            quiz.tick_until_ms = now + TICK_MS
            return port.Publish("published", quiz.state.seq)

    async def end_quiz(self, quiz_id: str, reason: Literal["deadline", "host"]) -> port.End:
        quiz = self._quiz(quiz_id)
        async with quiz.lock:
            now = self._clock()
            if quiz.end_seq is not None:
                return port.End("ended", quiz.end_seq)
            if reason == "deadline" and now < quiz.deadline_ms:
                return port.End("not_due")
            if reason == "host" and not quiz.marked:  # refuse writes; announce on the next call
                quiz.marked = True
                deadline_ms = min(now, quiz.state.deadline_ms)
                quiz.state = replace(quiz.state, deadline_ms=deadline_ms, dirty=False)
                return port.End("marked")
            quiz.state = s.transition(quiz.state, s.End(), now).state
            quiz.end_seq = quiz.state.seq
            return port.End("ended", quiz.end_seq)

    async def renew_presence(
        self, quiz_id: str, stale_ms: int, pairs: Sequence[tuple[str, str]]
    ) -> port.Renewed:
        raise NotImplementedError

    async def mark_dirty(self, quiz_id: str) -> None:
        raise NotImplementedError
