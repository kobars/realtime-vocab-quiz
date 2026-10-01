# AI-ASSISTED: the self-paced session state machine of docs/spec/domain.md §3 and §5.
"""All quiz rules in one pure ``transition(state, command, now)``; ``now`` is the only clock."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import NamedTuple, assert_never

from quiz.domain import events as ev
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.scoring import DEFAULT_TIME_LIMIT_MS, score_answer
from quiz.domain.standings import RankedStanding, Standing, record_points, standings

MAX_WINDOW_MS = 60 * 60 * 1000


@dataclass(frozen=True, slots=True)
class Question:
    question_id: str
    correct_choice: int


@dataclass(frozen=True, slots=True)
class Player:
    standing: Standing
    cursor: int = -1  # the last served question index
    serve_ms: int = 0
    cursor_open: bool = False
    finished: bool = False
    results: Mapping[str, ev.AnswerScored] = field(default_factory=dict)  # by submission id


@dataclass(frozen=True, slots=True)
class QuizState:
    questions: tuple[Question, ...]
    start_ms: int
    deadline_ms: int
    time_limit_ms: int = DEFAULT_TIME_LIMIT_MS
    players: Mapping[str, Player] = field(default_factory=dict)
    seq: int = 0  # the last broadcast seq
    dirty: bool = False  # the standings changed since the last broadcast
    ended_ms: int | None = None  # set once, when quiz_ended is broadcast

    def is_open(self, now: int) -> bool:
        return self.ended_ms is None and now < self.deadline_ms


def new_quiz(
    questions: Iterable[Question],
    *,
    start_ms: int,
    window_ms: int,
    time_limit_ms: int = DEFAULT_TIME_LIMIT_MS,
) -> QuizState:
    items = tuple(questions)
    if not items or not 0 < window_ms <= MAX_WINDOW_MS or time_limit_ms <= 0:
        msg = f"invalid quiz: {len(items)} questions, window {window_ms}, limit {time_limit_ms}"
        raise ValueError(msg)
    return QuizState(items, start_ms, start_ms + window_ms, time_limit_ms)


@dataclass(frozen=True, slots=True)
class Join:
    user_id: str


@dataclass(frozen=True, slots=True)
class ServeNext:
    user_id: str
    question_index: int


@dataclass(frozen=True, slots=True)
class Answer:
    user_id: str
    question_index: int
    choice_index: int
    submission_id: str


@dataclass(frozen=True, slots=True)
class End:
    """The host's "end now"; a no-op once the quiz has ended."""


@dataclass(frozen=True, slots=True)
class Tick:
    """One standings frame if they changed; ends the quiz once the deadline has passed."""


type Command = Join | ServeNext | Answer | End | Tick
type Reply = Player | ev.Event | None


class Step(NamedTuple):
    state: QuizState
    events: tuple[ev.Event, ...]
    reply: Reply


def transition(state: QuizState, command: Command, now: int) -> Step:
    match command:
        case Join():
            return _join(state, command.user_id, now)
        case ServeNext():
            return _serve_next(state, command, now)
        case Answer():
            return _answer(state, command, now)
        case End() | Tick():
            return _broadcast(state, now, end=isinstance(command, End))
        case _:
            assert_never(command)


def _player(state: QuizState, user_id: str) -> Player:
    if (player := state.players.get(user_id)) is None:
        raise DomainError(ErrorCode.NOT_JOINED, f"{user_id} has not joined")
    return player


def _require_open(state: QuizState, now: int) -> None:
    if not state.is_open(now):
        raise DomainError(ErrorCode.QUIZ_ENDED, "the quiz has ended")


def _with_player(state: QuizState, player: Player, *, dirty: bool) -> QuizState:
    players = {**state.players, player.standing.user_id: player}
    return replace(state, players=players, dirty=state.dirty or dirty)


def _join(state: QuizState, user_id: str, now: int) -> Step:
    _require_open(state, now)
    if (player := state.players.get(user_id)) is not None:  # a reconnect
        return Step(state, (), player)
    player = Player(Standing(user_id, total=0, reached_rel_ms=max(0, now - state.start_ms)))
    joined = ev.ParticipantJoined(user_id, now)
    return Step(_with_player(state, player, dirty=True), (joined,), player)


