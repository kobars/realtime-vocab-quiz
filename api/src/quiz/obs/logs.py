# AI-ASSISTED: JSON-line logging for structlog and the standard library, with request context.
"""One JSON object per line on stderr. Every line carries ``quiz_id`` and ``request_id`` (null
when unknown), taken from structlog's context variables, which the HTTP middleware binds."""

import logging
import sys
from typing import TextIO

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

HANDLER_NAME = "quiz-json"


def _ids(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    event.setdefault("quiz_id", None)
    event.setdefault("request_id", None)
    return event


def configure_logging(stream: TextIO | None = None, level: int = logging.INFO) -> None:
    """Install the JSON handler on the root logger; calling it again replaces the handler."""
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
    handler = logging.StreamHandler(stream or sys.stderr)
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
    root.handlers = [h for h in root.handlers if h.name != HANDLER_NAME] + [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):  # uvicorn's own lines go through the JSON handler
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True  # it logs query strings, so tickets
