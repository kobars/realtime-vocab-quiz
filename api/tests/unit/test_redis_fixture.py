# AI-ASSISTED: the test Redis fixture removes its container when startup fails after `docker run`.
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Self

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError


def _load_conftest() -> ModuleType:
    """A fresh copy of tests/conftest.py, so the mocks below touch no other test."""
    path = Path(__file__).parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("conftest_copy", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _NeverReady:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def ping(self) -> None:
        raise RedisConnectionError


@pytest.mark.parametrize("failure", ["port lookup", "readiness timeout"])
def test_container_is_removed_when_startup_fails(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    conftest, calls = _load_conftest(), []

    def docker(*args: str, check: bool = True) -> str:  # noqa: ARG001 - the helper's signature
        calls.append(args[:2])
        if args[0] == "port" and failure == "port lookup":
            raise subprocess.CalledProcessError(1, ["docker", *args])
        return {"run": "abc123\n", "port": "127.0.0.1:49999\n"}.get(args[0], "")

    monkeypatch.setattr(conftest, "_docker", docker)
    monkeypatch.setattr(conftest, "SyncRedis", SimpleNamespace(from_url=lambda _: _NeverReady()))
    with pytest.raises((subprocess.CalledProcessError, RedisConnectionError)):
        conftest._start_redis(wait_s=0)  # noqa: SLF001 - the fixture's own helper
    assert calls[0] == ("run", "-d")
    assert calls[-1] == ("rm", "-f")


def test_redis_acceptance_run_refuses_the_dev_redis() -> None:
    """The Redis acceptance harness flushes its REDIS_URL, so a dev-port URL must stop the run.

    The host never resolves: without the guard the flush fails to connect, never touching data.
    """
    tests = Path(__file__).parents[1]
    env = os.environ | {"ACCEPTANCE_STORE": "redis", "REDIS_URL": "redis://dev.invalid:6381/0"}
    run = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            f"{tests}/acceptance/test_join.py::test_ac1_join_by_quiz_id",
        ],
        cwd=tests.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == pytest.ExitCode.TESTS_FAILED, run.stdout
    assert "REDIS_URL points at the dev Redis on port 6381" in run.stdout
