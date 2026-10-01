# AI-ASSISTED: error codes of docs/spec/protocol.md §7 raised by the state machine and the store.
from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_MESSAGE = "INVALID_MESSAGE"
    NOT_JOINED = "NOT_JOINED"
    QUESTION_NOT_OPEN = "QUESTION_NOT_OPEN"
    ALREADY_ANSWERED = "ALREADY_ANSWERED"
    INVALID_STATE = "INVALID_STATE"
    QUIZ_ENDED = "QUIZ_ENDED"
    QUIZ_NOT_FOUND = "QUIZ_NOT_FOUND"
    SESSION_REPLACED = "SESSION_REPLACED"


class DomainError(Exception):
    """A refused command; the state it was applied to is unchanged.

    A ``QUIZ_ENDED`` refusal carries ``end_seq``: the seq of ``quiz_ended``, or None while no
    end was announced, in which case the caller runs ``end_quiz`` (docs/spec/redis.md §3.1).
    """

    def __init__(self, code: ErrorCode, message: str, *, end_seq: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.end_seq = end_seq
