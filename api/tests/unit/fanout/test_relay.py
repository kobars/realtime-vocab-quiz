# AI-ASSISTED: what the relay does with each feed message: control, quiz_ended and stale ranks.
import json
from unittest.mock import Mock

from quiz.fanout.broadcast import Relay
from quiz.ports.store import Limits, Store


async def test_session_replaced_closes_the_local_socket_and_reaches_no_client(
    sockets: Mock,
) -> None:
    relay = Relay("Q", Mock(spec=Store), sockets, Limits())
    message = json.dumps({"type": "session_replaced", "uid": "u", "connId": "c-old"})
    assert await relay.relay(message) is False
    sockets.replace.assert_called_once_with("c-old")
    sockets.broadcast.assert_not_called()
    sockets.send_to.assert_not_called()
