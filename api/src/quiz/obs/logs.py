# AI-ASSISTED: JSON-line logging for structlog and the standard library, with request context.
"""One JSON object per line on stderr. Every line carries ``quiz_id`` and ``request_id`` (null
when unknown), taken from structlog's context variables, which the HTTP middleware binds.

A line is formatted where it is logged, then a listener thread writes it: a stalled stderr reader
(a full pipe, a blocking log driver) never blocks the event loop. The queue between them is
bounded; when it is full a line is dropped and counted in ``log_lines_dropped_total``. Closing the
handler, which ``logging.shutdown`` does at exit, writes the queued lines first, waiting at most
``STOP_WAIT_S``: a stalled reader never holds the exit."""

import logging
import os
import queue
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from logging.handlers import QueueHandler, QueueListener
from typing import TextIO, override

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from quiz.obs import metrics

HANDLER_NAME = "quiz-json"
QUEUE_LINES = 10_000
STOP_WAIT_S = 2.0  # how long a stop may wait for the queued lines; below the stop grace


def _ids(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    event.setdefault("quiz_id", None)
    event.setdefault("request_id", None)
    return event


Write = Callable[[str], None]


def _line_writer(stream: TextIO | None) -> Write:
    """Write to ``stream``, or else straight to stderr's file descriptor. At exit,
    ``logging.shutdown`` and the interpreter flush ``sys.stderr``; a write blocked on a stalled
    reader must hold no lock of it, or the exit waits forever."""
    if stream is None:
        try:
            fd = sys.stderr.fileno()
        except AttributeError, OSError, ValueError:  # a replaced sys.stderr may have no descriptor
            stream = sys.stderr
        else:

            def to_fd(line: str) -> None:
                data = line.encode()
                while data:
                    data = data[os.write(fd, data) :]

            return to_fd

    def to_stream(line: str) -> None:
        stream.write(line)
        stream.flush()

    return to_stream


class _Writer(QueueListener):
    """Writes each queued line itself, with no ``logging.Handler`` in between: ``logging.shutdown``
    takes every handler's lock at exit, and a handler blocked on a stalled reader holds it."""

    def __init__(self, lines: queue.Queue[logging.LogRecord | None], write: Write) -> None:
        super().__init__(lines)
        self.lines, self.write = lines, write

    @override
    def handle(self, record: logging.LogRecord) -> None:
        try:
            self.write(record.getMessage() + "\n")  # the queued message is the JSON line
        except OSError, ValueError:  # a closed or broken stream: the line is lost, not the writer
            metrics.LOG_LINES_DROPPED.inc()

    @override
    def stop(self) -> None:
        if self._thread is None:  # never started, or stopped already
            return
        give_up = time.monotonic() + STOP_WAIT_S
        with suppress(queue.Full):  # the queue may be full: wait for room, within the limit
            self.lines.put(None, timeout=STOP_WAIT_S)
        self._thread.join(max(0.0, give_up - time.monotonic()))
        self._thread = None


class _DroppingHandler(QueueHandler):
    def __init__(self, lines: queue.Queue[logging.LogRecord | None], write: Write) -> None:
        super().__init__(lines)
        self.writer = _Writer(lines, write)

    @override
    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            metrics.LOG_LINES_DROPPED.inc()

    @override
    def close(self) -> None:
        self.writer.stop()
        super().close()


def configure_logging(stream: TextIO | None = None, level: int = logging.INFO) -> QueueListener:
    """Install the JSON handler on the root logger and start its writer; calling it again
    replaces the handler and stops the earlier writer. Stopping the returned listener writes
    the queued lines, waiting at most ``STOP_WAIT_S``."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _ids,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    handler = _DroppingHandler(queue.Queue(QUEUE_LINES), _line_writer(stream))
    handler.name = HANDLER_NAME
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    for old in [h for h in root.handlers if h.name == HANDLER_NAME]:
        root.removeHandler(old)
        old.close()
    root.addHandler(handler)
    root.setLevel(level)
    handler.writer.start()
    for name in ("uvicorn", "uvicorn.error"):  # uvicorn's own lines go through the JSON handler
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True  # it logs query strings, so tickets
    return handler.writer
