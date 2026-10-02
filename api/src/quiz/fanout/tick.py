# AI-ASSISTED: the coalescing tick of docs/spec/redis.md §5, per quiz while it has local sockets.
"""While this node holds a socket of a quiz, one loop runs for that quiz: it relays each of the
quiz's broadcasts, calls ``publish_if_dirty`` every tick (after ``busy``, once the token expires)
and sends the shifted ranks at most once a second. The first local socket starts the loop; the
last one cancels it, which also unsubscribes. The loop ends after it relayed ``quiz_ended``.
When the subscription fails, the loop subscribes again after a full-jitter backoff and sends each
local player a snapshot: pub/sub does not replay what the drop lost (§5). A tick that finds the
store unreachable keeps the subscription and waits the same backoff, which grows with each
failure in a row and starts over after a tick that went through."""

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from functools import partial

from quiz.app.service import OUTAGE_LOG_INTERVAL_MS, QuizService, rank_update
from quiz.contracts.codec import encode
from quiz.domain.errors import DomainError, ErrorCode
from quiz.fanout.broadcast import Relay, Sockets, with_you, without_you
from quiz.obs import metrics
from quiz.obs.logs import Throttle
from quiz.ports.clock import Clock
from quiz.ports.store import FeedStore, Publish

log = logging.getLogger(__name__)
SHIFT_S = 1.0  # a rank that only shifted is sent at most this often
END_GRACE_S = 0.5  # how long an end seen at the subscribe seq waits for its quiz_ended
BACKOFF_BASE_MS, BACKOFF_CAP_MS = 250, 10_000  # full jitter, as the client reconnects (protocol §7)


def backoff_s(attempt: int) -> float:
    cap_ms = min(BACKOFF_CAP_MS, BACKOFF_BASE_MS << attempt)
    return random.random() * cap_ms / 1000  # noqa: S311 - spreads retries, not a secret


