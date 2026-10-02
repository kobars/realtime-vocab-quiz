# AI-ASSISTED: relays one quiz's broadcasts and control messages to this node's sockets.
"""A broadcast arrives encoded once, as ``{"frame": …, "ranks": …}`` (docs/spec/redis.md §5); the
same frame bytes go to every local socket of the quiz. Above ``full_list_max`` players, a local
player outside the top ``top_n`` who scored gets ``rank_update`` from the frame's ``ranks``, and
one whose rank only shifted gets it from ``shifted``: reads of at most ``RANKS_BATCH`` local
players each. The ``quiz_ended`` frame goes to each local player with its own final rank in
``you``. A ``session_replaced`` control message closes that connection if it is on this node."""

import json
from collections.abc import Collection, Mapping
from contextlib import suppress
from typing import Any, Protocol

from quiz.contracts import messages as m
from quiz.contracts.codec import encode
from quiz.ports.store import Limits, Place, Ranks, Store

_HEAD, _TAIL = '{"frame":', ',"ranks":'  # user ids hold no quotes: the last _TAIL ends the frame
_NO_YOU = b"null}"  # an encoded QuizEnded ends in "you":null}, as you is its last field
RANKS_BATCH = 1_000  # players per shifted rank read: Redis runs other quizzes between batches


class Sockets(Protocol):  # this node's sockets, by quiz
    def broadcast(self, quiz_id: str, data: bytes, *, leaderboard: bool) -> None: ...

    def players(self, quiz_id: str) -> Collection[str]: ...

    def send_to(self, quiz_id: str, user_id: str, data: bytes) -> None: ...

    def replace(self, conn_id: str) -> None: ...


class Relay:
    """The broadcasts of one quiz on this node."""

    def __init__(self, quiz_id: str, store: Store, sockets: Sockets, limits: Limits) -> None:
        self._quiz_id, self._store, self._sockets, self._limits = quiz_id, store, sockets, limits
        self._sent: dict[str, tuple[int, int, int]] = {}  # user id → (atSeq, rank, score) it got
        self._player_count = 0
        self._seq = self._read_seq = -1  # the newest leaderboard relayed; the last shifted read
        self._repaired = -1  # the newest seq of a repair snapshot: no leaderboard at or below it

    async def relay(self, message: str) -> bool:
        """Queue the frame on every local socket; True once it was the last one, ``quiz_ended``."""
        parsed = json.loads(message)
        if parsed.get("type") == "session_replaced":  # control: a join replaced that connection
            self._sockets.replace(parsed["connId"])  # nothing when it is not on this node
            return False
        frame, data = parsed["frame"], message[len(_HEAD) : message.rindex(_TAIL)].encode()
        if frame["type"] == "quiz_ended":
            await self._ended(frame, data)
            return True
        if frame["seq"] <= self._repaired:  # older than a snapshot sent: seq < lastSeq resyncs
            return False
        self._sockets.broadcast(self._quiz_id, data, leaderboard=True)
        self._player_count, self._seq = frame["playerCount"], frame["seq"]
        local = self._sockets.players(self._quiz_id)
        for entry in frame["entries"]:  # rows the frame showed: an older rank read must not undo
            if (user_id := entry["userId"]) in local:
                self._sent[user_id] = (frame["seq"], entry["rank"], entry["score"])
        for user_id, rank, score in parsed["ranks"]:
            if user_id in local:
                self._send(user_id, rank, score, frame["seq"])
        return False

    def repaired(self, ranks: Ranks) -> None:
        """After a resubscribe, each local player got its snapshot and rank at ``ranks``: skip the
        queued leaderboards it holds and track ranks from there, as ``seq`` may have gone back."""
        self._repaired = self._seq = self._read_seq = ranks.at_seq
        self._player_count = ranks.player_count
        self._sent = {
            user_id: (ranks.at_seq, row.rank, row.score)
            for user_id, row in ranks.rows.items()
            if row is not None
        }

    async def shifted(self) -> None:
        """Send each local player outside the top its rank, if it moved since it last got one."""
        if self._seq <= self._read_seq or self._player_count <= self._limits.full_list_max:
            return
        if not (users := list(self._sockets.players(self._quiz_id))):
            return
        self._sent = {user_id: self._sent[user_id] for user_id in users if user_id in self._sent}
        for start in range(0, len(users), RANKS_BATCH):  # one short script per batch, not one long
            ranks = await self._store.ranks_of(self._quiz_id, users[start : start + RANKS_BATCH])
            if start == 0:  # a later batch may read past a frame that this one did not see
                self._read_seq = ranks.at_seq
            self._player_count = ranks.player_count
            for user_id, row in ranks.rows.items():
                last = self._sent.get(user_id, (-1, 0, 0))
                if last[0] >= ranks.at_seq:  # a frame relayed during the read sent a newer value
                    continue
                if row is None or row.rank <= self._limits.top_n:  # the frame shows it
                    self._sent.pop(user_id, None)
                elif last[1:] != (row.rank, row.score):
                    self._send(user_id, row.rank, row.score, ranks.at_seq)

    async def _ended(self, frame: dict[str, Any], data: bytes) -> None:
        users = list(self._sockets.players(self._quiz_id))
        rows: Mapping[str, Place | None] = {}
        with suppress(ConnectionError, TimeoutError):  # the end still goes out, with you: null
            rows = (await self._store.ranks_of(self._quiz_id, users)).rows
        # The shared part is validated and encoded once; each player's bytes end in its own you.
        head = encode(m.QuizEnded.model_validate(frame)).removesuffix(_NO_YOU) if rows else b""
        for user_id in users:
            own = data
            if (row := rows.get(user_id)) is not None:
                own = head + m.You(rank=row.rank, score=row.score).model_dump_json().encode() + b"}"
            self._sockets.send_to(self._quiz_id, user_id, own)

    def _send(self, user_id: str, rank: int, score: int, at_seq: int) -> None:
        self._sent[user_id] = (at_seq, rank, score)
        update = m.RankUpdate(atSeq=at_seq, rank=rank, score=score, playerCount=self._player_count)
        self._sockets.send_to(self._quiz_id, user_id, encode(update))
