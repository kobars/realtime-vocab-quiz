# AI-ASSISTED: a /metrics scrape finds each named metric with its type, each answer result and the
# store outage series of the error replies.
import httpx

from quiz.config import Settings
from quiz.main import create_app

METRICS = {
    "ws_connections": "gauge",
    "ws_pending_close": "gauge",
    "ws_closes_total": "counter",
    "ws_send_delay_seconds": "histogram",
    "event_loop_lag_seconds": "gauge",
    "answers_total": "counter",
    "ws_errors_total": "counter",
    "leaderboard_frames_total": "counter",
    "leaderboard_frames_conflated_total": "counter",
    "leaderboard_publish_lag_seconds": "histogram",
    "resyncs_total": "counter",
    "tick_duration_seconds": "histogram",
    "redis_clock_step_total": "counter",
    "log_lines_dropped_total": "counter",
}


async def test_metrics_scrape_finds_each_name() -> None:
    app = create_app(Settings(store="memory"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as h:
        resp = await h.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain; version=")
    lines = resp.text.splitlines()
    types = {line.split()[2]: line.split()[3] for line in lines if line.startswith("# TYPE ")}
    assert {name: types.get(name) for name in METRICS} == METRICS
    for name in METRICS:
        assert any(line.startswith(name) for line in lines), name
    series = {line.rpartition(" ")[0] for line in lines}
    assert {f'answers_total{{result="{r}"}}' for r in ("correct", "wrong", "late")} <= series
    assert 'ws_errors_total{code="UNAVAILABLE",request="answer"}' in series
    assert 'ws_closes_total{code="1013"}' in series
