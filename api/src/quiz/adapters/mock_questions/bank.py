# AI-ASSISTED: the seeded vocabulary question bank, validated when it loads.
"""MOCK: a fixed vocabulary bank read from ``data/*.json`` at start-up. A real system would read
quizzes from a content service or a database, edited in an authoring tool.

Each file holds one quiz: ``quiz_id``, ``title`` and its questions (``id``, ``word``, four
distinct ``choices`` and the ``answer`` index). Question IDs are the quiz ID lowercased without
hyphens, then a two-digit number in serve order: ``VOCAB-42`` has ``vocab42-01`` … ``vocab42-10``.
A file that is not JSON or breaks a rule stops the load with a ``ValueError`` that names the file.
"""

import json
from pathlib import Path
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    ValidationError,
    model_validator,
)

from quiz.ports.questions import BankQuestion

DATA = Path(__file__).parent / "data"
CHOICES = 4
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class _Question(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    word: Text
    choices: tuple[Text, Text, Text, Text]
    answer: Annotated[StrictInt, Field(ge=0, le=CHOICES - 1)]

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if len(set(self.choices)) != CHOICES:
            msg = f"{self.id}: the 4 choices must be distinct"
            raise ValueError(msg)
        return self


class _Quiz(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    quiz_id: Annotated[str, Field(pattern=r"^[A-Z0-9-]{3,16}$")]
    title: Text
    questions: Annotated[tuple[_Question, ...], Field(min_length=1, max_length=99)]

    @model_validator(mode="after")
    def _ids(self) -> Self:
        prefix = self.quiz_id.lower().replace("-", "")
        for number, question in enumerate(self.questions, start=1):
            if question.id != f"{prefix}-{number:02d}":
                msg = f"question {number} has id {question.id!r}, expected {prefix}-{number:02d}"
                raise ValueError(msg)
        return self


def parse_quiz(data: object) -> tuple[str, tuple[BankQuestion, ...]]:
    """Validate one quiz file's content; raise ``ValueError`` on any broken rule."""
    try:
        quiz = _Quiz.model_validate(data)
    except ValidationError as error:
        msg = f"invalid quiz: {error}"
        raise ValueError(msg) from None
    return quiz.quiz_id, tuple(
        BankQuestion(q.id, q.word, q.choices, q.answer) for q in quiz.questions
    )


class MockQuestionBank:
    def __init__(self, quizzes: dict[str, tuple[BankQuestion, ...]]) -> None:
        self._quizzes = quizzes

    @classmethod
    def load(cls, folder: Path = DATA) -> Self:
        quizzes: dict[str, tuple[BankQuestion, ...]] = {}
        for path in sorted(folder.glob("*.json")):
            try:
                quiz_id, questions = parse_quiz(json.loads(path.read_text(encoding="utf-8")))
            except ValueError as error:
                msg = f"{path.name}: {error}"
                raise ValueError(msg) from None
            if quiz_id in quizzes:
                msg = f"{path.name}: quiz {quiz_id} is defined twice"
                raise ValueError(msg)
            quizzes[quiz_id] = questions
        return cls(quizzes)

    @property
    def quiz_ids(self) -> tuple[str, ...]:
        return tuple(self._quizzes)

    async def questions(self, quiz_id: str) -> tuple[BankQuestion, ...] | None:
        return self._quizzes.get(quiz_id)
