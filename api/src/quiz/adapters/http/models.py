# AI-ASSISTED: the HTTP request and response bodies.
# Field names are the camelCase wire names, hence the file-wide N815 exemption.
# ruff: noqa: N815
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

LIMIT_MS = 3_600_000  # one hour: the longest question time and quiz window


class SessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    displayName: Annotated[str, Field(max_length=128)]


class SessionOut(BaseModel):
    userId: str
    sessionToken: str


class TicketOut(BaseModel):
    ticket: str
    expiresInMs: int


class QuizInfo(BaseModel):
    quizId: str
    title: str
    questionCount: int
    status: Literal["open", "ended"]
    players: int


class CreateQuiz(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quizId: Annotated[str, Field(pattern=r"^[A-Z0-9-]{3,16}$")]
    timeLimitMs: Annotated[int, Field(ge=1, le=LIMIT_MS)] = 20_000
    windowMs: Annotated[int, Field(ge=1, le=LIMIT_MS)] = 600_000


class Ended(BaseModel):
    quizId: str
    status: Literal["ended"]
    endSeq: int | None


class Status(BaseModel):
    status: Literal["ok", "ready", "unavailable"]


class Problem(BaseModel):
    error: str
    message: str
