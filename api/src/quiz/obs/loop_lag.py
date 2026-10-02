# AI-ASSISTED: the event-loop lag gauge of one node.
"""A timer due every ``interval_s`` reports in ``event_loop_lag_seconds`` how late the event loop
ran it. Every socket of a node shares its one event loop, so a callback that blocks the loop, or
more ready work than the loop gets through, delays each of their writes by as much."""

import asyncio

from quiz.obs import metrics

INTERVAL_S = 0.1


class LoopLag:
    def __init__(self, interval_s: float = INTERVAL_S) -> None:
        self._interval_s = interval_s
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the timer: the app's start hook."""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the timer: the app's stop hook."""
        if (task := self._task) is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            due = loop.time() + self._interval_s
            await asyncio.sleep(self._interval_s)
            metrics.EVENT_LOOP_LAG.set(max(0.0, loop.time() - due))
