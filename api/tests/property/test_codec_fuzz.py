# AI-ASSISTED: Hypothesis fuzz of the inbound frame parser: any bytes give a client message or an
# error to send back, never an exception.
import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from quiz.contracts import ErrorCode, ProtocolError, encode, parse_client_message
from quiz.contracts.codec import CLIENT_TYPES, MAX_DEPTH, MAX_FRAME_BYTES
from quiz.contracts.messages import MAX_WIRE_INT

PARSER_CODES = {
    ErrorCode.MESSAGE_TOO_LARGE,
    ErrorCode.INVALID_MESSAGE,
    ErrorCode.UNSUPPORTED_VERSION,
    ErrorCode.UNSUPPORTED_TYPE,
}

# Edge values on both sides of each bound, plus anything else.
wire_ints = st.integers(min_value=-1, max_value=MAX_WIRE_INT + 1) | st.integers()
# Lone surrogates survive json.dumps as \uXXXX escapes and break a later UTF-8 encode. They get
# their own branch: inside one alphabet they are about 0.2% of the code points, so rarely drawn.
lone_surrogates = st.text(st.characters(categories=["Cs"]), min_size=1, max_size=4)
any_text = st.text(max_size=40) | lone_surrogates
json_values = st.recursive(
    st.none() | st.booleans() | wire_ints | st.floats() | any_text,
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(any_text, inner, max_size=4),
    max_leaves=12,
)


def _frame(kind: str, **fields: st.SearchStrategy[Any]) -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries({"v": st.just(1), "type": st.just(kind), **fields})


valid_frames = st.one_of(
    _frame("ping"),
    _frame(
        "join",
        quizId=st.from_regex(r"\A[A-Z0-9-]{3,16}\Z") | any_text,
        displayName=st.text(max_size=130),
    ),
    _frame("next", questionIndex=wire_ints),
    _frame(
        "answer",
        questionIndex=wire_ints,
        choiceIndex=st.integers(min_value=-1, max_value=5),
        submissionId=st.uuids().map(str) | any_text,
    ),
    _frame("resync", lastSeq=wire_ints),
    _frame("get_leaderboard", offset=wire_ints, limit=wire_ints),
)
wire_fields = ["v", "type", "quizId", "displayName", "questionIndex", "choiceIndex"]
field_names = st.sampled_from([*wire_fields, "submissionId", "lastSeq", "offset", "limit"])


@st.composite
def mutated_json(draw: st.DrawFn) -> bytes:
    """A valid frame with fields dropped, replaced or added, then serialized and maybe damaged."""
    frame = draw(valid_frames)
    for _ in range(draw(st.integers(0, 3))):
        key = draw(field_names | any_text)
        if draw(st.booleans()):
            frame.pop(key, None)
        else:
            frame[key] = draw(json_values | st.sampled_from(sorted(CLIENT_TYPES)))
    text = json.dumps(frame, ensure_ascii=draw(st.booleans()))
    raw = text.encode("utf-8", "surrogatepass")
    if draw(st.booleans()):
        cut = draw(st.integers(0, len(raw)))
        raw = raw[:cut] + draw(st.binary(max_size=8)) + raw[cut + draw(st.integers(0, 4)) :]
    return raw


nested = st.integers(MAX_DEPTH - 1, MAX_DEPTH + 2).map(
    lambda depth: b'{"v":1,"type":"ping","x":' + b"[" * depth + b"]" * depth + b"}"
)
long_numbers = st.integers(1, 6_000).map(
    lambda digits: b'{"v":1,"type":"next","questionIndex":' + b"9" * digits + b"}"
)
# Padding keeps the JSON intact and moves the frame across the size limit.
near_the_limit = st.tuples(mutated_json(), st.integers(MAX_FRAME_BYTES - 64, MAX_FRAME_BYTES + 64))
hostile_frames = st.one_of(
    st.binary(max_size=MAX_FRAME_BYTES + 64),
    mutated_json(),
    near_the_limit.map(lambda pair: pair[0].ljust(pair[1])),
    nested,
    long_numbers,
)


@given(hostile_frames)
def test_any_frame_gives_a_client_message_or_an_error_to_send(raw: bytes) -> None:
    result = parse_client_message(raw)
    wire = encode(result)  # the session sends an error as returned, so encoding must not raise
    if isinstance(result, ProtocolError):
        assert result.code in PARSER_CODES
    else:
        assert parse_client_message(wire) == result
