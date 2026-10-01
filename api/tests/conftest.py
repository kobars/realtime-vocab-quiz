# AI-ASSISTED: shared pytest setup: Hypothesis profiles, folder markers, the one Redis fixture, a
# deadline on the in-process WebSocket client's receive and a reader of the service's metrics.
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from urllib.parse import urlparse

import anyio
import pytest
from hypothesis import settings
from redis import Redis as SyncRedis
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.testclient import WebSocketTestSession
from starlette.types import Message

from quiz.adapters.redis import RedisStore
from quiz.obs import metrics

settings.register_profile("dev", max_examples=50)
settings.register_profile("ci", max_examples=500, deadline=None, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

_TESTS = Path(__file__).parent
_FOLDER_MARKERS = frozenset({"unit", "property", "contract", "integration", "acceptance"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark each test by its folder, so `-m "not integration"` needs no per-test markers."""
    for item in items:
        if item.path.is_relative_to(_TESTS):
            folder = item.path.relative_to(_TESTS).parts[0]
            if folder in _FOLDER_MARKERS:
                item.add_marker(folder)


WS_RECEIVE_DEADLINE_S = 10.0  # well inside the per-test timeout


def receive_within(deadline_s: float) -> Callable[[WebSocketTestSession], Message]:
    def receive(ws: WebSocketTestSession) -> Message:
        async def next_message() -> Message:
            with anyio.fail_after(deadline_s):
                return await ws._send_rx.receive()  # noqa: SLF001 - the stream receive() reads

        return ws.portal.call(next_message)

    return receive


@pytest.fixture(scope="session", autouse=True)
def ws_receive() -> Iterator[Callable[[float], Callable[[WebSocketTestSession], Message]]]:
    """Give TestClient's WebSocket receive a deadline; yield the factory for a shorter one.

    Starlette's receive waits forever, so a server that never answers holds the test until the
    per-test timeout; with the deadline the receive itself raises TimeoutError much sooner.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(WebSocketTestSession, "receive", receive_within(WS_RECEIVE_DEADLINE_S))
        yield receive_within


DEV_REDIS_PORT = 6381  # `make up`; tests never touch it


def _docker(*args: str, check: bool = True) -> str:
    docker = shutil.which("docker") or pytest.fail("no REDIS_URL and no docker to start a Redis")
    run = subprocess.run([docker, *args], check=check, capture_output=True, text=True)  # noqa: S603
    return run.stdout


def _wait_ready(url: str, wait_s: float) -> None:
    deadline = time.monotonic() + wait_s
    while True:
        try:
            with SyncRedis.from_url(url) as client:
                client.ping()
        except RedisConnectionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
        else:
            return


def _start_redis(wait_s: float = 30) -> tuple[str, str]:
    """Run redis:8-alpine on a free host port that Docker picks; return (container, url).

    ``--rm`` acts only once the container stops, so any failure after ``docker run`` removes it.
    """
    run = ["run", "-d", "--rm", "-p", "127.0.0.1::6379", "redis:8-alpine"]
    container = _docker(*run, "redis-server", "--appendonly", "yes").strip()
    try:
        port = _docker("port", container, "6379/tcp").splitlines()[0].rsplit(":", 1)[1]
        url = f"redis://127.0.0.1:{port}/0"
        _wait_ready(url, wait_s)
    except BaseException:
        _docker("rm", "-f", container, check=False)
        raise
    return container, url


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    """One Redis per test session: REDIS_URL when set (CI), else a container of its own."""
    if url := os.environ.get("REDIS_URL"):
        if urlparse(url).port == DEV_REDIS_PORT:
            pytest.fail(f"REDIS_URL points at the dev Redis on port {DEV_REDIS_PORT}; unset it")
        with SyncRedis.from_url(url) as client:  # WAITAOF needs AOF; a CI service starts without
            client.config_set("appendonly", "yes")
        yield url
        return
    container, url = _start_redis()
    try:
        yield url
    finally:
        _docker("rm", "-f", container, check=False)


@pytest.fixture(autouse=True)
def acceptance_redis(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Redis acceptance harness flushes REDIS_URL: hand it this session's Redis instead."""
    redis_mode = os.environ.get("ACCEPTANCE_STORE") == "redis"
    if redis_mode and request.node.get_closest_marker("acceptance"):
        monkeypatch.setenv("REDIS_URL", request.getfixturevalue("redis_url"))


@pytest.fixture
def redis_prefix() -> str:
    """A key prefix of this test alone; ``redis_client`` deletes its keys afterwards."""
    return f"test:{uuid.uuid4().hex}:"


@pytest.fixture
async def redis_client(redis_url: str, redis_prefix: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url, decode_responses=True)
    yield client
    if keys := [key async for key in client.scan_iter(match=f"{redis_prefix}*")]:
        await client.delete(*keys)
    await client.aclose()


@pytest.fixture
async def redis_store(redis_client: Redis, redis_prefix: str) -> RedisStore:
    """A loaded store on this test's key prefix; ``redis_client`` deletes the keys afterwards."""
    store = RedisStore(redis_client, prefix=redis_prefix)
    await store.start()
    return store


@pytest.fixture
def metric() -> Callable[..., float]:
    """``metric(name, **labels)``: a sample's value on the shared registry, 0 before it exists.

    The registry lives for the whole run, so a test compares two reads, never one exact value."""

    def read(name: str, **labels: str) -> float:
        return metrics.REGISTRY.get_sample_value(name, labels) or 0.0

    return read
