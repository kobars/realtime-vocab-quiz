# AI-ASSISTED: the Redis store: each port method is one Lua script over the keys of quiz_keys().
"""The store port on Redis. Scripts read the Redis clock; Python passes no time or points.

The client must decode responses (``decode_responses=True``). A redis-py connection or
timeout error leaves as the built-in ``ConnectionError`` or ``TimeoutError``, so callers
need no redis import to tell an unreachable store from a fault.
"""

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from typing import Literal, cast

from redis import exceptions as redis_errors
from redis.asyncio import Redis

from quiz.adapters.redis.keys import quiz_keys
from quiz.adapters.redis.scripts import Reply, Scripts
from quiz.contracts.messages import FULL_LIST_MAX
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.events import AnswerScored
from quiz.domain.session import Question
from quiz.ports import store as port
from quiz.ports.store import Created, Joined, Limits


def _ok(name: str, reply: Reply) -> Reply:
    """Raise an error code as ``DomainError`` (``QUIZ_ENDED`` carries ``endSeq``); others pass."""
    try:
        code = ErrorCode(str(reply[0]))
    except ValueError:
        return reply
    end = reply[1] if code is ErrorCode.QUIZ_ENDED and len(reply) > 1 else None
    raise DomainError(code, f"{name} refused", end_seq=None if end is None else int(end))


@contextmanager
def _reachable() -> Iterator[None]:
    """Re-raise redis-py's connection and timeout errors as the built-in ones."""
    try:
        yield
    except redis_errors.TimeoutError as error:
        raise TimeoutError(str(error)) from error
    except redis_errors.ConnectionError as error:
        raise ConnectionError(str(error)) from error