class Ticker:
    def __init__(  # noqa: PLR0913 - the loop's collaborators and two node settings
        self,
        store: FeedStore,
        sockets: Sockets,
        service: QuizService,
        node_id: str,
        clock: Clock,
        *,
        max_quizzes: int | None = None,
    ) -> None:
        """``clock`` paces the warning of an unreachable store: one per interval for every quiz.
        ``max_quizzes`` is how many subscriptions the store holds at once; None for no limit."""
        self._store, self._sockets, self._service = store, sockets, service
        self._node_id, self._max_quizzes = node_id, max_quizzes
        self._outage_log = Throttle(clock, OUTAGE_LOG_INTERVAL_MS)
        self._tick_s = store.limits.tick_ms / 1000
        self._loops: dict[str, asyncio.Task[None]] = {}  # the running loops
        self._holds: dict[str, int] = {}  # per quiz this node does not follow: joins in flight

    @contextmanager
    def admission(self, quiz_id: str) -> Iterator[bool]:
        """Whether this node can follow the quiz: it does, or a subscription is free, which the
        join then holds while it runs, so concurrent joins never pass the limit together. The bind
        that follows the join, with no await in between, opens the loop. A refusal is counted."""
        if self._max_quizzes is None or self._following(quiz_id):
            yield True
            return
        if quiz_id not in self._holds and self._taken() >= self._max_quizzes:
            metrics.FEED_SUBSCRIBE_FAILURES.labels("limit").inc()
            yield False
            return
        self._holds[quiz_id] = self._holds.get(quiz_id, 0) + 1
        try:
            yield True
        finally:
            if left := self._holds[quiz_id] - 1:
                self._holds[quiz_id] = left
            else:
                del self._holds[quiz_id]

    def _taken(self) -> int:
        """The subscriptions in use or held by a join in flight: a loop leaves ``_loops`` when
        it ends (or is closed), so this needs no scan of the loops."""
        return len(self._loops) + sum(quiz_id not in self._loops for quiz_id in self._holds)

    def _following(self, quiz_id: str) -> bool:
        return (task := self._loops.get(quiz_id)) is not None and not task.done()

    def open(self, quiz_id: str) -> None:
        """Start the quiz's loop unless it runs. Past the limit (a read-only join of an ended
        quiz, or a refused join on a bound socket) no loop starts: neither needs live updates."""
        if (task := self._loops.get(quiz_id)) is not None:
            if not task.done():
                return
            del self._loops[quiz_id]  # ended; its done callback may not have run yet
        if self._max_quizzes is not None and self._taken() >= self._max_quizzes:
            log.info("quiz %s: every subscription is taken, so no loop starts", quiz_id)
            return
        task = self._loops[quiz_id] = asyncio.create_task(self._run(quiz_id))
        task.add_done_callback(partial(self._ended, quiz_id))

    def _ended(self, quiz_id: str, task: asyncio.Task[None]) -> None:
        if self._loops.get(quiz_id) is task:  # not a newer loop of the same quiz
            del self._loops[quiz_id]

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
        # The cached standings and pages are this node's only while it follows the quiz: a quiz
        # id can be created again once its quiz expired, and a cached page outlives an end.
        self._service.drop_cache(quiz_id)
        try:
            await self._follow(quiz_id)
        finally:
            self._service.drop_cache(quiz_id)

    async def _follow(self, quiz_id: str) -> None:
        relay = Relay(quiz_id, self._store, self._sockets, self._store.limits)
        progress = asyncio.Event()  # set by a relayed broadcast or a tick that went through
        attempt, failed = 0, False
        while True:
            subscribed = False
            try:
                async with self._store.subscribe(quiz_id) as messages:
                    subscribed = True
                    if failed:
                        await self._repair(quiz_id, relay)
                    await self._serve(quiz_id, relay, messages, progress)
            except Exception as error:
                if not subscribed:
                    metrics.FEED_SUBSCRIBE_FAILURES.labels("error").inc()
                if isinstance(error, DomainError) and error.code is ErrorCode.QUIZ_NOT_FOUND:
                    return  # expired, or lost by the store: also from the repair's read (§5)
                log.exception("fan-out of quiz %s failed: subscribing again", quiz_id)
            else:
                return
            if progress.is_set():
                progress.clear()
                attempt = 0
            await asyncio.sleep(backoff_s(attempt))
            attempt, failed = attempt + 1, True

    async def _serve(
        self, quiz_id: str, relay: Relay, messages: AsyncIterator[str], progress: asyncio.Event
    ) -> None:
        """Relay and tick until the quiz ended; raise when either one fails or the quiz is gone."""
        relaying = asyncio.create_task(_relay(relay, messages, progress))
        try:
            subscribed_at = await self._store.read_seq(quiz_id) or 0
            ticking = asyncio.create_task(self._tick(quiz_id, relay, progress))
            try:
                await asyncio.wait((relaying, ticking), return_when=asyncio.FIRST_COMPLETED)
                if relaying.done():
                    relaying.result()  # raises when the feed failed
                    return  # quiz_ended was relayed
                end_seq = ticking.result()
                if end_seq is not None and end_seq > subscribed_at:
                    await relaying  # quiz_ended was published after the subscribe
                else:  # at or before the seq read: in the feed already if after the subscribe
                    await asyncio.wait({relaying}, timeout=END_GRACE_S)
                    if relay.ending:  # it holds quiz_ended: let it reach every local player
                        await relaying
            finally:
                ticking.cancel()
                await asyncio.gather(ticking, return_exceptions=True)
        finally:
            relaying.cancel()
            await asyncio.gather(relaying, return_exceptions=True)

    async def _repair(self, quiz_id: str, relay: Relay) -> None:
        """Send each local player its standing, as for a resync, before relaying again. The
        shared snapshot is built and encoded once; each player's bytes end in its own ``you``."""
        self._service.drop_cache(quiz_id)
        users = list(self._sockets.players(quiz_id))
        ranks, shared = await self._service.standings(quiz_id, users)
        head = without_you(shared)
        for user_id, row in ranks.rows.items():
            you = None if row is None else row.you()
            self._sockets.send_to(quiz_id, user_id, with_you(head, you))
            if you is not None and (update := rank_update(shared, you)) is not None:
                self._sockets.send_to(quiz_id, user_id, encode(update))
        relay.repaired(ranks)

    async def _tick(self, quiz_id: str, relay: Relay, progress: asyncio.Event) -> int | None:
        """Tick until the quiz ended: the seq of its ``quiz_ended``, if the store gave one."""
        clock = asyncio.get_running_loop().time
        shift_at, failures = clock() + SHIFT_S, 0
        while True:
            wait_s = self._tick_s
            try:
                with metrics.TICK_DURATION.time():
                    result = await self._publish(quiz_id)
                    progress.set()
                    failures = 0
                    if (
                        result.status == "ended"
                        and (end := await self._end(quiz_id, result)) is not None
                    ):
                        return end
                    if result.status == "busy":
                        wait_s = (result.retry_ms + 1) / 1000
                    if clock() >= shift_at:
                        shift_at = clock() + SHIFT_S
                        await relay.shifted()
            except ConnectionError, TimeoutError:
                failures += 1
                wait_s = max(wait_s, backoff_s(failures))
                if self._outage_log.due():
                    log.warning("tick of quiz %s: store unreachable", quiz_id)
            await asyncio.sleep(wait_s)

    async def _end(self, quiz_id: str, result: Publish) -> int | None:
        """The seq of the quiz's ``quiz_ended``, or None while its host mark is not durable."""
        if result.seq is not None:
            return result.seq
        end = await self._store.end_quiz(quiz_id, "deadline")
        if end.status == "ended":
            return end.seq
        # not_due: a host mark not announced, or whose announcement a Redis restart lost;
        # announce it once it is durable (redis.md §3.1)
        try:
            return await self._store.end_by_host(quiz_id)
        except DomainError as error:
            if error.code is not ErrorCode.UNAVAILABLE:
                raise
            log.warning("tick of quiz %s: the end mark is not durable yet", quiz_id)
            return None

    async def _publish(self, quiz_id: str) -> Publish:
        result = await self._store.publish_if_dirty(quiz_id, self._node_id)
        if result.status == "published":
            metrics.LEADERBOARD_FRAMES.inc()
            if result.lag_ms is not None:
                metrics.LEADERBOARD_PUBLISH_LAG.observe(result.lag_ms / 1000)
        return result


async def _relay(relay: Relay, messages: AsyncIterator[str], progress: asyncio.Event) -> None:
    """Relay until ``quiz_ended``; a feed that fails or ends before it raises."""
    async for message in messages:
        try:
            if await relay.relay(message):
                return
            progress.set()
        except Exception:
            log.exception("broadcast not relayed")
    msg = "the subscription ended"
    raise ConnectionError(msg)
