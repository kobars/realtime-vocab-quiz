# AI-ASSISTED: the HTTP request and response bodies, each with an example for the OpenAPI page.
# Field names are the camelCase wire names, hence the file-wide N815 exemption.
# ruff: noqa: N815
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

LIMIT_MS = 3_600_000  # one hour: the longest question time and quiz window


def _example(**fields: JsonValue) -> ConfigDict:
    return ConfigDict(extra="forbid", json_schema_extra={"examples": [fields]})


class SessionIn(BaseModel):
    model_config = _example(displayName="Ana")
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
    model_config = _example(quizId="VOCAB-42", timeLimitMs=20_000, windowMs=600_000)
    quizId: Annotated[str, Field(pattern=r"^[A-Z0-9-]{3,16}$")]
    timeLimitMs: Annotated[int, Field(ge=1, le=LIMIT_MS)] = 20_000
    windowMs: Annotated[int, Field(ge=1, le=LIMIT_MS)] = 600_000


class Ended(BaseModel):
    model_config = _example(quizId="VOCAB-42", status="ended", endSeq=57)
    quizId: str
    status: Literal["ended"]
    endSeq: int | None


class Status(BaseModel):
    model_config = _example(status="ok")
    status: Literal["ok", "ready", "unavailable"]


class Problem(BaseModel):
    model_config = _example(error="QUIZ_NOT_FOUND", message="no such quiz")
    error: str
    message: str
