# AI-ASSISTED: the question bank port; the mock bank of the demo implements it.
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BankQuestion:
    question_id: str
    prompt: str
    choices: tuple[str, ...]
    correct_choice: int


class QuestionBank(Protocol):
    async def questions(self, quiz_id: str) -> tuple[BankQuestion, ...] | None:
        """Return the questions of a quiz in serve order, or None for an unknown quiz."""
        ...
