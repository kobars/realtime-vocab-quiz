# AI-ASSISTED: strict inbound frame parser and the one-shot encoder for outbound messages.
"""Turn inbound frames into typed client messages, and messages into wire bytes.

The cheap checks (size, then nesting depth) run on the raw bytes before any JSON
parsing, so a hostile frame costs one linear scan at most.
"""

import json
from typing import NoReturn

from pydantic import ValidationError

from quiz.contracts.messages import (
    CLIENT_ADAPTER,
    Broadcast,
    ClientMessage,
    ErrorCode,
    ProtocolError,
    ServerMessage,
    message_types,
)

MAX_FRAME_BYTES = 16 * 1024
MAX_DEPTH = 8

CLIENT_TYPES = message_types(ClientMessage)

_OPEN, _CLOSE, _QUOTE, _BACKSLASH = frozenset(b"[{"), frozenset(b"]}"), ord('"'), ord("\\")


def _error(code: ErrorCode, message: str, request_type: str | None = None) -> ProtocolError:
    return ProtocolError(code=code, message=message, requestType=request_type)


def exceeds_depth(raw: bytes, limit: int = MAX_DEPTH) -> bool:
    """Return True when arrays and objects nest deeper than ``limit`` (strings are skipped)."""
    depth = 0
    in_string = escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == _BACKSLASH:
                escaped = True
            elif byte == _QUOTE:
                in_string = False
        elif byte == _QUOTE:
            in_string = True
        elif byte in _OPEN:
            depth += 1
            if depth > limit:
                return True
        elif byte in _CLOSE:
            depth -= 1
    return False


def _reject_constant(name: str) -> NoReturn:
    msg = f"{name} is not JSON"
    raise ValueError(msg)


def parse_client_message(raw: bytes) -> ClientMessage | ProtocolError:  # noqa: PLR0911
    """Return the typed message in ``raw``, or the ``error`` message to send back."""
    if len(raw) > MAX_FRAME_BYTES:
        return _error(ErrorCode.MESSAGE_TOO_LARGE, f"frame above {MAX_FRAME_BYTES} bytes")
    if exceeds_depth(raw):
        return _error(ErrorCode.INVALID_MESSAGE, f"JSON nesting above {MAX_DEPTH}")
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except ValueError:
        return _error(ErrorCode.INVALID_MESSAGE, "not a UTF-8 JSON text")
    if not isinstance(data, dict):
        return _error(ErrorCode.INVALID_MESSAGE, "not a JSON object")
    kind = data.get("type")
    known = kind if isinstance(kind, str) and kind in CLIENT_TYPES else None
    if "v" not in data:
        return _error(ErrorCode.INVALID_MESSAGE, "missing field v", known)
    version = data["v"]
    if type(version) is not int or version != 1:
        msg = "only protocol version 1 is supported"
        return _error(ErrorCode.UNSUPPORTED_VERSION, msg, known)
    if not isinstance(kind, str):
        return _error(ErrorCode.INVALID_MESSAGE, "missing or non-string field type")
    if kind not in CLIENT_TYPES:
        return _error(ErrorCode.UNSUPPORTED_TYPE, "unknown message type")
    try:
        return CLIENT_ADAPTER.validate_python(data)
    except ValidationError as exc:
        first = exc.errors(include_url=False, include_input=False)[0]
        where = ".".join(str(part) for part in first["loc"][1:]) or "message"
        return _error(ErrorCode.INVALID_MESSAGE, f"{where}: {first['msg']}", kind)


def encode(message: ClientMessage | ServerMessage) -> bytes:
    """Serialize one message to compact UTF-8 JSON, every field present."""
    return message.__pydantic_serializer__.to_json(message)


def encode_broadcast(message: Broadcast) -> bytes:
    """Encode a broadcast once; the fan-out sends these same bytes to every socket."""
    return encode(message)
