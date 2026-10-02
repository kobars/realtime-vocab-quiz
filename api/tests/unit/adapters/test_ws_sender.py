# AI-ASSISTED: the sender counts each leaderboard frame that conflation drops from a slow socket.
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
