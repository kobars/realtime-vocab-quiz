# AI-ASSISTED: public surface of the wire contracts package.
"""Pydantic wire models: the WebSocket protocol, defined once."""

from quiz.contracts.codec import encode, encode_broadcast, parse_client_message
from quiz.contracts.messages import ClientMessage, ErrorCode, ProtocolError, ServerMessage

__all__ = [
    "ClientMessage",
    "ErrorCode",
    "ProtocolError",
    "ServerMessage",
    "encode",
    "encode_broadcast",
    "parse_client_message",
]
