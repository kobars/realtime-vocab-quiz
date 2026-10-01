# AI-ASSISTED: a /metrics scrape finds each named metric with its type.
import httpx

from quiz.config import Settings
from quiz.main import create_app

METRICS = {
    "ws_connections": "gauge",
    "answers_total": "counter",
    "leaderboard_frames_total": "counter",
    "tick_duration_seconds": "histogram",
    "redis_clock_step_total": "counter",
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
    assert 'answers_total{result="late"} 0.0' in lines
