# AI-ASSISTED: relays one quiz's published broadcasts to this node's sockets, with rank_update.
"""A broadcast arrives encoded once, as ``{"frame": …, "ranks": …}`` (docs/spec/redis.md §5); the
same frame bytes go to every local socket of the quiz. Above ``full_list_max`` players, a local
player outside the top ``top_n`` who scored gets ``rank_update`` from the frame's ``ranks``, and
one whose rank only shifted gets it from ``shifted``: one read for all local players."""

import json
from collections.abc import Collection
from typing import Protocol

from quiz.contracts import messages as m
from quiz.contracts.codec import encode
from quiz.ports.store import Limits, Store

_HEAD, _TAIL = '{"frame":', ',"ranks":'  # user ids hold no quotes: the last _TAIL ends the frame


class Sockets(Protocol):  # this node's sockets, by quiz
    def broadcast(self, quiz_id: str, data: bytes, *, leaderboard: bool) -> None: ...

    def players(self, quiz_id: str) -> Collection[str]: ...

    def send_to(self, quiz_id: str, user_id: str, data: bytes) -> None: ...


class Relay:
    """The broadcasts of one quiz on this node."""

    def __init__(self, quiz_id: str, store: Store, sockets: Sockets, limits: Limits) -> None:
        self._quiz_id, self._store, self._sockets, self._limits = quiz_id, store, sockets, limits
        self._sent: dict[str, tuple[int, int]] = {}  # user id → the (rank, score) it last got
        self._player_count = 0
        self._moved = False  # a leaderboard went out since the last shifted read

    def relay(self, message: str) -> None:
        """Queue the frame on every local socket; scorers outside the top get their rank."""
        parsed = json.loads(message)
        frame, data = parsed["frame"], message[len(_HEAD) : message.rindex(_TAIL)].encode()
        leaderboard = frame["type"] == "leaderboard"
        self._sockets.broadcast(self._quiz_id, data, leaderboard=leaderboard)
        if not leaderboard:
            return
        self._player_count, self._moved = frame["playerCount"], True
        local = self._sockets.players(self._quiz_id)
        for user_id, rank, score in parsed["ranks"]:
            if user_id in local:
                self._send(user_id, rank, score, frame["seq"])

    async def shifted(self) -> None:
        """Send each local player outside the top its rank, if it moved since it last got one."""
        if not self._moved or self._player_count <= self._limits.full_list_max:
            return
        self._moved = False
        if not (users := list(self._sockets.players(self._quiz_id))):
            return
        ranks = await self._store.ranks_of(self._quiz_id, users)
        self._player_count, sent, self._sent = ranks.player_count, self._sent, {}
        for user_id, row in ranks.rows.items():
            if row is None or row.rank <= self._limits.top_n:
                continue  # not a player, or in the frame's entries
            self._sent[user_id] = sent.get(user_id, (0, 0))
            if self._sent[user_id] != (row.rank, row.score):
                self._send(user_id, row.rank, row.score, ranks.at_seq)

    def _send(self, user_id: str, rank: int, score: int, at_seq: int) -> None:
        self._sent[user_id] = (rank, score)
        update = m.RankUpdate(atSeq=at_seq, rank=rank, score=score, playerCount=self._player_count)
        self._sockets.send_to(self._quiz_id, user_id, encode(update))
