# AI-ASSISTED: domain error codes of docs/spec/protocol.md §6 raised by the session state machine.
from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_MESSAGE = "INVALID_MESSAGE"
    NOT_JOINED = "NOT_JOINED"
    QUESTION_NOT_OPEN = "QUESTION_NOT_OPEN"
    ALREADY_ANSWERED = "ALREADY_ANSWERED"
    INVALID_STATE = "INVALID_STATE"
    QUIZ_ENDED = "QUIZ_ENDED"


class DomainError(Exception):
    """A refused command; the state it was applied to is unchanged."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
