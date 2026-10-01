# AI-ASSISTED: the joined sockets of this node per quiz, and closing a replaced session.
"""Which socket of this node serves which quiz: a broadcast reaches every local socket of the
quiz, and a connection that a newer join replaced is closed here when it lives on this node."""

from quiz.adapters.ws.sender import Sender
from quiz.app.service import CLOSE_REPLACED, Connection
from quiz.contracts import messages as m


class Registry:
    def __init__(self) -> None:
        self._senders: dict[str, Sender] = {}  # conn_id → its sender
        self._quizzes: dict[str, dict[str, Sender]] = {}  # quiz_id → conn_id → sender

    def bind(self, conn: Connection, sender: Sender) -> None:
        """Record a socket under the quiz it joined; a repeat join changes nothing."""
        if conn.quiz_id is not None:
            self._senders[conn.conn_id] = sender
            self._quizzes.setdefault(conn.quiz_id, {})[conn.conn_id] = sender

    def senders(self, quiz_id: str) -> list[Sender]:
        return list(self._quizzes.get(quiz_id, {}).values())

    def broadcast(self, quiz_id: str, data: bytes, *, leaderboard: bool) -> None:
        """Queue one encoded frame on every local socket of the quiz."""
        for sender in self.senders(quiz_id):
            sender.send_frame(data, leaderboard=leaderboard)

    def replace(self, conn_id: str) -> None:
        """Close a socket of this node that a newer join took over: the error, then 4001."""
        if (sender := self._senders.get(conn_id)) is not None:
            text = "this quiz was opened on another connection"
            error = m.ProtocolError(
                code=m.ErrorCode.SESSION_REPLACED, message=text, requestType=None
            )
            sender.send(error)
            sender.close(CLOSE_REPLACED)

    def drop(self, conn: Connection) -> None:
        """Forget a closed socket."""
        if self._senders.pop(conn.conn_id, None) is None or conn.quiz_id is None:
            return
        quiz = self._quizzes[conn.quiz_id]
        del quiz[conn.conn_id]
        if not quiz:
            del self._quizzes[conn.quiz_id]
