# AI-ASSISTED: JSON-line logging for structlog and the standard library, with request context.
"""One JSON object per line on stderr. Every line carries ``quiz_id`` and ``request_id`` (null
when unknown), taken from structlog's context variables, which the HTTP middleware binds.

A line is formatted where it is logged, then a listener thread writes it: a stalled stderr reader
(a full pipe, a blocking log driver) never blocks the event loop. The queue between them is
bounded; when it is full a line is dropped and counted in ``log_lines_dropped_total``. Closing the
handler, which ``logging.shutdown`` does at exit, writes every queued line first."""

import logging
import queue
import sys
from logging.handlers import QueueHandler, QueueListener
from typing import TextIO, override

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from quiz.obs import metrics

HANDLER_NAME = "quiz-json"
QUEUE_LINES = 10_000


def _ids(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    event.setdefault("quiz_id", None)
    event.setdefault("request_id", None)
    return event


class _Writer(QueueListener):
    def __init__(self, lines: queue.Queue[logging.LogRecord | None], out: logging.Handler) -> None:
        super().__init__(lines, out)
        self.lines = lines

    @override
    def enqueue_sentinel(self) -> None:
        self.lines.put(None)  # the stop sentinel; waits for room, as the queue may be full


class _DroppingHandler(QueueHandler):
    def __init__(self, lines: queue.Queue[logging.LogRecord | None], out: logging.Handler) -> None:
        super().__init__(lines)
        self.writer = _Writer(lines, out)

    @override
    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            metrics.LOG_LINES_DROPPED.inc()

    @override
    def close(self) -> None:
        self.writer.stop()  # a no-op on a stopped writer
        super().close()


def configure_logging(stream: TextIO | None = None, level: int = logging.INFO) -> QueueListener:
    """Install the JSON handler on the root logger and start its writer; calling it again
    replaces the handler and stops the earlier writer. Stopping the returned listener writes
    every queued line."""
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
    out = logging.StreamHandler(stream or sys.stderr)
    out.setFormatter(logging.Formatter("%(message)s"))  # the queued line is already JSON
    handler = _DroppingHandler(queue.Queue(QUEUE_LINES), out)
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
