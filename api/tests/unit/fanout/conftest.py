# AI-ASSISTED: this node's sockets for the fan-out unit tests.
from unittest.mock import Mock

import pytest

from quiz.fanout.broadcast import Sockets


@pytest.fixture
def sockets() -> Mock:
    """This node's sockets of the quiz: player u's alone; the mock records each send."""
    sockets = Mock(spec=Sockets)
    sockets.players.return_value = {"u"}
    return sockets
