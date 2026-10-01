# AI-ASSISTED: the image smoke and nginx check scripts, run against a fake docker command.
"""``scripts/smoke_images.sh`` and ``scripts/check_nginx.sh`` with a ``docker`` stub first on
``PATH`` that logs every call, so the tests need no Docker daemon."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Answers `id -u` with a non-root uid and lists three compose services. `docker inspect` fails,
# unless $RESPONSE names a file: then every container is healthy, has one hashed asset and
# answers each request with that file.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
case "$*" in
  *" id -u") echo 10001 ;;
  "compose "*"config --services") printf 'redis\\napi-1\\napi-2\\n' ;;
  "inspect "*) [[ -n "${RESPONSE:-}" ]] && echo "running healthy" || exit 1 ;;
  "exec "*" find "*) echo /usr/share/nginx/html/assets/index-abc.js ;;
  "exec "*" curl "*) cat "$RESPONSE" ;;
esac
"""


def _run(
    script: str, cwd: Path, tmp_path: Path, root: Path = ROOT, **env_extra: str
) -> tuple[int, list[str], str]:
    """Run ``script`` of the checkout ``root`` in ``cwd`` with the docker stub; return its exit
    code, the docker calls and its stderr."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    log.touch()
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    env = {**os.environ, "PATH": path, "DOCKER_LOG": str(log), **env_extra}
    result = subprocess.run(
        [str(root / "scripts" / script), "ci"], cwd=cwd, env=env, capture_output=True, check=False
    )
    calls = log.read_text(encoding="utf-8").splitlines()
    return result.returncode, calls, result.stderr.decode()


def test_smoke_removes_its_container_when_the_script_aborts(tmp_path: Path) -> None:
    code, calls, _ = _run("smoke_images.sh", ROOT, tmp_path)
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
    code, calls, _ = _run("check_nginx.sh", repo, tmp_path)
    assert code == 0
    (infra,) = [c for c in calls if "/etc/nginx/nginx.conf:ro" in c]
    for service in ("redis", "api-1", "api-2"):
        assert f"--add-host={service}:127.0.0.1" in infra
    mount = f"{repo}/infra/nginx/nginx.conf:/etc/nginx/nginx.conf:ro"
    assert infra.endswith(f"-v {mount} elsaquiz-web:ci nginx -t")


def _response(tmp_path: Path, missing: str = "") -> Path:
    """A HEAD response with every header of the web image's snippet except ``missing``."""
    snippet = (ROOT / "web" / "security-headers.conf").read_text(encoding="utf-8")
    headers = re.findall(r'^add_header (\S+) "(.*)" always;$', snippet, re.MULTILINE)
    lines = ["HTTP/1.1 200 OK", "Cache-Control: no-cache"]
    lines += [f"{name}: {value}" for name, value in headers if name != missing]
    response = tmp_path / "response.txt"
    response.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return response


def test_smoke_checks_the_security_headers_on_the_spa_route_and_on_an_asset(
    tmp_path: Path,
) -> None:
    code, calls, _ = _run("smoke_images.sh", ROOT, tmp_path, RESPONSE=str(_response(tmp_path)))
    assert code == 0
    requests = [c.split()[-1] for c in calls if c.startswith("exec ") and " curl " in c]
    assert requests == [
        "http://127.0.0.1:8080/",
        "http://127.0.0.1:8080/assets/index-abc.js",
    ]


def test_smoke_fails_when_a_response_lacks_a_security_header(tmp_path: Path) -> None:
    response = _response(tmp_path, missing="Content-Security-Policy")
    code, calls, stderr = _run("smoke_images.sh", ROOT, tmp_path, RESPONSE=str(response))
    assert code != 0
    assert "/ lacks Content-Security-Policy: default-src 'self';" in stderr
    started = [c.split("--name ")[1].split()[0] for c in calls if c.startswith("run --detach")]
    assert calls[-1] == f"rm --force {started[-1]}"


@pytest.mark.parametrize(
    ("snippet", "error"),
    [
        (None, "cannot read"),
        ('    add_header X-Content-Type-Options "nosniff" always;\n', "0 of 1 add_header lines"),
        (
            (
                'add_header Referrer-Policy "no-referrer" always;\n'
                "add_header X-Content-Type-Options nosniff always;\n"
            ),
            "1 of 2 add_header lines",
        ),
    ],
)
def test_smoke_fails_when_the_snippet_yields_fewer_headers_than_it_adds(
    tmp_path: Path, snippet: str | None, error: str
) -> None:
    """A header the smoke test cannot parse would otherwise go unchecked."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "smoke_images.sh", repo / "scripts")
    if snippet is not None:
        (repo / "web").mkdir()
        (repo / "web" / "security-headers.conf").write_text(snippet, encoding="utf-8")
    response = _response(tmp_path)
    code, _, stderr = _run("smoke_images.sh", ROOT, tmp_path, root=repo, RESPONSE=str(response))
    assert code != 0
    assert error in stderr
