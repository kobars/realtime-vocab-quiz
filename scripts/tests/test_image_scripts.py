# AI-ASSISTED: the image smoke and nginx check scripts, run against a fake docker command.
"""``scripts/smoke_images.sh`` and ``scripts/check_nginx.sh`` with a ``docker`` stub first on
``PATH`` that logs every call, so the tests need no Docker daemon."""

import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Answers `id -u` with a non-root uid and lists three compose services, unless $COMPOSE_FAILS is
# set. `docker inspect` fails, unless $RESPONSE names a file: then every container whose name
# lacks $UNHEALTHY is healthy, has one hashed asset and answers each request with that file. The
# API image's store is $STORE (default redis) and its Lua scripts are the lines of $LUA_FILES.
# The smoke test's Redis answers PING unless $REDIS_DOWN is set. `nginx -T` prints the rendered
# real-ip directive unless $NO_REAL_IP is set.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
case "$*" in
  *" id -u") echo 10001 ;;
  "compose "*"config --services") [[ -z "${COMPOSE_FAILS:-}" ]] || exit 1
    printf 'redis\\napi-1\\napi-2\\n' ;;
  "inspect "*) [[ -n "${RESPONSE:-}" && "$*" != *"${UNHEALTHY:-none}"* ]] || exit 1
    echo "running healthy" ;;
  "exec "*" find "*) echo /usr/share/nginx/html/assets/index-abc.js ;;
  "exec "*" curl "*) cat "$RESPONSE" ;;
  *"print(Settings().store)"*) echo "${STORE:-redis}" ;;
  *" redis-cli ping") [[ -z "${REDIS_DOWN:-}" ]] || exit 1 ;;
  *"rglob('*.lua')"*) cat "${LUA_FILES:-/dev/null}" ;;
  "run "*" nginx -T") [[ -n "${NO_REAL_IP:-}" ]] || echo 'set_real_ip_from 10.89.79.0/24;' ;;
esac
"""
LUA = "api/src/quiz/adapters/redis/lua/"
COMPOSE_REDIS = re.findall(r"image: (redis:\S+)", (ROOT / "compose.yaml").read_text())[0]


def _run(
    script: str,
    cwd: Path,
    tmp_path: Path,
    root: Path = ROOT,
    env_extra: Mapping[str, str] | None = None,
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
    env = {**os.environ, "PATH": path, "DOCKER_LOG": str(log), **(env_extra or {})}
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


def _repo_with_infra_nginx_conf(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "infra" / "nginx").mkdir(parents=True)
    (repo / "infra" / "nginx" / "nginx.conf").write_text("events {}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)  # noqa: S607
    subprocess.run(["git", "add", "infra"], cwd=repo, check=True)  # noqa: S607
    return repo


def test_infra_nginx_config_is_tested_with_the_compose_service_names_resolvable(
    tmp_path: Path,
) -> None:
    repo = _repo_with_infra_nginx_conf(tmp_path)
    code, calls, _ = _run("check_nginx.sh", repo, tmp_path)
    assert code == 0
    (infra,) = [c for c in calls if "/etc/nginx/nginx.conf:ro" in c]
    for service in ("redis", "api-1", "api-2"):
        assert f"--add-host={service}:127.0.0.1" in infra
    mount = f"{repo}/infra/nginx/nginx.conf:/etc/nginx/nginx.conf:ro"
    assert infra.endswith(f"-v {mount} elsaquiz-web:ci nginx -t")


def test_the_nginx_check_also_runs_with_the_real_ip_template_rendered(tmp_path: Path) -> None:
    """compose.prod.yaml's nginx: the entrypoint renders the template into /tmp/edge/."""
    repo = _repo_with_infra_nginx_conf(tmp_path)
    (repo / "infra" / "nginx" / "real-ip.conf.template").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "infra"], cwd=repo, check=True)  # noqa: S607
    code, calls, _ = _run("check_nginx.sh", repo, tmp_path)
    assert code == 0
    (rendered,) = [c for c in calls if c.endswith(" nginx -T")]
    assert "-e NGINX_ENVSUBST_OUTPUT_DIR=/tmp -e EDGE_SUBNET=10.89.79.0/24" in rendered
    template = f"{repo}/infra/nginx/real-ip.conf.template"
    assert f"-v {template}:/etc/nginx/templates/edge/real-ip.conf.template:ro" in rendered


def test_the_nginx_check_fails_when_the_rendered_template_is_not_included(tmp_path: Path) -> None:
    repo = _repo_with_infra_nginx_conf(tmp_path)
    (repo / "infra" / "nginx" / "real-ip.conf.template").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "infra"], cwd=repo, check=True)  # noqa: S607
    code, _, _ = _run("check_nginx.sh", repo, tmp_path, env_extra={"NO_REAL_IP": "1"})
    assert code != 0


def test_the_nginx_check_stops_when_compose_cannot_list_the_services(tmp_path: Path) -> None:
    """Compose refuses to read the file while the full stack's secrets are unset."""
    repo = _repo_with_infra_nginx_conf(tmp_path)
    code, calls, _ = _run("check_nginx.sh", repo, tmp_path, env_extra={"COMPOSE_FAILS": "1"})
    assert code != 0
    assert not [c for c in calls if "/etc/nginx/nginx.conf:ro" in c]


def _response(tmp_path: Path, missing: str = "") -> Path:
    """A HEAD response with every header of the web image's snippet except ``missing``."""
    snippet = (ROOT / "web" / "security-headers.conf").read_text(encoding="utf-8")
    headers = re.findall(r'^add_header (\S+) "(.*)" always;$', snippet, re.MULTILINE)
    lines = ["HTTP/1.1 200 OK", "Cache-Control: no-cache"]
    lines += [f"{name}: {value}" for name, value in headers if name != missing]
    response = tmp_path / "response.txt"
    response.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return response


