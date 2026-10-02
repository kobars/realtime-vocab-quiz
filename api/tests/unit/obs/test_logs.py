# AI-ASSISTED: the log pipeline: a stalled stderr never stalls the event loop, and no line is lost
# on a clean stop.
import asyncio
import io
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import override

import pytest
import structlog

from quiz.obs import logs


class BlockedStream(io.StringIO):  # a sink whose reader has stalled until ``open`` is set
    def __init__(self) -> None:
        super().__init__()
        self.open = threading.Event()

    @override
    def write(self, text: str) -> int:
        self.open.wait()
        return super().write(text)


@pytest.mark.timeout(10)  # the current code blocks the loop on the first write
async def test_a_blocked_sink_does_not_stall_the_loop(metric: Callable[..., float]) -> None:
    sink, dropped = BlockedStream(), metric("log_lines_dropped_total")
    listener = logs.configure_logging(sink)
    gaps: list[float] = []

    async def heartbeat() -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.01)
            gaps.append(time.monotonic() - last)
            last = time.monotonic()

    beat = asyncio.create_task(heartbeat())
    log = structlog.get_logger("quiz.http")
    with structlog.contextvars.bound_contextvars(quiz_id="VOCAB-42", request_id="req-1"):
        for batch in range(200):  # 20,000 lines, twice the queue
            for i in range(100):
                log.info("http_request", n=batch * 100 + i)
            await asyncio.sleep(0)
    await asyncio.sleep(0.05)
    beat.cancel()
    assert max(gaps) < 0.1
    assert metric("log_lines_dropped_total") > dropped
    sink.open.set()
    listener.stop()
    lines = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert len(lines) > 1
    assert {(line["quiz_id"], line["request_id"], line["event"]) for line in lines} == {
        ("VOCAB-42", "req-1", "http_request")
    }


def test_closing_the_handler_writes_every_queued_line() -> None:
    sink = io.StringIO()
    logs.configure_logging(sink)
    for i in range(500):
        logging.getLogger("quiz.test").info("line %d", i)
    [handler] = [h for h in logging.getLogger().handlers if h.name == logs.HANDLER_NAME]
    handler.close()  # what logging.shutdown does at the interpreter's exit
    assert [json.loads(line)["event"] for line in sink.getvalue().splitlines()] == [
        f"line {i}" for i in range(500)
    ]
