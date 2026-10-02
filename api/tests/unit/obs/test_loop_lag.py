# AI-ASSISTED: the event-loop lag gauge reports how long a blocking callback held the loop.
import asyncio
import time
from collections.abc import Callable

from quiz.obs.loop_lag import LoopLag


async def test_a_callback_that_blocks_the_loop_shows_as_lag(metric: Callable[..., float]) -> None:
    lag = LoopLag(interval_s=0.01)
    await lag.start()
    await asyncio.sleep(0.03)  # a few samples on an idle loop
    assert metric("event_loop_lag_seconds") < 0.05
    time.sleep(0.1)  # noqa: ASYNC251 - the blocking callback under test
    await asyncio.sleep(0.005)  # the late timer fires first, then this sleep ends
    assert metric("event_loop_lag_seconds") >= 0.08
    await lag.stop()
    await lag.stop()  # stopping twice is safe