def _lua_files(tmp_path: Path, missing: str = "") -> Path:
    """The repo's Lua scripts, relative to the lua/ folder, except ``missing``."""
    lua = ROOT / LUA
    names = sorted(str(path.relative_to(lua)) for path in lua.rglob("*.lua"))
    listing = tmp_path / "lua.txt"
    listing.write_text("".join(f"{name}\n" for name in names if name != missing), encoding="utf-8")
    return listing


def _passing(tmp_path: Path) -> dict[str, str]:
    """The environment in which every image passes the smoke test."""
    return {"RESPONSE": str(_response(tmp_path)), "LUA_FILES": str(_lua_files(tmp_path))}


def test_smoke_checks_the_security_headers_on_the_spa_route_and_on_an_asset(
    tmp_path: Path,
) -> None:
    code, calls, _ = _run("smoke_images.sh", ROOT, tmp_path, env_extra=_passing(tmp_path))
    assert code == 0
    requests = [c.split()[-1] for c in calls if c.startswith("exec ") and " curl " in c]
    assert requests == [
        "http://127.0.0.1:8080/",
        "http://127.0.0.1:8080/assets/index-abc.js",
    ]


def test_smoke_fails_when_a_response_lacks_a_security_header(tmp_path: Path) -> None:
    response = _response(tmp_path, missing="Content-Security-Policy")
    code, calls, stderr = _run(
        "smoke_images.sh", ROOT, tmp_path, env_extra={"RESPONSE": str(response)}
    )
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
    code, _, stderr = _run(
        "smoke_images.sh", ROOT, tmp_path, root=repo, env_extra={"RESPONSE": str(response)}
    )
    assert code != 0
    assert error in stderr


def test_smoke_runs_the_api_image_on_a_redis_of_its_own_until_it_is_ready(tmp_path: Path) -> None:
    code, calls, _ = _run("smoke_images.sh", ROOT, tmp_path, env_extra=_passing(tmp_path))
    assert code == 0
    (network,) = [c.split()[-1] for c in calls if c.startswith("network create ")]
    redis = network.replace("smoke-", "smoke-redis-")
    assert f"run --detach --name {redis} --network {network} {COMPOSE_REDIS}" in calls
    (api,) = [c for c in calls if c.startswith("run --detach") and "elsaquiz-api" in c]
    assert f"--network {network} -e REDIS_URL=redis://{redis}:6379/0" in api
    assert "STORE" not in api  # the image's default
    name = api.split("--name ")[1].split()[0]
    (ready,) = [c for c in calls if c.startswith(f"exec {name} python")]
    assert "http://127.0.0.1:8000/readyz" in ready
    assert calls[-2:] == [f"rm --force {redis}", f"network rm {network}"]


def test_smoke_removes_the_redis_and_its_network_when_the_api_never_gets_healthy(
    tmp_path: Path,
) -> None:
    env = _passing(tmp_path) | {"UNHEALTHY": "elsaquiz-api"}
    code, calls, _ = _run("smoke_images.sh", ROOT, tmp_path, env_extra=env)
    assert code != 0
    (network,) = [c.split()[-1] for c in calls if c.startswith("network create ")]
    assert calls[-2:] == [
        f"rm --force {network.replace('smoke-', 'smoke-redis-')}",
        f"network rm {network}",
    ]


@pytest.mark.parametrize("missing", ["score_answer.lua", "lib/points.lua"])
def test_smoke_fails_when_the_api_image_lacks_a_lua_script(tmp_path: Path, missing: str) -> None:
    env = _passing(tmp_path) | {"LUA_FILES": str(_lua_files(tmp_path, missing))}
    code, calls, stderr = _run("smoke_images.sh", ROOT, tmp_path, env_extra=env)
    assert code != 0
    assert "API image Lua scripts differ from the repo" in stderr
    assert f"< {missing}" in stderr
    assert not [c for c in calls if c.startswith("network create ")]


def test_smoke_fails_when_the_api_image_defaults_to_the_memory_store(tmp_path: Path) -> None:
    env = _passing(tmp_path) | {"STORE": "memory"}
    code, _, stderr = _run("smoke_images.sh", ROOT, tmp_path, env_extra=env)
    assert code != 0
    assert "elsaquiz-api:ci defaults to STORE=memory, not redis" in stderr


def test_smoke_stops_when_its_redis_never_answers(tmp_path: Path) -> None:
    """A clear error, not an API node started against a Redis that is not there."""
    fast = tmp_path / "fast"
    fast.mkdir()
    (fast / "sleep").write_text("#!/bin/sh\n", encoding="utf-8")  # no 15 s wait in the test
    (fast / "sleep").chmod(0o755)
    path = f"{tmp_path / 'bin'}{os.pathsep}{fast}{os.pathsep}{os.environ['PATH']}"
    env = _passing(tmp_path) | {"REDIS_DOWN": "1", "PATH": path}
    code, calls, stderr = _run("smoke_images.sh", ROOT, tmp_path, env_extra=env)
    assert code != 0
    assert "Redis did not answer PING within 15 s" in stderr
    assert not [c for c in calls if c.startswith("run --detach") and "elsaquiz-api" in c]
    (network,) = [c.split()[-1] for c in calls if c.startswith("network create ")]
    assert calls[-2:] == [
        f"rm --force {network.replace('smoke-', 'smoke-redis-')}",
        f"network rm {network}",
    ]
