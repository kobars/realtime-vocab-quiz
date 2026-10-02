# AI-ASSISTED: the HTTP request and response bodies, each with an example for the OpenAPI page;
# request bodies take JSON types strictly; the self-service hosting bodies too.
# Field names are the camelCase wire names, hence the file-wide N815 exemption.
# ruff: noqa: N815
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from quiz.contracts.messages import QuizId

LIMIT_MS = 3_600_000  # one hour: the longest question time and quiz window
QUESTION_MS = 20_000  # the question time of a self-hosted quiz, and the admin API's default


def _example(*, strict: bool = False, **fields: JsonValue) -> ConfigDict:
    return ConfigDict(extra="forbid", strict=strict, json_schema_extra={"examples": [fields]})


def _request(**fields: JsonValue) -> ConfigDict:
    """A request body: no type coercion, so ``true``, ``"90000"`` or ``1.0`` is no integer."""
    return _example(strict=True, **fields)


class SessionIn(BaseModel):
    model_config = _request(displayName="Ana")
    displayName: Annotated[str, Field(max_length=128)]


class SessionOut(BaseModel):
    model_config = _example(userId="u_3kq9VbX2mPz1aQ7c", sessionToken="mF3x…43 characters")
    userId: str
    sessionToken: str


class TicketOut(BaseModel):
    model_config = _example(ticket="Zp8Q…43 characters", expiresInMs=30_000)
    ticket: str
    expiresInMs: int


class QuizInfo(BaseModel):
    model_config = _example(
        quizId="VOCAB-42", title="Everyday English", questionCount=10, status="open", players=12
    )
    quizId: str
    title: str
    questionCount: int
    status: Literal["open", "ended"]
    players: int


class CreateQuiz(BaseModel):
    model_config = _request(
        quizId="VOCAB-42-7K3Q", bankQuizId="VOCAB-42", timeLimitMs=20_000, windowMs=600_000
    )
    quizId: QuizId
    bankQuizId: QuizId | None = None  # the bank quiz it plays; by default quizId
    timeLimitMs: Annotated[int, Field(ge=1, le=LIMIT_MS)] = QUESTION_MS
    windowMs: Annotated[int, Field(ge=1, le=LIMIT_MS)] = 600_000


class Ended(BaseModel):
    model_config = _example(quizId="VOCAB-42", status="ended", endSeq=57)
    quizId: str
    status: Literal["ended"]
    endSeq: int


class Bank(BaseModel):
    model_config = _example(id="VOCAB-42", title="Everyday English", questionCount=10)
    id: str
    title: str
    questionCount: int


class HostIn(BaseModel):
    model_config = _request(bankQuizId="VOCAB-42")
    bankQuizId: QuizId


class Hosted(BaseModel):
    model_config = _example(
        quizId="VOCAB-42-7K3Q",
        sharePath="/q/VOCAB-42-7K3Q",
        hostToken="Qm9…43 characters",
        windowMs=1_800_000,
        endsAtMs=1_800_001_800_000,
    )
    quizId: str
    sharePath: str
    hostToken: str  # shown once; the store keeps its SHA-256 only
    windowMs: int
    endsAtMs: int


class Status(BaseModel):
    model_config = _example(status="ok")
    status: Literal["ok", "ready", "unavailable"]


class Problem(BaseModel):
    model_config = _example(error="QUIZ_NOT_FOUND", message="no such quiz")
    error: str
    message: str
