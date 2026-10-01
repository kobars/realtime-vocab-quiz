# AI-ASSISTED: the coalescing tick of docs/spec/redis.md §5, per quiz while it has local sockets.
"""While this node holds a socket of a quiz, one loop runs for that quiz: it relays each of the
quiz's broadcasts, calls ``publish_if_dirty`` every tick (after ``busy``, once the token expires)
and sends the shifted ranks at most once a second. The first local socket starts the loop; the
last one cancels it, which also unsubscribes. The loop ends after it relayed ``quiz_ended``."""

import asyncio
import logging
from collections.abc import AsyncIterator

from quiz.domain.errors import DomainError, ErrorCode
from quiz.fanout.broadcast import Relay, Sockets
from quiz.ports.store import FeedStore

log = logging.getLogger(__name__)
SHIFT_S = 1.0  # a rank that only shifted is sent at most this often


class Ticker:
    def __init__(self, store: FeedStore, sockets: Sockets, node_id: str) -> None:
        self._store, self._sockets, self._node_id = store, sockets, node_id
        self._tick_s = store.limits.tick_ms / 1000
        self._loops: dict[str, asyncio.Task[None]] = {}

    def open(self, quiz_id: str) -> None:
        if (task := self._loops.get(quiz_id)) is None or task.done():
            self._loops[quiz_id] = asyncio.create_task(self._run(quiz_id))

    def close(self, quiz_id: str) -> None:
        if (task := self._loops.pop(quiz_id, None)) is not None:
            task.cancel()

    async def stop(self) -> None:
        """Cancel every loop: the app's shutdown hook."""
        tasks = [self._loops.pop(quiz_id) for quiz_id in list(self._loops)]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, quiz_id: str) -> None:
        relay = Relay(quiz_id, self._store, self._sockets, self._store.limits)
        try:
            async with self._store.subscribe(quiz_id) as messages:
                relaying = asyncio.create_task(_relay(relay, messages))
                try:
                    subscribed_at = await self._store.read_seq(quiz_id) or 0
                    end_seq = await self._tick(quiz_id, relay)
                    if end_seq is not None and end_seq > subscribed_at:
                        await relaying  # quiz_ended was published after the subscribe
                finally:
                    relaying.cancel()
                    await asyncio.gather(relaying, return_exceptions=True)
        except Exception:
            log.exception("fan-out of quiz %s stopped", quiz_id)

    async def _tick(self, quiz_id: str, relay: Relay) -> int | None:
        """Tick until the quiz ended (its end seq) or is gone (None)."""
        clock = asyncio.get_running_loop().time
        shift_at = clock() + SHIFT_S
        while True:
            wait_s = self._tick_s
            try:
                result = await self._store.publish_if_dirty(quiz_id, self._node_id)
                if result.status == "ended":
                    if result.seq is not None:
                        return result.seq
                    # a host mark not yet announced: retry until the deadline is due (redis.md §3.1)
                    if (end := await self._store.end_quiz(quiz_id, "deadline")).status == "ended":
                        return end.seq
                if result.status == "busy":
                    wait_s = (result.retry_ms + 1) / 1000
                if clock() >= shift_at:
                    shift_at = clock() + SHIFT_S
                    await relay.shifted()
            except DomainError as error:
                if error.code is ErrorCode.QUIZ_NOT_FOUND:  # expired, or lost by the store
                    return None
                raise
            except ConnectionError, TimeoutError:
                log.warning("tick of quiz %s: store unreachable", quiz_id)
            await asyncio.sleep(wait_s)


async def _relay(relay: Relay, messages: AsyncIterator[str]) -> None:
    async for message in messages:
        try:
            if await relay.relay(message):
                return
        except Exception:
            log.exception("broadcast not relayed")