def _served(state: QuizState, player: Player, now: int) -> ev.QuestionServed:
    i, end = player.cursor, min(player.serve_ms + state.time_limit_ms, state.deadline_ms)
    question_id, remaining_ms = state.questions[i].question_id, max(0, end - now)
    return ev.QuestionServed(player.standing.user_id, i, question_id, player.serve_ms, remaining_ms)


def _serve_next(state: QuizState, command: ServeNext, now: int) -> Step:
    player = _player(state, command.user_id)
    _require_open(state, now)
    i, n, user_id = command.question_index, len(state.questions), command.user_id
    if player.finished and i == n:  # a repeat of the finishing request
        return Step(state, (), ev.PlayerFinished(user_id, player.standing.total))
    if i == player.cursor >= 0:  # a retry of the serve: the stored serve time
        return Step(state, (), _served(state, player, now))
    if i != n and (i != player.cursor + 1 or player.finished):  # i = N: finish from any cursor
        raise DomainError(ErrorCode.INVALID_STATE, f"next {i} with cursor {player.cursor}")
    events: list[ev.Event] = []
    if player.cursor_open:
        events.append(ev.QuestionSkipped(user_id, player.cursor))
    reply: ev.PlayerFinished | ev.QuestionServed
    if i == n:
        player = replace(player, cursor_open=False, finished=True)
        reply = ev.PlayerFinished(user_id, player.standing.total)
    else:
        player = replace(player, cursor=i, serve_ms=now, cursor_open=True)
        reply = _served(state, player, now)
    events.append(reply)
    return Step(_with_player(state, player, dirty=False), tuple(events), reply)


def _answer(state: QuizState, command: Answer, now: int) -> Step:
    player = _player(state, command.user_id)
    i, user_id, sid = command.question_index, command.user_id, command.submission_id
    if (stored := player.results.get(sid)) is not None:  # idempotency layer 1
        if stored.question_index == i:
            return Step(state, (), stored)
        raise DomainError(ErrorCode.INVALID_MESSAGE, "submissionId reused for another question")
    _require_open(state, now)
    if not 0 <= i <= player.cursor:
        raise DomainError(ErrorCode.QUESTION_NOT_OPEN, f"question {i} was not served")
    if i < player.cursor or not player.cursor_open:  # idempotency layer 2
        raise DomainError(ErrorCode.ALREADY_ANSWERED, f"question {i} is closed")
    elapsed = max(0, now - player.serve_ms)
    question, choice = state.questions[i], command.choice_index
    correct = choice == question.correct_choice
    points = score_answer(correct=correct, elapsed_ms=elapsed, time_limit_ms=state.time_limit_ms)
    standing = record_points(player.standing, points=points, at_rel_ms=now - state.start_ms)
    total, late = standing.total, elapsed > state.time_limit_ms
    result = ev.AnswerScored(
        user_id, i, sid, choice, question.correct_choice, correct, late, points, total, state.seq
    )
    finished = i == len(state.questions) - 1
    results = {**player.results, sid: result}
    player = replace(
        player, standing=standing, cursor_open=False, finished=finished, results=results
    )
    events: tuple[ev.Event, ...] = (result,)
    if finished:
        events += (ev.PlayerFinished(user_id, total),)
    return Step(_with_player(state, player, dirty=points > 0), events, result)


def _ranked(state: QuizState) -> tuple[RankedStanding, ...]:
    return tuple(standings(player.standing for player in state.players.values()))


def _broadcast(state: QuizState, now: int, *, end: bool) -> Step:
    if state.ended_ms is not None:  # quiz_ended was the last broadcast
        return Step(state, (), None)
    seq = state.seq + 1
    if end or not state.is_open(now):
        ended = ev.QuizEnded(seq, min(now, state.deadline_ms), _ranked(state))
        return Step(replace(state, seq=seq, dirty=False, ended_ms=ended.at_ms), (ended,), ended)
    if not state.dirty:
        return Step(state, (), None)
    frame = ev.StandingsBroadcast(seq, _ranked(state))
    return Step(replace(state, seq=seq, dirty=False), (frame,), frame)
