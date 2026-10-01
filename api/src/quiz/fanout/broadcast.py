# AI-ASSISTED: relays one quiz's published broadcasts to this node's sockets, with rank_update.
"""A broadcast arrives encoded once, as ``{"frame": …, "ranks": …}`` (docs/spec/redis.md §5); the
same frame bytes go to every local socket of the quiz. Above ``full_list_max`` players, a local
player outside the top ``top_n`` who scored gets ``rank_update`` from the frame's ``ranks``, and
one whose rank only shifted gets it from ``shifted``: one read for all local players. The
``quiz_ended`` frame goes to each local player with its own final rank in ``you``."""

import json
from collections.abc import Collection, Mapping
from contextlib import suppress
from typing import Any, Protocol

from quiz.contracts import messages as m
from quiz.contracts.codec import encode
from quiz.ports.store import Limits, Row, Store

_HEAD, _TAIL = '{"frame":', ',"ranks":'  # user ids hold no quotes: the last _TAIL ends the frame


class Sockets(Protocol):  # this node's sockets, by quiz
    def broadcast(self, quiz_id: str, data: bytes, *, leaderboard: bool) -> None: ...

    def players(self, quiz_id: str) -> Collection[str]: ...

    def send_to(self, quiz_id: str, user_id: str, data: bytes) -> None: ...


class Relay:
    """The broadcasts of one quiz on this node."""

    def __init__(self, quiz_id: str, store: Store, sockets: Sockets, limits: Limits) -> None:
        self._quiz_id, self._store, self._sockets, self._limits = quiz_id, store, sockets, limits
        self._sent: dict[str, tuple[int, int, int]] = {}  # user id → (atSeq, rank, score) it got
        self._player_count = 0
        self._seq = self._read_seq = -1  # the newest leaderboard relayed; the last shifted read

    async def relay(self, message: str) -> bool:
        """Queue the frame on every local socket; True once it was the last one, ``quiz_ended``."""
        parsed = json.loads(message)
        frame, data = parsed["frame"], message[len(_HEAD) : message.rindex(_TAIL)].encode()
        if frame["type"] == "quiz_ended":
            await self._ended(frame, data)
            return True
        self._sockets.broadcast(self._quiz_id, data, leaderboard=True)
        self._player_count, self._seq = frame["playerCount"], frame["seq"]
        local = self._sockets.players(self._quiz_id)
        for user_id, rank, score in parsed["ranks"]:
            if user_id in local:
                self._send(user_id, rank, score, frame["seq"])
        return False

    async def shifted(self) -> None:
        """Send each local player outside the top its rank, if it moved since it last got one."""
        if self._seq <= self._read_seq or self._player_count <= self._limits.full_list_max:
            return
        if not (users := list(self._sockets.players(self._quiz_id))):
            return
        ranks = await self._store.ranks_of(self._quiz_id, users)
        self._player_count, self._read_seq = ranks.player_count, ranks.at_seq
        sent, self._sent = self._sent, {}
        for user_id, row in ranks.rows.items():
            last = sent.get(user_id, (-1, 0, 0))
            if last[0] >= ranks.at_seq:  # a frame relayed during the read sent a newer value
                self._sent[user_id] = last
            elif row is not None and row.rank > self._limits.top_n:  # else the frame shows it
                self._sent[user_id] = last
                if last[1:] != (row.rank, row.score):
                    self._send(user_id, row.rank, row.score, ranks.at_seq)

    async def _ended(self, frame: dict[str, Any], data: bytes) -> None:
        users = list(self._sockets.players(self._quiz_id))
        rows: Mapping[str, Row | None] = {}
        with suppress(ConnectionError, TimeoutError):  # the end still goes out, with you: null
            rows = (await self._store.ranks_of(self._quiz_id, users)).rows
        for user_id in users:
            own = data
            if (row := rows.get(user_id)) is not None:
                you = m.You(rank=row.rank, score=row.score)
                own = encode(m.QuizEnded.model_validate({**frame, "you": you}))
            self._sockets.send_to(self._quiz_id, user_id, own)

    def _send(self, user_id: str, rank: int, score: int, at_seq: int) -> None:
        self._sent[user_id] = (at_seq, rank, score)
        update = m.RankUpdate(atSeq=at_seq, rank=rank, score=score, playerCount=self._player_count)
        self._sockets.send_to(self._quiz_id, user_id, encode(update))
