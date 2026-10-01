# AI-ASSISTED: the joined sockets of this node per quiz, session replacement and the leave grace.
"""Which socket of this node serves which quiz: a broadcast reaches every local socket of the
quiz, and a connection that another join replaced is closed here when it lives on this node.
Sockets are tracked from the accept on, so a replacement also closes a socket whose own join
reply has not reached the node yet: the store took that join first, its reply comes last.

A joined socket that drops keeps its presence for the grace period, then ``leave`` runs with its
own connection id. Timers are per connection and nothing cancels them: ``leave`` compares the
connection id, so the store alone decides whether the socket still holds the presence. A rejoin
or a replacing join makes the older socket's leave stale, and a read-only join (after the end)
writes no presence, so the earlier socket's leave still removes it (docs/spec/redis.md §3, §3.1)."""

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
        self._senders: dict[str, Sender] = {}  # conn_id → its sender, joined or not
        self._quizzes: dict[str, dict[str, Sender]] = {}  # quiz_id → conn_id → sender
        self._leaving: set[asyncio.Task[None]] = set()  # grace timers, held until done

    def track(self, conn_id: str, sender: Sender) -> None:
        """Record an accepted socket, before its join."""
        self._senders[conn_id] = sender

    def bind(self, conn: Connection, sender: Sender) -> None:
        """Record a joined socket."""
        if conn.quiz_id is None:
            return
        self._senders[conn.conn_id] = sender
        self._quizzes.setdefault(conn.quiz_id, {})[conn.conn_id] = sender

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
        if conn.read_only:
            return  # joined after the end: no presence to remove
        timer = asyncio.create_task(self._leave_later(conn.quiz_id, conn.user_id, conn.conn_id))
        self._leaving.add(timer)
        timer.add_done_callback(self._leaving.discard)

    async def _leave_later(self, quiz_id: str, user_id: str, conn_id: str) -> None:
        await asyncio.sleep(self._grace_s)
        try:
            await self._store.leave(quiz_id, user_id, conn_id)
        except Exception:  # a timer has no caller to raise to; the presence sweep drops it later
            log.warning("the leave of a closed connection failed", exc_info=True)
