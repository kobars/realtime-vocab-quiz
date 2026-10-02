# AI-ASSISTED: the sender counts each leaderboard frame that conflation drops from a slow socket
# and reports each written frame's send delay.
import asyncio
from collections.abc import Callable
from typing import cast

from fastapi import WebSocket

from quiz.adapters.ws.sender import Sender


class Stalled:  # a client that never reads: every frame after the first stays queued
    async def send_text(self, _text: str) -> None:
        await asyncio.Event().wait()

    async def close(self, _code: int) -> None:
        """Nothing to close: the test cancels the writer."""


async def test_each_leaderboard_frame_conflation_drops_is_counted(
    metric: Callable[..., float],
) -> None:
    before = metric("leaderboard_frames_conflated_total")
    sender = Sender(cast("WebSocket", Stalled()), soft=10, hard=10_000)
    frame = b'{"v":1,"type":"leaderboard","seq":1,"rebase":false}'  # one frame passes soft
    for _ in range(4):
        sender.send_frame(frame, leaderboard=True)
    sender.send_frame(b'{"v":1,"type":"pong","seq":1}')  # a barrier: never dropped
    sender.send_frame(frame, leaderboard=True)  # nothing left to replace after the barrier
    assert metric("leaderboard_frames_conflated_total") == before + 3
    sender.task.cancel()


class Held:  # a client that takes each frame once ``reading`` is set
    def __init__(self) -> None:
        self.reading = asyncio.Event()

    async def send_text(self, _text: str) -> None:
        await self.reading.wait()

    async def close(self, _code: int) -> None:
        """Nothing to close: the writer ends after the queued frames."""


async def test_each_written_frame_reports_its_time_from_queueing_to_the_end_of_its_write(
    metric: Callable[..., float],
) -> None:
    count, total = metric("ws_send_delay_seconds_count"), metric("ws_send_delay_seconds_sum")
    held = Held()
    sender = Sender(cast("WebSocket", held), soft=10_000, hard=100_000)
    for seq in (1, 2):
        sender.send_frame(f'{{"v":1,"type":"pong","seq":{seq}}}'.encode())
    await asyncio.sleep(0.06)  # the transport holds the first frame back, the second waits behind
    held.reading.set()
    sender.close(1000)
    await sender.task  # both frames are written, then the socket is closed
    assert metric("ws_send_delay_seconds_count") == count + 2
    assert metric("ws_send_delay_seconds_sum") - total >= 2 * 0.06
