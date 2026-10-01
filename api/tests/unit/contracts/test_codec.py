# AI-ASSISTED: inbound frame checks (size, depth, JSON, version, type) and the broadcast encoder.
import json

import pytest

from quiz.contracts import ErrorCode, ProtocolError, encode_broadcast, parse_client_message
from quiz.contracts.codec import MAX_DEPTH, MAX_FRAME_BYTES, exceeds_depth
from quiz.contracts.messages import Entry, Leaderboard, Ping

PING = b'{"v":1,"type":"ping"}'


def code_of(raw: bytes) -> ErrorCode | None:
    result = parse_client_message(raw)
    return result.code if isinstance(result, ProtocolError) else None


def test_a_frame_of_exactly_the_limit_is_parsed() -> None:
    raw = PING + b" " * (MAX_FRAME_BYTES - len(PING))
    assert parse_client_message(raw) == Ping()


def test_a_frame_above_the_limit_is_too_large_before_any_parsing() -> None:
    raw = b"[" * (MAX_FRAME_BYTES + 1)
    assert code_of(raw) == ErrorCode.MESSAGE_TOO_LARGE


@pytest.mark.parametrize(("depth", "too_deep"), [(MAX_DEPTH, False), (MAX_DEPTH + 1, True)])
def test_nesting_is_limited_before_parsing(depth: int, *, too_deep: bool) -> None:
    nested = "[" * (depth - 1) + "]" * (depth - 1)
    raw = f'{{"v":1,"type":"ping","x":{nested or 0}}}'.encode()
    assert exceeds_depth(raw) is too_deep
    result = parse_client_message(raw)
    assert isinstance(result, ProtocolError)
    assert ("nesting" in result.message) is too_deep


def test_brackets_inside_strings_do_not_count_as_nesting() -> None:
    name = '\\"[[[[[[[[[[{{{{{{{{{{'
    raw = f'{{"v":1,"type":"join","quizId":"VOCAB-42","displayName":"{name}"}}'.encode()
    assert not exceeds_depth(raw)
    assert code_of(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"\xff\xfe",
        b'{"v":1,"type":"ping"} x',
        b'{"v":NaN,"type":"ping"}',
        b"[1]",
        b'"ping"',
        b'{"type":"ping"}',
        b'{"v":1}',
        b'{"v":1,"type":7}',
    ],
)
def test_malformed_frames_are_invalid_messages(raw: bytes) -> None:
    assert code_of(raw) == ErrorCode.INVALID_MESSAGE


@pytest.mark.parametrize("version", ["2", "true", "1.0", '"1"', "0", "null"])
def test_a_wrong_version_is_unsupported(version: str) -> None:
    assert code_of(f'{{"v":{version},"type":"ping"}}'.encode()) == ErrorCode.UNSUPPORTED_VERSION


@pytest.mark.parametrize("kind", ["subscribe", "leaderboard", "PING", ""])
def test_an_unknown_type_is_unsupported(kind: str) -> None:
    result = parse_client_message(f'{{"v":1,"type":"{kind}"}}'.encode())
    assert isinstance(result, ProtocolError)
    assert result.code == ErrorCode.UNSUPPORTED_TYPE
    assert result.requestType is None


def test_the_version_is_checked_before_the_type() -> None:
    assert code_of(b'{"v":2,"type":"future"}') == ErrorCode.UNSUPPORTED_VERSION


def test_a_broadcast_is_encoded_once_as_compact_json_with_every_field() -> None:
    frame = Leaderboard(
        seq=7,
        rebase=False,
        playerCount=1,
        onlineCount=1,
        entries=[Entry(rank=1, userId="u_1", displayName="Ana", score=150)],
    )
    raw = encode_broadcast(frame)
    assert isinstance(raw, bytes)
    assert raw.startswith(b'{"v":1,"type":"leaderboard","seq":7,')
    assert b" " not in raw
    assert json.loads(raw)["entries"] == [
        {"rank": 1, "userId": "u_1", "displayName": "Ana", "score": 150}
    ]


@pytest.mark.parametrize(
    "raw",
    [
        b'{"v":1,"type":"get_leaderboard","offset":1000000000000000000000000000000,"limit":10}',
        b'{"v":1,"type":"next","questionIndex":' + b"9" * 4000 + b"}",
        b'{"v":1,"type":"resync","lastSeq":9007199254740993}',
    ],
    ids=["offset-1e30", "questionIndex-4000-digits", "lastSeq-2**53+1"],
)
def test_an_integer_above_the_wire_maximum_is_an_invalid_message(raw: bytes) -> None:
    result = parse_client_message(raw)
    assert isinstance(result, ProtocolError)
    assert result.code == ErrorCode.INVALID_MESSAGE


def test_an_integer_at_the_wire_maximum_is_parsed() -> None:
    raw = f'{{"v":1,"type":"resync","lastSeq":{2**53}}}'.encode()
    assert code_of(raw) is None


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b'{"type":"answer"}', ErrorCode.INVALID_MESSAGE),
        (b'{"v":2,"type":"answer"}', ErrorCode.UNSUPPORTED_VERSION),
    ],
)
def test_a_version_error_names_a_known_request_type(raw: bytes, code: ErrorCode) -> None:
    result = parse_client_message(raw)
    assert isinstance(result, ProtocolError)
    assert result.code == code
    assert result.requestType == "answer"


@pytest.mark.parametrize("raw", [b'{"v":2,"type":"future"}', b'{"v":2,"type":7}', b'{"v":2}'])
def test_a_version_error_without_a_known_type_has_no_request_type(raw: bytes) -> None:
    result = parse_client_message(raw)
    assert isinstance(result, ProtocolError)
    assert result.code == ErrorCode.UNSUPPORTED_VERSION
    assert result.requestType is None
