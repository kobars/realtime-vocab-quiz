# AI-ASSISTED: make demo's script against a fake docker command, and the compose services it starts.
"""``scripts/demo.sh`` runs in a copy of the script with a ``docker`` stub first on ``PATH`` that
logs each call with the variables compose would read; the compose services are read as YAML."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pre_commit.yaml import yaml_load

ROOT = Path(__file__).resolve().parents[2]
COMPOSE: dict[str, Any] = yaml_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
SERVICES: dict[str, Any] = COMPOSE["services"]

# The seed prints $SEED_OUTPUT (default: a quiz ID); every other call prints nothing.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$* | cap=${PER_IP_CONN_CAP:-} quiz=${DEMO_QUIZ_ID:-} bots=${DEMO_BOTS:-}" >> "$DOCKER_LOG"
case "$*" in
  *" run --rm -T seed") printf '%b' "${SEED_OUTPUT-Quiz ID: VOCAB-42-TEST (open for 60 min)\\n}" ;;
esac
"""
BOTS_UP = (
    "compose --progress quiet up -d --no-build bots | cap={cap} quiz=VOCAB-42-TEST bots={bots}"
)


def _demo(
    tmp_path: Path, *args: str, env_file: str | None = None, **env: str
) -> tuple[int, list[str], str, Path]:
    """Run demo.sh from a fresh copy; return its exit code, the docker calls, its output and the
    copy's root."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "demo.sh", repo / "scripts")
    if env_file is not None:
        (repo / ".env").write_text(env_file, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    log.touch()
    base = {k: v for k, v in os.environ.items() if k != "PER_IP_CONN_CAP"}
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    result = subprocess.run(
        [str(repo / "scripts" / "demo.sh"), *args],
        env={**base, "PATH": path, "DOCKER_LOG": str(log), **env},
        capture_output=True,
        text=True,
        check=False,
    )
    calls = log.read_text(encoding="utf-8").splitlines()
    return result.returncode, calls, result.stdout + result.stderr, repo


def test_a_fresh_clone_gets_secrets_the_stack_a_fresh_quiz_and_its_bots(tmp_path: Path) -> None:
    code, calls, out, repo = _demo(tmp_path)
    assert code == 0, out
    secrets = dict(line.split("=", 1) for line in (repo / ".env").read_text().splitlines())
    assert set(secrets) == {"ADMIN_TOKEN", "REDIS_PASSWORD"}
    assert all(re.fullmatch(r"[0-9a-f]{48}", value) for value in secrets.values())
    assert secrets["ADMIN_TOKEN"] != secrets["REDIS_PASSWORD"]
    assert (repo / ".env").stat().st_mode & 0o077 == 0  # the secrets are the owner's alone
    # The bots image is built before the seed starts the quiz's window.
    assert calls == [
        "compose --progress quiet build bots | cap=10000 quiz= bots=",
        "compose --profile full up -d --wait --wait-timeout 120 | cap=10000 quiz= bots=",
        "compose --progress quiet run --rm -T seed | cap=10000 quiz= bots=",
        BOTS_UP.format(cap=10000, bots=20),
    ]
    assert "Quiz ID: VOCAB-42-TEST (open for 60 min)" in out
    assert "20 playing VOCAB-42-TEST" in out


@pytest.mark.parametrize(
    ("bots", "cap"), [("20", "10000"), ("200", "10000"), ("1799", "10000"), ("2000", "11000")]
)
def test_the_connection_cap_stays_far_above_the_bots(tmp_path: Path, bots: str, cap: str) -> None:
    """A changed cap recreates the API nodes, so the usual bot counts share one."""
    code, calls, out, _ = _demo(tmp_path, bots, env_file="ADMIN_TOKEN=a\nREDIS_PASSWORD=b\n")
    assert code == 0, out
    assert calls[-1] == BOTS_UP.format(cap=cap, bots=bots)


def test_a_cap_set_in_env_or_the_shell_is_kept(tmp_path: Path) -> None:
    env_file = "ADMIN_TOKEN=a\nREDIS_PASSWORD=b\nPER_IP_CONN_CAP=300\n"
    code, calls, _, repo = _demo(tmp_path, env_file=env_file)
    assert code == 0
    assert all("| cap= " in call for call in calls)  # compose reads it from .env
    assert (repo / ".env").read_text() == env_file
    code, calls, _, _ = _demo(tmp_path / "shell", PER_IP_CONN_CAP="400")
    assert all("| cap=400 " in call for call in calls)


@pytest.mark.parametrize("bots", ["0", "-5", "ten", "1e3"])
def test_a_bot_count_that_is_not_a_whole_number_above_0_stops_first(
    tmp_path: Path, bots: str
) -> None:
    code, calls, out, repo = _demo(tmp_path, bots)
    assert code == 2
    assert "BOTS must be a whole number above 0" in out
    assert calls == []
    assert not (repo / ".env").exists()


def test_no_bots_start_when_the_seed_prints_no_quiz_id(tmp_path: Path) -> None:
    code, calls, out, _ = _demo(tmp_path, SEED_OUTPUT="")
    assert code == 1
    assert "the seed printed no quiz ID" in out
    assert not [call for call in calls if " up " in call and " bots |" in call]


def test_the_seed_runs_from_the_api_image_on_the_stack_network() -> None:
    seed = SERVICES["seed"]
    assert seed["profiles"] == ["demo"]
    assert seed["image"] == SERVICES["api-1"]["image"]
    assert seed["networks"] == ["stack"]
    assert seed["read_only"] is True
    assert seed["volumes"] == ["./scripts/seed.py:/opt/seed.py:ro"]
    assert seed["command"] == ["python", "/opt/seed.py"]
    assert seed["environment"]["ADMIN_TOKEN"].startswith("${ADMIN_TOKEN:?")


def test_the_bots_are_the_bot_swarm_on_the_demo_quiz_with_an_allowed_origin() -> None:
    bots, load = SERVICES["bots"], SERVICES["load"]
    assert bots["profiles"] == ["demo"]
    assert (bots["build"], bots["networks"]) == (load["build"], load["networks"])
    assert bots["image"] == load["image"]  # one image of the bot swarm, not one per service
    assert bots["environment"] == load["environment"]  # through nginx on the stack network
    assert bots["volumes"] == []  # the result file stays in a tmpfs: no host folder to own
    assert "/app/results" in bots["tmpfs"]
    flags = dict(arg.removeprefix("--").split("=", 1) for arg in bots["command"])
    assert (flags["quiz-ids"], flags["bots"]) == ("${DEMO_QUIZ_ID:-}", "${DEMO_BOTS:-20}")
    assert flags["origin"] == "http://localhost:${QUIZ_PORT:-8080}"  # the API's default origin


def test_the_test_profile_runs_the_unit_and_acceptance_tests_from_a_fresh_build() -> None:
    test = SERVICES["test"]
    assert test["profiles"] == ["test"]
    assert test["command"] == ["make", "test", "acceptance"]
    assert test["build"] == {"context": ".", "dockerfile": "infra/dev/Dockerfile"}
    assert test["pull_policy"] == "build"  # never a stale image of an older checkout
    assert "volumes" not in test


def test_the_development_image_keeps_the_tests_in_its_build_context() -> None:
    ignored = (ROOT / "infra" / "dev" / "Dockerfile.dockerignore").read_text().splitlines()
    for entry in ("**/.git", ".worktrees", "**/.venv", "**/node_modules", "**/.env"):
        assert entry in ignored
    for kept in ("api/tests", "load", "docs"):
        assert kept not in ignored


def test_make_help_lists_the_demo_targets() -> None:
    listing = subprocess.run(
        ["make", "--no-print-directory", "-s", "help"],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    targets = [line.split()[0] for line in listing.splitlines()]
    assert {"demo", "demo-stop", "new-quiz"} <= set(targets)
