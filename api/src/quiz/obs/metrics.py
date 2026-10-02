# AI-ASSISTED: the Prometheus metrics of one node, on a registry of their own.
"""Every metric the service exports. ``/metrics`` serves ``REGISTRY``. Each metric is registered
here up front, and a labelled counter starts with each label value at 0 (``ws_errors_total``: its
``UNAVAILABLE`` series; ``ws_closes_total``: each known close code and ``other``), so a scrape shows
those series before their first event. The scoring
service counts answers, error replies, resyncs and clock steps; the gateway its sockets, pending
closes and closes by code; each socket's sender its send delays and the leaderboard frames
conflation dropped; the fan-out tick its frames, durations and publish lags; the log pipeline the
lines it dropped; a timer the event loop's lag."""

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

WS_CONNECTIONS = Gauge(
    "ws_connections", "WebSocket connections holding a connection cap slot", registry=REGISTRY
)
WS_PENDING_CLOSE = Gauge(
    "ws_pending_close",
    "WebSocket connections whose given-up close frame waits for the peer to read or go",
    registry=REGISTRY,
)
WS_CLOSES = Counter(
    "ws_closes_total",
    "WebSocket closes by close code: the server's, or the peer's when it closed first",
    ["code"],
    registry=REGISTRY,
)
# The codes this service closes with, and those a browser, a proxy or a server restart give. A peer
# may close with any of about 2,000 more; those count as "other", so a client adds no series.
WS_CLOSE_CODES = frozenset({1000, 1001, 1005, 1006, 1008, 1009, 1011, 1012, 1013, 4001})
for _code in (*map(str, sorted(WS_CLOSE_CODES)), "other"):
    WS_CLOSES.labels(_code)
WS_SEND_DELAY = Histogram(
    "ws_send_delay_seconds",
    "Time from queueing a frame in a socket's send queue to the end of its write",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)
EVENT_LOOP_LAG = Gauge(
    "event_loop_lag_seconds",
    "How late the event loop ran its latest lag timer",
    registry=REGISTRY,
)
ANSWERS = Counter("answers_total", "Scored answers by result", ["result"], registry=REGISTRY)
for _result in ("correct", "wrong", "late"):
    ANSWERS.labels(_result)
LEADERBOARD_FRAMES = Counter(
    "leaderboard_frames_total", "Leaderboard frames published by this node", registry=REGISTRY
)
LEADERBOARD_FRAMES_CONFLATED = Counter(
    "leaderboard_frames_conflated_total",
    "Leaderboard frames dropped from a slow socket's send queue by a newer frame",
    registry=REGISTRY,
)
LEADERBOARD_PUBLISH_LAG = Histogram(
    "leaderboard_publish_lag_seconds",
    "Time from the first change a published leaderboard frame carries to its publication",
    buckets=(0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.75, 1.0, 2.5),
    registry=REGISTRY,
)
RESYNCS = Counter("resyncs_total", "Resync requests answered with a snapshot", registry=REGISTRY)
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


def count_close(code: int) -> None:
    """Count one WebSocket close under its code, or under ``other`` outside ``WS_CLOSE_CODES``."""
    WS_CLOSES.labels(str(code) if code in WS_CLOSE_CODES else "other").inc()
