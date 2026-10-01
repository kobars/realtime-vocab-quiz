# AI-ASSISTED: Pydantic models for every message of the wire protocol v1 (docs/spec/protocol.md).
# Field names are the camelCase wire names, hence the file-wide N815 exemption.
# ruff: noqa: N815
"""The wire protocol v1: one model per message, two discriminated unions on ``type``.

Field names are the wire names (camelCase), so a model and its JSON read the same.
Every field is required; a field without a value is ``null``, never omitted.
Order: client messages, broadcasts (carry ``seq``), unicasts (carry ``atSeq``), then
``pong`` and ``error``.
"""

from enum import StrEnum
from typing import Annotated, Literal, TypeAliasType, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

QuizId = Annotated[str, Field(pattern=r"^[A-Z0-9-]{3,16}$")]
UserId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
QuestionId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
SubmissionId = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
DisplayName = Annotated[str, Field(min_length=1, max_length=32)]
RawDisplayName = Annotated[str, Field(max_length=128)]
NonNegative = Annotated[int, Field(ge=0)]
Rank = Annotated[int, Field(ge=1)]
ChoiceIndex = Annotated[int, Field(ge=0, le=3)]

FULL_LIST_MAX = 200
TOP_N = 50


class ErrorCode(StrEnum):
    INVALID_MESSAGE = "INVALID_MESSAGE"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    MESSAGE_TOO_LARGE = "MESSAGE_TOO_LARGE"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    QUIZ_NOT_FOUND = "QUIZ_NOT_FOUND"
    NOT_JOINED = "NOT_JOINED"
    QUESTION_NOT_OPEN = "QUESTION_NOT_OPEN"
    ALREADY_ANSWERED = "ALREADY_ANSWERED"
    RATE_LIMITED = "RATE_LIMITED"
    SESSION_REPLACED = "SESSION_REPLACED"
    UNAVAILABLE = "UNAVAILABLE"
    INTERNAL = "INTERNAL"
    QUIZ_ENDED = "QUIZ_ENDED"
    INVALID_STATE = "INVALID_STATE"


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        json_schema_serialization_defaults_required=True,
    )


class _Message(_Strict):
    # v and type have defaults so code can build messages; the inbound parser requires both.
    v: Literal[1] = 1


class Entry(_Strict):
    rank: Rank
    userId: UserId
    displayName: DisplayName
    score: NonNegative


class You(_Strict):
    rank: Rank
    score: NonNegative


class Join(_Message):
    type: Literal["join"] = "join"
    quizId: QuizId
    displayName: RawDisplayName


class Next(_Message):
    type: Literal["next"] = "next"
    questionIndex: NonNegative


class Answer(_Message):
    type: Literal["answer"] = "answer"
    questionIndex: NonNegative
    choiceIndex: ChoiceIndex
    submissionId: SubmissionId


class Ping(_Message):
    type: Literal["ping"] = "ping"


class Resync(_Message):
    type: Literal["resync"] = "resync"
    lastSeq: NonNegative


class GetLeaderboard(_Message):
    type: Literal["get_leaderboard"] = "get_leaderboard"
    offset: NonNegative
    limit: Annotated[int, Field(ge=1, le=FULL_LIST_MAX)]


class Leaderboard(_Message):
    type: Literal["leaderboard"] = "leaderboard"
    seq: NonNegative
    rebase: bool
    playerCount: NonNegative
    onlineCount: NonNegative
    entries: Annotated[list[Entry], Field(max_length=FULL_LIST_MAX)]


class QuizEnded(_Message):
    type: Literal["quiz_ended"] = "quiz_ended"
    seq: NonNegative
    playerCount: NonNegative
    entries: Annotated[list[Entry], Field(max_length=TOP_N)]
    you: You | None


class Joined(_Message):
    type: Literal["joined"] = "joined"
    atSeq: NonNegative
    quizId: QuizId
    userId: UserId
    displayName: DisplayName
    questionCount: NonNegative
    timeLimitMs: NonNegative
    quizRemainingMs: NonNegative
    cursor: Annotated[int, Field(ge=-1)]
    cursorOpen: bool
    finished: bool
    score: NonNegative


class Question(_Message):
    type: Literal["question"] = "question"
    atSeq: NonNegative
    questionIndex: NonNegative
    questionId: QuestionId
    prompt: str
    choices: Annotated[list[str], Field(min_length=4, max_length=4)]
    timeLimitMs: NonNegative
    remainingMs: NonNegative


class AnswerResult(_Message):
    type: Literal["answer_result"] = "answer_result"
    atSeq: NonNegative
    questionIndex: NonNegative
    submissionId: SubmissionId
    choiceIndex: ChoiceIndex
    correctChoiceIndex: ChoiceIndex
    correct: bool
    late: bool
    pointsAwarded: Annotated[int, Field(ge=0, le=150)]
    score: NonNegative


class RankUpdate(_Message):
    type: Literal["rank_update"] = "rank_update"
    atSeq: NonNegative
    rank: Rank
    score: NonNegative
    playerCount: NonNegative


class LeaderboardPage(_Message):
    type: Literal["leaderboard_page"] = "leaderboard_page"
    atSeq: NonNegative
    offset: NonNegative
    playerCount: NonNegative
    final: bool
    entries: Annotated[list[Entry], Field(max_length=FULL_LIST_MAX)]


class Snapshot(_Message):
    type: Literal["snapshot"] = "snapshot"
    atSeq: NonNegative
    status: Literal["open", "ended"]
    playerCount: NonNegative
    onlineCount: NonNegative
    entries: Annotated[list[Entry], Field(max_length=FULL_LIST_MAX)]
    you: You | None


class Finished(_Message):
    type: Literal["finished"] = "finished"
    atSeq: NonNegative
    score: NonNegative
    rank: Rank
    playerCount: NonNegative


class Pong(_Message):
    type: Literal["pong"] = "pong"
    seq: NonNegative | None


class ProtocolError(_Message):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str
    requestType: str | None


type ClientMessage = Annotated[
    Join | Next | Answer | Ping | Resync | GetLeaderboard, Field(discriminator="type")
]
type Broadcast = Leaderboard | QuizEnded
type ServerMessage = Annotated[
    Leaderboard
    | QuizEnded
    | Joined
    | Question
    | AnswerResult
    | RankUpdate
    | LeaderboardPage
    | Snapshot
    | Finished
    | Pong
    | ProtocolError,
    Field(discriminator="type"),
]


def message_types(union: TypeAliasType) -> frozenset[str]:
    """Return the ``type`` values of the models in a message union."""
    models: tuple[type[_Message], ...] = get_args(get_args(union.__value__)[0])
    return frozenset(model.model_fields["type"].default for model in models)


CLIENT_ADAPTER: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)
SERVER_ADAPTER: TypeAdapter[ServerMessage] = TypeAdapter(ServerMessage)
