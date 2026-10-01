# AI-ASSISTED: the presence renew loop of docs/spec/redis.md §3, one per node.
"""A grace timer dies with its node, and its ``leave`` may fail, so every ``renew_ms`` this node
renews the presence of each joined socket it holds, per quiz, and the same call drops every entry
of the quiz that no node renewed for ``stale_ms``: the grace plus one renew period, so a normal
disconnect still leaves through its grace timer first. A failed renew is logged, and the next
one still runs."""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Protocol

from quiz.ports.store import Store

log = logging.getLogger(__name__)
RENEW_MS = 3_000


class Holders(Protocol):  # this node's joined sockets
    def presence(self) -> Mapping[str, Sequence[tuple[str, str]]]:
        """The (user id, connection id) pairs of each quiz."""
        ...


class PresenceRenewer:
    def __init__(
        self, store: Store, holders: Holders, grace_ms: int, renew_ms: int = RENEW_MS
    ) -> None:
        self._store, self._holders = store, holders
        self._stale_ms, self._renew_s = grace_ms + renew_ms, renew_ms / 1000
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the loop: the app's start hook."""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the loop: the app's stop hook."""
        if (task := self._task) is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._renew_s)
            for quiz_id, pairs in self._holders.presence().items():
                try:
                    await self._store.renew_presence(quiz_id, self._stale_ms, pairs)
                except Exception:
                    log.warning("presence renew of quiz %s failed", quiz_id, exc_info=True)
