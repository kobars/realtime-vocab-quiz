# AI-ASSISTED: the Prometheus metrics of one node, on a registry of their own.
"""Every metric the service exports. ``/metrics`` serves ``REGISTRY``. Each metric is registered
here up front, and a labelled counter starts with each label value at 0 (``ws_errors_total``: its
``UNAVAILABLE`` series), so a scrape shows those series before their first event. The scoring
service counts answers, error replies and clock steps, the gateway open sockets, the fan-out tick
its frames and durations, the log pipeline the lines it dropped."""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from quiz.contracts import messages as m

REGISTRY = CollectorRegistry()

WS_CONNECTIONS = Gauge("ws_connections", "Open WebSocket connections", registry=REGISTRY)
ANSWERS = Counter("answers_total", "Scored answers by result", ["result"], registry=REGISTRY)
for _result in ("correct", "wrong", "late"):
    ANSWERS.labels(_result)
LEADERBOARD_FRAMES = Counter(
    "leaderboard_frames_total", "Leaderboard frames published by this node", registry=REGISTRY
)
TICK_DURATION = Histogram(
    "tick_duration_seconds",
    "Duration of one coalescing tick: the publish script, and the shifted ranks when due",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5),
    registry=REGISTRY,
)
WS_ERRORS = Counter(
    "ws_errors_total",
    "WebSocket error replies of the use cases by request type and code",
    ["request", "code"],
    registry=REGISTRY,
)
for _request in sorted(m.message_types(m.ClientMessage)):
    WS_ERRORS.labels(_request, m.ErrorCode.UNAVAILABLE.value)
REDIS_CLOCK_STEP = Counter(
    "redis_clock_step_total",
    "Answers scored with elapsed 0 because the Redis clock stepped back after the serve",
    registry=REGISTRY,
)

LOG_LINES_DROPPED = Counter(
    "log_lines_dropped_total",
    "Log lines dropped because the queue to the log writer was full",
    registry=REGISTRY,
)


def exposition() -> tuple[bytes, str]:
    """The registry in the Prometheus text format, and its content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
