# AI-ASSISTED: the Prometheus metrics of one node, on a registry of their own.
"""Every metric the service exports. ``/metrics`` serves ``REGISTRY``; the gateway, the scoring
path and the fan-out tick update the metrics below. A labelled counter starts with each label
value at 0, so a scrape shows every series before its first event."""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

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
    "Duration of one coalescing tick: publish script and relay",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5),
    registry=REGISTRY,
)
REDIS_CLOCK_STEP = Counter(
    "redis_clock_step_total",
    "Answers scored with elapsed 0 because the Redis clock stepped back after the serve",
    registry=REGISTRY,
)


def exposition() -> tuple[bytes, str]:
    """The registry in the Prometheus text format, and its content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
