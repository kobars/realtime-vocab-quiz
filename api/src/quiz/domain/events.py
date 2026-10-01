# AI-ASSISTED: the events and replies of the session state machine.
from dataclasses import dataclass

from quiz.domain.standings import RankedStanding


@dataclass(frozen=True, slots=True)
class ParticipantJoined:
    user_id: str
    at_ms: int


@dataclass(frozen=True, slots=True)
class QuestionServed:
    user_id: str
    question_index: int
    question_id: str
    serve_ms: int
    remaining_ms: int


@dataclass(frozen=True, slots=True)
class QuestionSkipped:
    user_id: str
    question_index: int


@dataclass(frozen=True, slots=True)
class AnswerScored:  # the stored answer_result; a replay returns this object
    user_id: str
    question_index: int
    submission_id: str
    choice_index: int
    correct_choice: int
    correct: bool
    late: bool
    points: int
    total: int
    at_seq: int


@dataclass(frozen=True, slots=True)
class PlayerFinished:
    user_id: str
    total: int


@dataclass(frozen=True, slots=True)
class QuizEnded:
    seq: int
    at_ms: int
    entries: tuple[RankedStanding, ...]


type Event = (
    ParticipantJoined | QuestionServed | QuestionSkipped | AnswerScored | PlayerFinished | QuizEnded
)