class RedisStore:
    def __init__(self, client: Redis, *, prefix: str = "", limits: Limits | None = None) -> None:
        self._client = client
        self.limits = limits or Limits()  # for the tick and snapshot scripts, through ARGV
        self._scripts = Scripts(client)
        self._prefix = prefix

    async def start(self) -> None:
        """Load the scripts; call once before the first command."""
        await self._scripts.load()

    async def _run(self, name: str, quiz_id: str, *args: str | int) -> Reply:
        keys = quiz_keys(quiz_id, self._prefix)
        with _reachable():
            reply = await self._scripts.call(name, keys, *args)
        return _ok(name, reply)

    async def create_quiz(
        self, quiz_id: str, questions: tuple[Question, ...], *, window_ms: int, time_limit_ms: int
    ) -> Created:
        ids = json.dumps([q.question_id for q in questions])
        answers = json.dumps([q.correct_choice for q in questions])
        reply = await self._run("create_quiz", quiz_id, ids, answers, time_limit_ms, window_ms)
        start_ms, deadline_ms = (int(v or 0) for v in reply[1:3])
        return Created(start_ms, deadline_ms)

    async def join(self, quiz_id: str, user_id: str, display_name: str, conn_id: str) -> Joined:
        reply = await self._run("join", quiz_id, user_id, display_name, conn_id)
        seq, cursor, cursor_open, finished, total, count, limit, left = (
            int(v or 0) for v in reply[1:9]
        )
        name, replaced = reply[9], reply[10] if len(reply) > 10 else None  # noqa: PLR2004
        return Joined(
            seq,
            cursor,
            bool(cursor_open),
            bool(finished),
            total,
            count,
            limit,
            left,
            str(name),
            None if replaced is None else str(replaced),
        )

    async def leave(self, quiz_id: str, user_id: str, conn_id: str) -> bool:
        return (await self._run("leave", quiz_id, user_id, conn_id))[0] == "ok"

    async def serve_next(
        self, quiz_id: str, user_id: str, question_index: int, conn_id: str
    ) -> port.Served | port.Finished:
        reply = await self._run("serve_question", quiz_id, user_id, question_index, conn_id)
        kind, index, question_id, left, seq = reply[1:6]
        if kind == "finished":
            total, rank, count = (int(v or 0) for v in reply[6:9])
            return port.Finished(int(seq or 0), total, rank, count)
        return port.Served(int(seq or 0), int(index or 0), str(question_id), int(left or 0))

    async def apply_answer(  # noqa: PLR0913, PLR0917 - the port's signature
        self,
        quiz_id: str,
        user_id: str,
        question_index: int,
        choice_index: int,
        submission_id: str,
        conn_id: str,
    ) -> port.Answered:
        args = (user_id, question_index, choice_index, submission_id, conn_id)
        reply = await self._run("score_answer", quiz_id, *args)
        i, choice, key, correct, late, points, total, seq, back = (int(v or 0) for v in reply[1:10])
        flags = bool(correct), bool(late)
        result = AnswerScored(user_id, i, submission_id, choice, key, *flags, points, total, seq)
        return port.Answered(result, bool(back))

    async def _read(
        self, quiz_id: str, offset: int, limit: int, user_ids: Sequence[str] = ()
    ) -> tuple[port.Snapshot, dict[str, port.Row | None]]:
        """The standings at one seq (``limit`` 0: the broadcast rows) and each asked user's row."""
        reply = await self._run("read_standings", quiz_id, offset, limit, *user_ids)
        seq, count, online, status = reply[1:5]
        rows = cast("list[list[str]]", reply[5])
        asked = cast("list[list[str] | None]", reply[6])
        table = tuple(port.Row(int(rank), uid, name, int(total)) for rank, uid, name, total in rows)
        state = cast("Literal['open', 'ended']", status)
        snap = port.Snapshot(int(seq or 0), state, int(count or 0), int(online or 0), table, None)
        return snap, {
            uid: None if hit is None else port.Row(int(hit[0]), uid, hit[1], int(hit[2]))
            for uid, hit in zip(user_ids, asked, strict=True)
        }

    async def standings_page(self, quiz_id: str, offset: int, limit: int) -> port.Page:
        if offset < 0 or not 1 <= limit <= FULL_LIST_MAX:
            msg = f"page offset {offset}, limit {limit}"
            raise DomainError(ErrorCode.INVALID_MESSAGE, msg)
        snap, _ = await self._read(quiz_id, offset, limit)
        return port.Page(snap.at_seq, snap.player_count, snap.status == "ended", snap.rows)

    async def read_seq(self, quiz_id: str) -> int | None:
        with _reachable():
            seq = await self._client.get(quiz_keys(quiz_id, self._prefix).seq)
        return None if seq is None else int(seq)

    async def ranks_of(self, quiz_id: str, user_ids: Sequence[str]) -> port.Ranks:
        snap, asked = await self._read(quiz_id, 0, 0, user_ids)
        return port.Ranks(snap.at_seq, snap.player_count, asked)

    async def snapshot(self, quiz_id: str, user_id: str | None) -> port.Snapshot:
        snap, asked = await self._read(quiz_id, 0, 0, () if user_id is None else (user_id,))
        return replace(snap, you=None if user_id is None else asked[user_id])

    async def publish_if_dirty(self, quiz_id: str, node_id: str) -> port.Publish:
        reply = await self._run("publish_leaderboard", quiz_id, node_id)
        value = reply[1] if len(reply) > 1 else None
        match reply[0]:
            case "published" | "ended" as status:
                return port.Publish(status, None if value is None else int(value))
            case "busy":
                return port.Publish("busy", retry_ms=int(value or 0))
            case "clean":
                return port.Publish("clean")
            case status:
                raise ValueError(status)

    async def end_quiz(self, quiz_id: str, reason: Literal["deadline", "host"]) -> port.End:
        reply = await self._run("end_quiz", quiz_id, reason)
        match reply[0]:
            case "ended":
                return port.End("ended", int(reply[1] or 0))
            case "marked" | "not_due" as status:
                return port.End(status)
            case status:
                raise ValueError(status)

    async def renew_presence(
        self, quiz_id: str, stale_ms: int, pairs: Sequence[tuple[str, str]]
    ) -> port.Renewed:
        raise NotImplementedError

    async def mark_dirty(self, quiz_id: str) -> None:
        raise NotImplementedError
