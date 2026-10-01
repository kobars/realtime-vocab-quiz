# AI-ASSISTED: the joined sockets of this node per quiz, session replacement and the leave grace.
"""Which socket of this node serves which quiz: a broadcast reaches every local socket of the
quiz, and a connection that another join replaced is closed here when it lives on this node.

A joined socket that drops keeps its presence for the grace period, then ``leave`` runs. A join
of the same player on this node cancels the timer, and a socket that such a join replaced starts
none; ``leave`` compares the connection id, so a timer that still fires never removes a newer
connection on another node (docs/spec/redis.md §3). A read-only join (after the end) writes no
presence, so it leaves the timer running: ``leave`` still removes presence then (§3.1)."""

import asyncio
import logging

from quiz.adapters.ws.sender import Sender
from quiz.app.service import CLOSE_REPLACED, Connection
from quiz.contracts import messages as m
from quiz.ports.store import Store

log = logging.getLogger(__name__)


class Registry:
    def __init__(self, store: Store, grace_ms: int) -> None:
        self._store, self._grace_s = store, grace_ms / 1000
        self._senders: dict[str, Sender] = {}  # conn_id → its sender
        self._quizzes: dict[str, dict[str, Sender]] = {}  # quiz_id → conn_id → sender
        self._grace: dict[tuple[str, str], asyncio.Task[None]] = {}  # (quiz_id, user_id) → timer
        self._present: dict[tuple[str, str], str] = {}  # (quiz_id, user_id) → newest conn_id

    def bind(self, conn: Connection, sender: Sender) -> None:
        """Record a joined socket; a writing join cancels the player's pending leave."""
        if conn.quiz_id is None:
            return
        self._senders[conn.conn_id] = sender
        self._quizzes.setdefault(conn.quiz_id, {})[conn.conn_id] = sender
        if conn.read_only:
            return
        key = (conn.quiz_id, conn.user_id)
        self._present[key] = conn.conn_id
        if (timer := self._grace.pop(key, None)) is not None:
            timer.cancel()

    def senders(self, quiz_id: str) -> list[Sender]:
        return list(self._quizzes.get(quiz_id, {}).values())

    def broadcast(self, quiz_id: str, data: bytes, *, leaderboard: bool) -> None:
        for sender in self.senders(quiz_id):
            sender.send_frame(data, leaderboard=leaderboard)

    def replace(self, conn_id: str) -> None:
        """Close a socket of this node that a newer join took over: the error, then 4001."""
        if (sender := self._senders.get(conn_id)) is not None:
            text = "this quiz was opened on another connection"
            sender.send(
                m.ProtocolError(code=m.ErrorCode.SESSION_REPLACED, message=text, requestType=None)
            )
            sender.close(CLOSE_REPLACED)

    def drop(self, conn: Connection) -> None:
        """Forget a closed socket; its player leaves after the grace unless they join again."""
        if self._senders.pop(conn.conn_id, None) is None or conn.quiz_id is None:
            return
        quiz = self._quizzes[conn.quiz_id]
        del quiz[conn.conn_id]
        if not quiz:
            del self._quizzes[conn.quiz_id]
        key = (conn.quiz_id, conn.user_id)
        if conn.read_only or self._present.get(key) != conn.conn_id:
            return  # joined after the end, or replaced: a newer socket holds the presence
        self._grace[key] = asyncio.create_task(self._leave_later(key, conn.conn_id))

    async def _leave_later(self, key: tuple[str, str], conn_id: str) -> None:
        await asyncio.sleep(self._grace_s)  # a writing join of the player cancels it here
        del self._grace[key], self._present[key]
        try:
            await self._store.leave(*key, conn_id)
        except Exception:  # a timer has no caller to raise to; the presence sweep drops it later
            log.warning("the leave of a closed connection failed", exc_info=True)
