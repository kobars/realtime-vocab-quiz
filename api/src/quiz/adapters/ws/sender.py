# AI-ASSISTED: one writer per socket: a byte-bounded send queue with leaderboard conflation.
"""Every frame for a socket goes through its ``Sender``, so the socket has one writer and the
client gets a node's messages in the order the node produced them (docs/spec/protocol.md §1, §5).

The buffer counts the bytes not yet written, the frame in flight included. Above the soft limit
a ``leaderboard`` takes the place of every ``leaderboard`` queued after the last other message,
and goes out with ``rebase: true``; every other message is a barrier and is never dropped.
Above the hard limit the queue makes way for ``error UNAVAILABLE`` and close 1013. A socket
that does not take its queue within ``flush_s`` of a close is closed anyway."""

import asyncio
from collections import deque
from contextlib import suppress
from dataclasses import dataclass

from fastapi import WebSocket

from quiz.contracts import messages as m
from quiz.contracts.codec import encode

CLOSE_OVERLOAD = 1013
FLUSH_S = 5.0
# Our encoder writes compact JSON, and a quote inside a string value is escaped: this key with
# its value occurs once per frame.
_NOT_REBASED, _REBASED = b'"rebase":false', b'"rebase":true'
_SLOW = encode(
    m.ProtocolError(code=m.ErrorCode.UNAVAILABLE, message="slow client", requestType=None)
)


@dataclass(slots=True)
class _Frame:
    data: bytes
    leaderboard: bool


class Sender:
    def __init__(self, ws: WebSocket, soft: int, hard: int, flush_s: float = FLUSH_S) -> None:
        self._ws, self._soft, self._hard, self._flush_s = ws, soft, hard, flush_s
        self._queue: deque[_Frame] = deque()
        self._queued = self._in_flight = 0
        self._ready = asyncio.Event()
        self._close_by: float | None = None
        self._deadline: asyncio.Timeout | None = None
        self.close_code: int | None = None  # set by close(); nothing is queued after it
        self.task = asyncio.create_task(self._run())  # ends once the socket is closed or gone

    @property
    def buffered(self) -> int:
        return self._queued + self._in_flight

    def send(self, message: m.ServerMessage) -> None:
        self.send_frame(encode(message), leaderboard=isinstance(message, m.Leaderboard))

    def send_frame(self, data: bytes, *, leaderboard: bool = False) -> None:
        """Queue an encoded frame; ``leaderboard`` frames may be conflated."""
        if self.close_code is not None:
            return
        if leaderboard and self.buffered > self._soft:
            data = data.replace(_NOT_REBASED, _REBASED, 1)
            while self._queue and self._queue[-1].leaderboard:
                self._queued -= len(self._queue.pop().data)
        self._append(data, leaderboard=leaderboard)
        if self.buffered > self._hard:
            self._queue.clear()
            self._queued = 0
            # The frame in flight still counts, so the error may pass the limit too: it skips
            # the check, and the close always follows.
            self._append(_SLOW, leaderboard=False)
            self.close(CLOSE_OVERLOAD)
        self._ready.set()

    def _append(self, data: bytes, *, leaderboard: bool) -> None:
        self._queue.append(_Frame(data, leaderboard))
        self._queued += len(data)

    def close(self, code: int) -> None:
        """Close the socket with ``code`` once the queued frames are out."""
        if self.close_code is not None:
            return
        self.close_code = code
        self._close_by = asyncio.get_running_loop().time() + self._flush_s
        if self._deadline is not None:  # only while the writer is inside it
            self._deadline.reschedule(self._close_by)
        self._ready.set()

    async def _run(self) -> None:
        try:
            async with asyncio.timeout_at(self._close_by) as self._deadline:  # a loop time
                await self._write()
        except TimeoutError:
            pass  # the queue did not drain within flush_s of the close: close it anyway
        except Exception:  # noqa: BLE001 - the socket is gone; the receive loop sees the drop
            return
        finally:
            self._deadline = None  # a finished timeout cannot be rescheduled by a later close()
        with suppress(Exception):  # it may have dropped meanwhile
            await self._ws.close(self.close_code or 1000)

    async def _write(self) -> None:
        while True:
            await self._ready.wait()
            if not self._queue:
                if self.close_code is not None:
                    return
                self._ready.clear()
                continue
            frame = self._queue.popleft()
            self._queued -= len(frame.data)
            self._in_flight = len(frame.data)
            await self._ws.send_text(frame.data.decode())
            self._in_flight = 0
