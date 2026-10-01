# AI-ASSISTED: example tests of the session state machine against docs/spec/domain.md §3 and §5.
import pytest

from quiz.contracts.messages import ErrorCode as WireErrorCode
from quiz.domain import events as ev
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.session import (
    Answer,
    Command,
    End,
    Join,
    Question,
    QuizState,
    ServeNext,
    Step,
    new_quiz,
    transition,
)

T, START, DEADLINE = 20_000, 1_000, 61_000
QUIZ = new_quiz([Question("q0", 2), Question("q1", 0)], start_ms=START, window_ms=60_000)
SERVED = transition(transition(QUIZ, Join("ann"), START).state, ServeNext("ann", 0), START + 100)


def refused(state: QuizState, command: Command, now: int) -> ErrorCode:
    with pytest.raises(DomainError) as info:
        transition(state, command, now)
    return info.value.code


def test_join_registers_once_and_a_rejoin_writes_nothing() -> None:
    joined = transition(QUIZ, Join("ann"), START + 500)
    assert joined.events == (ev.ParticipantJoined("ann", START + 500),)
    assert joined.state.players["ann"].standing.reached_rel_ms == 500
    assert transition(joined.state, Join("ann"), START + 900) == Step(
        joined.state, (), joined.reply
    )


def test_a_duplicate_next_returns_the_stored_serve_time() -> None:
    assert SERVED.events == (ev.QuestionServed("ann", 0, "q0", START + 100, T),)
    retry = transition(SERVED.state, ServeNext("ann", 0), START + 5_100)
    assert retry == Step(
        SERVED.state, (), ev.QuestionServed("ann", 0, "q0", START + 100, T - 5_000)
    )


def test_a_replay_and_both_idempotency_layers() -> None:
    scored = transition(SERVED.state, Answer("ann", 0, 2, "s1"), START + 6_900)
    result = ev.AnswerScored("ann", 0, "s1", 2, 2, True, False, 133, 133, 0)  # noqa: FBT003
    assert (scored.events, scored.state.players["ann"].standing.total) == ((result,), 133)
    replay = transition(scored.state, Answer("ann", 0, 1, "s1"), START + 9_000)
    assert replay == Step(scored.state, (), result)
    assert refused(scored.state, Answer("ann", 0, 2, "s2"), START + 9_000) == "ALREADY_ANSWERED"
    moved = transition(scored.state, ServeNext("ann", 1), START + 9_000).state
    assert refused(moved, Answer("ann", 1, 0, "s1"), START + 9_500) == "INVALID_MESSAGE"


@pytest.mark.parametrize(
    ("elapsed", "expected"), [(T, (100, False)), (T + 1, (0, True)), (-50, (150, False))]
)
def test_lateness_is_decided_at_answer_time(elapsed: int, expected: tuple[int, bool]) -> None:
    reply = transition(SERVED.state, Answer("ann", 0, 2, "s1"), START + 100 + elapsed).reply
    assert isinstance(reply, ev.AnswerScored)
    assert (reply.points, reply.late) == expected


def test_refused_requests() -> None:
    assert refused(SERVED.state, ServeNext("bob", 0), START) == "NOT_JOINED"
    assert refused(SERVED.state, Answer("ann", 1, 0, "s1"), START) == "QUESTION_NOT_OPEN"
    assert refused(SERVED.state, ServeNext("ann", 2), START) == "INVALID_STATE"
    for command in (Join("bob"), ServeNext("ann", 1), Answer("ann", 0, 2, "s1")):
        assert refused(SERVED.state, command, DEADLINE) == "QUIZ_ENDED"


def test_skips_the_last_answer_finishes_and_a_repeat_of_next_n() -> None:
    last = transition(SERVED.state, ServeNext("ann", 1), START + 100).state  # skips question 0
    assert refused(last, Answer("ann", 0, 2, "s1"), START + 100) == "ALREADY_ANSWERED"
    done = transition(last, Answer("ann", 1, 0, "s1"), START + 100)
    assert done.events[-1] == ev.PlayerFinished("ann", 150)
    finish = transition(done.state, ServeNext("ann", 2), START + 200)
    assert finish == Step(done.state, (), ev.PlayerFinished("ann", 150))
    skipped = transition(last, ServeNext("ann", 2), START + 200)
    assert skipped.events == (ev.QuestionSkipped("ann", 1), ev.PlayerFinished("ann", 0))


def test_quiz_ended_is_broadcast_once() -> None:
    ended = transition(SERVED.state, End(), DEADLINE + 5)
    assert isinstance(ended.reply, ev.QuizEnded)
    assert (ended.events, ended.reply.seq, ended.reply.at_ms) == ((ended.reply,), 1, DEADLINE)
    assert transition(ended.state, End(), DEADLINE + 9) == Step(ended.state, (), None)
    host = transition(SERVED.state, End(), START + 7).state
    assert refused(host, Join("bob"), START + 8) == "QUIZ_ENDED"


def test_domain_error_codes_are_wire_codes() -> None:
    assert {code.value for code in ErrorCode} <= {code.value for code in WireErrorCode}
