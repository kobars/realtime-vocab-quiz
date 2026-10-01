# AI-ASSISTED: a valid and an invalid wire example for every protocol message.
import json
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from quiz.contracts.messages import (
    CLIENT_ADAPTER,
    SERVER_ADAPTER,
    Broadcast,
    ClientMessage,
    ServerMessage,
    message_types,
)

SUB = "0b7c6a4e-3f1d-4c2a-9e8b-5d6f7a8b9c0d"
ENTRY = {"rank": 1, "userId": "u_1", "displayName": "Ana", "score": 150}

# type -> (valid fields, fields that make it invalid)
CLIENT: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "join": ({"quizId": "VOCAB-42", "displayName": " Ana "}, {"quizId": "vocab-42"}),
    "next": ({"questionIndex": 10}, {"questionIndex": -1}),
    "answer": ({"questionIndex": 0, "choiceIndex": 3, "submissionId": SUB}, {"choiceIndex": 4}),
    "ping": ({}, {"seq": 1}),
    "resync": ({"lastSeq": 0}, {"lastSeq": "0"}),
    "get_leaderboard": ({"offset": 0, "limit": 200}, {"limit": 201}),
}

SERVER: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "leaderboard": (
        {"seq": 1, "rebase": False, "playerCount": 1, "onlineCount": 1, "entries": [ENTRY]},
        {"entries": [ENTRY] * 201},
    ),
    "quiz_ended": (
        {"seq": 9, "playerCount": 1, "entries": [ENTRY], "you": {"rank": 1, "score": 150}},
        {"entries": [ENTRY] * 51},
    ),
    "joined": (
        {
            "atSeq": 0,
            "quizId": "VOCAB-42",
            "userId": "u_1",
            "displayName": "Ana",
            "questionCount": 10,
            "timeLimitMs": 20000,
            "quizRemainingMs": 600000,
            "cursor": -1,
            "cursorOpen": False,
            "finished": False,
            "score": 0,
        },
        {"cursor": -2},
    ),
    "question": (
        {
            "atSeq": 3,
            "questionIndex": 0,
            "questionId": "q-1",
            "prompt": "Pick the synonym of 'quick'",
            "choices": ["fast", "slow", "late", "calm"],
            "timeLimitMs": 20000,
            "remainingMs": 19500,
        },
        {"choices": ["fast", "slow", "late"]},
    ),
    "answer_result": (
        {
            "atSeq": 3,
            "questionIndex": 0,
            "submissionId": SUB,
            "choiceIndex": 0,
            "correctChoiceIndex": 0,
            "correct": True,
            "late": False,
            "pointsAwarded": 150,
            "score": 150,
        },
        {"pointsAwarded": 151},
    ),
    "rank_update": ({"atSeq": 4, "rank": 51, "score": 100, "playerCount": 300}, {"rank": 0}),
    "leaderboard_page": (
        {"atSeq": 4, "offset": 0, "playerCount": 1, "final": True, "entries": [ENTRY]},
        {"final": "yes"},
    ),
    "snapshot": (
        {
            "atSeq": 4,
            "status": "open",
            "playerCount": 1,
            "onlineCount": 0,
            "entries": [ENTRY],
            "you": None,
        },
        {"status": "paused"},
    ),
    "finished": ({"atSeq": 5, "score": 300, "rank": 1, "playerCount": 1}, {"score": -1}),
    "pong": ({"seq": None}, {"seq": -1}),
    "error": (
        {"code": "NOT_JOINED", "message": "join first", "requestType": "next"},
        {"code": "TEAPOT"},
    ),
}


def frame(kind: str, fields: dict[str, Any]) -> bytes:
    return json.dumps({"v": 1, "type": kind, **fields}).encode()


def adapter(kind: str) -> TypeAdapter[Any]:
    return CLIENT_ADAPTER if kind in CLIENT else SERVER_ADAPTER


EXAMPLES = {**CLIENT, **SERVER}
WITH_FIELDS = sorted(kind for kind, (fields, _) in EXAMPLES.items() if fields)


def test_every_message_has_examples() -> None:
    assert set(CLIENT) == message_types(ClientMessage)
    assert set(SERVER) == message_types(ServerMessage)


def test_message_types_reads_a_plain_union() -> None:
    assert message_types(Broadcast) == {"leaderboard", "quiz_ended"}


@pytest.mark.parametrize("kind", sorted(EXAMPLES))
def test_valid_message_round_trips(kind: str) -> None:
    raw = frame(kind, EXAMPLES[kind][0])
    message = adapter(kind).validate_json(raw)
    assert message.type == kind
    assert json.loads(adapter(kind).dump_json(message)) == json.loads(raw)


@pytest.mark.parametrize("kind", sorted(EXAMPLES))
def test_invalid_message_is_rejected(kind: str) -> None:
    valid, bad = EXAMPLES[kind]
    with pytest.raises(ValidationError):
        adapter(kind).validate_json(frame(kind, {**valid, **bad}))


@pytest.mark.parametrize("kind", WITH_FIELDS)
def test_message_with_a_missing_field_is_rejected(kind: str) -> None:
    fields = dict(EXAMPLES[kind][0])
    fields.popitem()
    with pytest.raises(ValidationError, match="Field required"):
        adapter(kind).validate_json(frame(kind, fields))


@pytest.mark.parametrize("kind", sorted(EXAMPLES))
def test_unknown_field_is_rejected(kind: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        adapter(kind).validate_json(frame(kind, {**EXAMPLES[kind][0], "extra": 1}))

