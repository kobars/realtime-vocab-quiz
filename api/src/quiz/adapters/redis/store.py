# AI-ASSISTED: the Redis store: one Lua script per port method; the feed is events plus control.
"""The store port on Redis. Scripts read the Redis clock; Python passes no time or points.

The client must decode responses (``decode_responses=True``). A redis-py connection or
timeout error leaves as the built-in ``ConnectionError`` or ``TimeoutError``, so callers
need no redis import to tell an unreachable store from a fault.
"""

import json
from collections.abc import AsyncGenerator, AsyncIterator, Iterator, Sequence
from contextlib import aclosing, asynccontextmanager, contextmanager
from dataclasses import replace
from itertools import chain
from typing import Literal, cast

from redis import exceptions as redis_errors
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from quiz.adapters.redis.keys import quiz_keys
from quiz.adapters.redis.scripts import Reply, Scripts
from quiz.contracts.messages import FULL_LIST_MAX
from quiz.domain.errors import DomainError, ErrorCode
from quiz.domain.events import AnswerScored
from quiz.domain.session import Question
from quiz.ports import store as port
from quiz.ports.store import Created, Joined, Limits

WAITAOF_TIMEOUT_MS = 2000  # the host end waits this long for the mark's fsync (redis.md §3.1)
SUBSCRIBE_TIMEOUT_S = 5  # subscribe() waits this long for Redis to confirm the subscription
RANKS_ONLY = -1  # read_standings' limit for the asked users' rows alone


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


async def _messages(pubsub: PubSub) -> AsyncGenerator[str]:
    with _reachable():
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield message["data"]
            elif message["type"] == "subscribe":  # redis-py reconnected: messages may be lost
                msg = "the subscription dropped"
                raise ConnectionError(msg)


class RedisStore:
    def __init__(self, client: Redis, *, prefix: str = "", limits: Limits | None = None) -> None:
        self._client = client
        self.limits = limits or Limits()  # for the tick, end and standings scripts, through ARGV
        self._scripts = Scripts(client)
        self._prefix = prefix

    async def start(self) -> None:
        """Load the scripts; call once before the first command."""
        await self._scripts.load()

    async def _run(
        self, name: str, quiz_id: str, *args: str | int, on: Redis | None = None
    ) -> Reply:
        keys = quiz_keys(quiz_id, self._prefix)
        with _reachable():
            reply = await self._scripts.call(name, keys, *args, on=on)
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
        fields = (int(v or 0) for v in reply[1:11])
        i, choice, key, correct, late, points, total, seq, back, replay = fields
        flags = bool(correct), bool(late)
        result = AnswerScored(user_id, i, submission_id, choice, key, *flags, points, total, seq)
        return port.Answered(result, bool(back), bool(replay))

    async def _read(
        self, quiz_id: str, offset: int, limit: int, user_ids: Sequence[str] = ()
    ) -> tuple[port.Snapshot, dict[str, port.Place | None]]:
        """The standings at one seq and each asked user's row.

        ``limit`` 0 reads the broadcast rows, ``RANKS_ONLY`` no rows.
        """
        top_n, full = self.limits.top_n, self.limits.full_list_max
        reply = await self._run("read_standings", quiz_id, offset, limit, top_n, full, *user_ids)
        seq, count, online, status = reply[1:5]
        rows = cast("list[list[str]]", reply[5])
        asked = cast("list[list[int] | None]", reply[6])
        table = tuple(port.Row(int(rank), uid, name, int(total)) for rank, uid, name, total in rows)
        state = cast("Literal['open', 'ended']", status)
        snap = port.Snapshot(int(seq or 0), state, int(count or 0), int(online or 0), table, None)
        return snap, {
            uid: None if hit is None else port.Place(int(hit[0]), int(hit[1]))
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
        snap, asked = await self._read(quiz_id, 0, RANKS_ONLY, user_ids)
        return port.Ranks(snap.at_seq, snap.status, snap.player_count, asked)

    async def snapshot(self, quiz_id: str, user_id: str | None) -> port.Snapshot:
        snap, asked = await self._read(quiz_id, 0, 0, () if user_id is None else (user_id,))
        return replace(snap, you=None if user_id is None else asked[user_id])

    async def publish_if_dirty(self, quiz_id: str, node_id: str) -> port.Publish:
        lim = self.limits
        args = (node_id, lim.tick_ms, lim.top_n, lim.full_list_max)
        reply = await self._run("publish_leaderboard", quiz_id, *args)
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

    @asynccontextmanager
    async def subscribe(self, quiz_id: str) -> AsyncIterator[AsyncIterator[str]]:
        """The quiz's ``events`` and ``control`` channels, entered once Redis confirmed both."""
        keys, pubsub = quiz_keys(quiz_id, self._prefix), self._client.pubsub()
        try:
            async with aclosing(_messages(pubsub)) as messages:
                with _reachable():
                    await pubsub.subscribe(keys.events, keys.control)
                    for _ in range(2):  # one confirmation per channel
                        if await pubsub.get_message(timeout=SUBSCRIBE_TIMEOUT_S) is None:
                            msg = "Redis did not confirm the subscription"
                            raise ConnectionError(msg)
                yield messages
        finally:
            await pubsub.aclose()  # type: ignore[no-untyped-call]

    async def end_quiz(
        self, quiz_id: str, reason: Literal["deadline", "host", "mark"], *, on: Redis | None = None
    ) -> port.End:
        reply = await self._run("end_quiz", quiz_id, reason, self.limits.top_n, on=on)
        match reply[0]:
            case "ended":
                return port.End("ended", int(reply[1] or 0))
            case "marked" | "not_due" as status:
                return port.End(status)
            case status:
                raise ValueError(status)

    async def end_by_host(self, quiz_id: str) -> int:
        async with self._client.client() as conn:  # WAITAOF counts this connection's writes only
            end = await self.end_quiz(quiz_id, "mark", on=conn)  # rewritten when it exists
            if end.status == "marked":
                if await self._fsynced(conn) < 1:
                    raise DomainError(ErrorCode.UNAVAILABLE, "the end mark was not fsynced")
                end = await self.end_quiz(quiz_id, "host", on=conn)
        return port.announced(end)

    async def _fsynced(self, conn: Redis) -> int:
        """``WAITAOF 1 0 2000`` on ``conn``: 1 when the local AOF fsync covers its writes."""
        with _reachable():
            local, _replicas = await conn.waitaof(1, 0, WAITAOF_TIMEOUT_MS)
        return int(local)

    async def renew_presence(
        self, quiz_id: str, stale_ms: int, pairs: Sequence[tuple[str, str]]
    ) -> port.Renewed:
        reply = await self._run("renew_presence", quiz_id, stale_ms, *chain.from_iterable(pairs))
        if reply[0] == "ended":
            return port.Renewed("ended")
        return port.Renewed("renewed", int(reply[1] or 0))

    async def mark_dirty(self, quiz_id: str) -> None:
        raise NotImplementedError
