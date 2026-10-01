# AI-ASSISTED: the image smoke and nginx check scripts, run against a fake docker command.
"""``scripts/smoke_images.sh`` and ``scripts/check_nginx.sh`` with a ``docker`` stub first on
``PATH`` that logs every call, so the tests need no Docker daemon."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Answers `id -u` with a non-root uid, lists three compose services, fails `docker inspect`.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
case "$*" in
  *" id -u") echo 10001 ;;
  "compose "*"config --services") printf 'redis\\napi-1\\napi-2\\n' ;;
  "inspect "*) exit 1 ;;
esac
"""


def _run(script: str, cwd: Path, tmp_path: Path) -> tuple[int, list[str]]:
    """Run ``script`` in ``cwd`` with the docker stub; return its exit code and the docker calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    log.touch()
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    env = {**os.environ, "PATH": path, "DOCKER_LOG": str(log)}
    result = subprocess.run(
        [str(ROOT / "scripts" / script), "ci"], cwd=cwd, env=env, capture_output=True, check=False
    )
    return result.returncode, log.read_text(encoding="utf-8").splitlines()


def test_smoke_removes_its_container_when_the_script_aborts(tmp_path: Path) -> None:
    code, calls = _run("smoke_images.sh", ROOT, tmp_path)
    assert code != 0
    started = [c.split("--name ")[1].split()[0] for c in calls if c.startswith("run --detach")]
    assert started
    assert calls[-1] == f"rm --force {started[-1]}"


def test_infra_nginx_config_is_tested_with_the_compose_service_names_resolvable(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "infra" / "nginx").mkdir(parents=True)
    (repo / "infra" / "nginx" / "nginx.conf").write_text("events {}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)  # noqa: S607
    subprocess.run(["git", "add", "infra"], cwd=repo, check=True)  # noqa: S607
    code, calls = _run("check_nginx.sh", repo, tmp_path)
    assert code == 0
    (infra,) = [c for c in calls if "/etc/nginx/nginx.conf:ro" in c]
    for service in ("redis", "api-1", "api-2"):
        assert f"--add-host={service}:127.0.0.1" in infra
    mount = f"{repo}/infra/nginx/nginx.conf:/etc/nginx/nginx.conf:ro"
    assert infra.endswith(f"-v {mount} elsaquiz-web:ci nginx -t")
