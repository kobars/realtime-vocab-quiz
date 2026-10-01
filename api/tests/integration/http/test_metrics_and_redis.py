# AI-ASSISTED: a /metrics scrape, and the probes and tickets on a reachable Redis.
import httpx
from fastapi import FastAPI

from quiz.config import Settings
from quiz.main import create_app

METRICS = (
    "ws_connections",
    "answers_total",
    "leaderboard_frames_total",
    "tick_duration_seconds",
    "redis_clock_step_total",
)


def client_of(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_metrics_scrape_finds_each_name() -> None:
    async with client_of(create_app(Settings(store="memory"))) as http:
        resp = await http.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain; version=")
    types = {
        line.split()[2]: line.split()[3]
        for line in resp.text.splitlines()
        if line.startswith("# TYPE ")
    }
    expected = ["gauge", "counter", "counter", "histogram", "counter"]
    assert [types.get(name) for name in METRICS] == expected
    for name in METRICS:
        assert any(line.startswith(name) for line in resp.text.splitlines()), name
    assert 'answers_total{result="late"} 0.0' in resp.text


async def test_ready_and_tickets_on_redis(redis_url: str) -> None:
    app = create_app(Settings(store="redis", redis_url=redis_url))
    async with app.router.lifespan_context(app), client_of(app) as http:
        assert (await http.get("/readyz")).json() == {"status": "ready"}
        session = (await http.post("/sessions", json={"displayName": "Ana"})).json()
        auth = {"Authorization": f"Bearer {session['sessionToken']}"}
        assert (await http.post("/tickets", headers=auth)).status_code == 201
