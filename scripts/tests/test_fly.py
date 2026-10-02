# AI-ASSISTED: the Fly.io deploy: the script against a stub flyctl, its dry runs, the fly.toml files
# and the edge config's differences from the VM's.
"""``scripts/deploy/fly.sh`` runs with a stub flyctl first on ``PATH`` that records each call (and
its stdin) and answers the lookups from environment variables, so no Fly resource is touched. The
edge config is checked line by line against ``infra/nginx/nginx.conf`` and, with Docker, by
``nginx -T`` in the web image's pinned nginx."""

import os
import re
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy" / "fly.sh"
FLY = ROOT / "infra" / "fly"
BASH = shutil.which("bash") or "/bin/bash"
MAKE = shutil.which("make") or "make"
DOCKER = shutil.which("docker")
SECRET = re.compile(r"[0-9a-f]{48}")
# Inside the web Machine (and the test container): where the entrypoint renders the template.
RENDERED = "/tmp/fly/nginx.conf"  # noqa: S108

# Each call is one shell-quoted line; the stdin of a secrets import goes to $LOG.stdin.
FAKE_FLYCTL = """printf '%q ' "$@" >> "$LOG"; echo >> "$LOG"
case "$*" in
  "auth whoami") [[ -z ${SIGNED_OUT:-} ]] ;;
  "apps list "*) printf '%s' "${APPS:-}" ;;
  "volumes list "*) printf '%s' "${VOLUMES:-[]}" ;;
  "ips list --app myquiz-api "*) printf '%s' "${API_IPS:-[]}" ;;
  "ips list --app myquiz-web "*) printf '%s' "${WEB_IPS:-[]}" ;;
  "secrets import "*) cat >> "$LOG.stdin" ;;
esac"""


def _run(
    tmp_path: Path, *args: str, stdin: str = "", **env: str
) -> tuple[int, list[list[str]], str]:
    """Run fly.sh; return its exit code, the flyctl calls' arguments and its output."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stubs = {"flyctl": FAKE_FLYCTL, "curl": "true", "uv": 'echo "uv $* token=$ADMIN_TOKEN"'}
    for name, body in stubs.items():
        (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "flyctl.log"
    log.write_text("", encoding="utf-8")
    base = {k: v for k, v in os.environ.items() if not k.startswith("FLY_")}
    result = subprocess.run(
        [BASH, str(SCRIPT), *args],
        input=stdin,
        env={
            **base,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "LOG": str(log),
            "FLY_ENV_FILE": str(tmp_path / ".env.fly"),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    calls = [shlex.split(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return result.returncode, calls, result.stdout + result.stderr


def _skipped(out: str) -> list[str]:
    return [
        line.removeprefix("dry run, skipped: ") for line in out.splitlines() if "skipped" in line
    ]


def test_launch_dry_run_prints_every_create_and_runs_no_flyctl(tmp_path: Path) -> None:
    code, calls, out = _run(tmp_path, "launch", "--dry-run", FLY_APP="myquiz")
    assert (code, calls) == (0, []), out
    assert _skipped(out) == [
        f"write {tmp_path / '.env.fly'} (mode 600) with a new ADMIN_TOKEN and REDIS_PASSWORD",
        "flyctl apps create myquiz-redis --org personal",
        "flyctl apps create myquiz-api --org personal",
        "flyctl apps create myquiz-web --org personal",
        "flyctl volumes create redis_data --app myquiz-redis --region sin --size 1 --yes",
        "flyctl ips allocate-v6 --private --app myquiz-api",
        "flyctl ips allocate-v4 --shared --app myquiz-web --yes",
        "flyctl ips allocate-v6 --app myquiz-web",
        "flyctl secrets import --app myquiz-redis --stage   (stdin: REDIS_PASSWORD)",
        "flyctl secrets import --app myquiz-api --stage   (stdin: ADMIN_TOKEN, REDIS_URL)",
    ]
    assert not (tmp_path / ".env.fly").exists()
    assert not SECRET.search(out)


COMMON = ["--ha=false", "--wait-timeout", "5m", "--yes"]


def _deploys(region: str, api_image: list[str], web_image: list[str]) -> list[list[str]]:
    common = ["--primary-region", region, *COMMON]
    return [
        ["deploy", ".", "--config", "infra/fly/redis.toml", "--app", "myquiz-redis", *common,
         "--no-public-ips"],
        ["deploy", ".", "--config", "infra/fly/api.toml", "--app", "myquiz-api", *common,
         "--no-public-ips", *api_image, "--env", "ALLOWED_ORIGINS=https://myquiz-web.fly.dev"],
        ["scale", "count", "2", "--app", "myquiz-api", "--region", region, "--yes"],
        ["deploy", ".", "--config", "infra/fly/web.toml", "--app", "myquiz-web", *common,
         *web_image, "--env", "QUIZ_API_HOST=myquiz-api.flycast"],
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("args", "api_image", "web_image"),
    [
        ([], ["--image", "ghcr.io/kobars/realtime-vocab-quiz-api:main"],
         ["--image", "ghcr.io/kobars/realtime-vocab-quiz-web:main"]),
        (["--tag", "1a2b3c4"], ["--image", "ghcr.io/kobars/realtime-vocab-quiz-api:1a2b3c4"],
         ["--image", "ghcr.io/kobars/realtime-vocab-quiz-web:1a2b3c4"]),
        (["--build"], ["--dockerfile", "api/Dockerfile", "--remote-only"],
         ["--dockerfile", "web/Dockerfile", "--remote-only"]),
    ],
)  # fmt: skip
def test_deploy_dry_run_prints_redis_then_the_api_then_the_web_edge(
    tmp_path: Path, args: list[str], api_image: list[str], web_image: list[str]
) -> None:
    code, calls, out = _run(tmp_path, "deploy", *args, "--dry-run", FLY_APP="myquiz")
    assert (code, calls) == (0, []), out
    assert [shlex.split(line) for line in _skipped(out)] == [
        ["flyctl", *call] for call in _deploys("sin", api_image, web_image)
    ] + [["the", "wait"]]
    assert "live at https://myquiz-web.fly.dev/" in out


def test_destroy_dry_run_prints_the_three_deletes_without_asking(tmp_path: Path) -> None:
    code, calls, out = _run(tmp_path, "destroy", "--dry-run", FLY_APP="myquiz")
    assert (code, calls) == (0, []), out
    assert _skipped(out) == [
        f"flyctl apps destroy myquiz-{role} --yes" for role in ("web", "api", "redis")
    ]


def _env(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())


def test_launch_creates_everything_once_and_keeps_the_secrets(tmp_path: Path) -> None:
    code, calls, out = _run(tmp_path, "launch", FLY_APP="myquiz", FLY_REGION="nrt")
    assert code == 0, out
    assert calls[0] == ["auth", "whoami"]
    changes = [call for call in calls if call[1] in {"create", "allocate-v4", "allocate-v6"}]
    assert changes == [
        ["apps", "create", "myquiz-redis", "--org", "personal"],
        ["apps", "create", "myquiz-api", "--org", "personal"],
        ["apps", "create", "myquiz-web", "--org", "personal"],
        ["volumes", "create", "redis_data", "--app", "myquiz-redis", "--region", "nrt", "--size",
         "1", "--yes"],
        ["ips", "allocate-v6", "--private", "--app", "myquiz-api"],
        ["ips", "allocate-v4", "--shared", "--app", "myquiz-web", "--yes"],
        ["ips", "allocate-v6", "--app", "myquiz-web"],
    ]  # fmt: skip
    env_file = tmp_path / ".env.fly"
    assert env_file.stat().st_mode & 0o777 == 0o600
    env = _env(env_file)
    assert (env["FLY_APP"], env["FLY_REGION"], env["FLY_ORG"]) == ("myquiz", "nrt", "personal")
    assert SECRET.fullmatch(env["ADMIN_TOKEN"])
    assert SECRET.fullmatch(env["REDIS_PASSWORD"])
    # The secrets travel on stdin only.
    stdin = (tmp_path / "flyctl.log.stdin").read_text(encoding="utf-8")
    assert stdin == (
        f"REDIS_PASSWORD={env['REDIS_PASSWORD']}\nADMIN_TOKEN={env['ADMIN_TOKEN']}\n"
        f"REDIS_URL=redis://:{env['REDIS_PASSWORD']}@myquiz-redis.internal:6379/0\n"
    )
    assert not SECRET.search(out + str(calls))

    # Again, with everything there and FLY_APP from .env.fly: only the secrets, unchanged.
    (tmp_path / "flyctl.log.stdin").unlink()
    code, calls, out = _run(
        tmp_path,
        "launch",
        APPS="other \t\nmyquiz-redis \t\nmyquiz-api \t\nmyquiz-web \t\n",  # padded, as flyctl prints them
        VOLUMES='[{"id": "vol_1", "Name": "redis_data"}]',
        API_IPS='[{"Address": "fdaa:0:1::5", "Type": "private_v6"}]',
        WEB_IPS='[{"Type": "shared_v4"}, {"Type": "v6"}]',
    )
    assert code == 0, out
    assert [c[:2] for c in calls if c[0] != "auth" and c[1] != "list"] == [
        ["secrets", "import"],
        ["secrets", "import"],
    ]
    assert ["volumes", "list", "--app", "myquiz-redis", "--json"] in calls
    assert _env(env_file) == env
    assert (tmp_path / "flyctl.log.stdin").read_text(encoding="utf-8") == stdin


@pytest.mark.parametrize(
    ("args", "env", "error"),
    [
        (["launch"], {"FLY_APP": "myquiz", "SIGNED_OUT": "1"}, "run fly auth login"),
        (["deploy"], {"FLY_APP": "myquiz", "SIGNED_OUT": "1"}, "run fly auth login"),
        (["launch"], {}, "set FLY_APP"),
        (["launch"], {"FLY_APP": "My_Quiz"}, "FLY_APP 'My_Quiz' must be lower-case"),
        (["deploy"], {"FLY_APP": "myquiz"}, "run make fly-launch first"),
        (["deploy", "--tag"], {"FLY_APP": "myquiz"}, "--tag needs a value"),
        (["status", "--now"], {"FLY_APP": "myquiz"}, "unknown option: --now"),
    ],
)
def test_the_script_stops_before_changing_anything(
    tmp_path: Path, args: list[str], env: dict[str, str], error: str
) -> None:
    code, calls, out = _run(tmp_path, *args, **env)
    assert code == 1
    assert error in out
    assert calls in ([], [["auth", "whoami"]])


def test_another_prefix_than_the_secrets_file_names_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".env.fly").write_text("FLY_APP=myquiz\nADMIN_TOKEN=a\nREDIS_PASSWORD=b\n")
    code, calls, out = _run(tmp_path, "launch", FLY_APP="otherquiz")
    assert (code, calls) == (1, [])
    assert "holds the secrets of myquiz" in out


def test_deploy_runs_in_order_and_waits_for_the_https_url(tmp_path: Path) -> None:
    (tmp_path / ".env.fly").write_text("FLY_APP=myquiz\nFLY_REGION=fra\n", encoding="utf-8")
    code, calls, out = _run(tmp_path, "deploy")
    assert code == 0, out
    image = "ghcr.io/kobars/realtime-vocab-quiz-{}:main"
    assert calls == [
        ["auth", "whoami"],
        *_deploys("fra", ["--image", image.format("api")], ["--image", image.format("web")]),
    ]
    assert "The quiz app is live at https://myquiz-web.fly.dev/" in out


def test_demo_passes_the_token_in_the_environment_only(tmp_path: Path) -> None:
    (tmp_path / ".env.fly").write_text(f"FLY_APP=myquiz\nADMIN_TOKEN={'ab' * 24}\n")
    code, calls, out = _run(tmp_path, "demo")
    assert (code, calls) == (0, []), out
    assert out.strip() == (
        "uv run --project api --locked python scripts/seed.py --api-url "
        f"https://myquiz-web.fly.dev/api --public-url https://myquiz-web.fly.dev token={'ab' * 24}"
    )


# flyctl pads each name with blanks.
DESTROY_ENV = {
    "FLY_APP": "myquiz",
    "APPS": "myquiz-api \t\nmyquiz-redis \t\nmyquiz-web \t\nother \t\n",
}


def test_destroy_deletes_the_three_apps_once_the_prefix_is_typed(tmp_path: Path) -> None:
    code, calls, out = _run(tmp_path, "destroy", stdin="myquiz\n", **DESTROY_ENV)
    assert code == 0, out
    assert [c for c in calls if c[1] == "destroy"] == [
        ["apps", "destroy", f"myquiz-{role}", "--yes"] for role in ("web", "api", "redis")
    ]


@pytest.mark.parametrize("answer", ["", "yes\n", "myquiz-web\n"])
def test_destroy_deletes_nothing_without_the_prefix(tmp_path: Path, answer: str) -> None:
    code, calls, out = _run(tmp_path, "destroy", stdin=answer, **DESTROY_ENV)
    assert code == 1
    assert "nothing deleted" in out
    assert not any("destroy" in call for call in calls)


def test_the_make_targets_pass_their_variables_to_the_script() -> None:
    def dry(*args: str) -> str:
        env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MAKELEVEL", "MFLAGS"}}
        result = subprocess.run(
            [MAKE, "-n", "--no-print-directory", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return " ".join(result.stdout.split())

    assert dry("fly-launch", "DRY_RUN=1") == "scripts/deploy/fly.sh launch --dry-run"
    assert dry("fly-deploy", "FLY_IMAGE_TAG=v1.2.0", "BUILD=1") == (
        "scripts/deploy/fly.sh deploy --build --tag 'v1.2.0'"
    )
    for target in ("demo", "status", "destroy"):
        assert dry(f"fly-{target}") == f"scripts/deploy/fly.sh {target}"


def _toml(role: str) -> dict:  # type: ignore[type-arg]
    with (FLY / f"{role}.toml").open("rb") as file:
        return tomllib.load(file)


@pytest.mark.parametrize(
    ("role", "memory"), [("web", "256mb"), ("api", "512mb"), ("redis", "512mb")]
)
def test_each_app_runs_in_one_region_on_a_small_shared_machine_and_restarts(
    role: str, memory: str
) -> None:
    config = _toml(role)
    assert config["primary_region"] == "sin"
    assert config["vm"] == [{"size": "shared-cpu-1x", "memory": memory}]
    assert config["restart"] == [{"policy": "always"}]


def test_no_machine_ever_stops_for_lack_of_traffic() -> None:
    web, api = _toml("web")["http_service"], _toml("api")["services"]
    assert (web["auto_stop_machines"], web["min_machines_running"]) == ("off", 1)
    assert [(s["auto_stop_machines"], s["min_machines_running"]) for s in api] == [("off", 2)]
    assert "services" not in _toml("redis")
    assert "http_service" not in _toml("redis")


def test_the_web_edge_is_public_over_https_and_checked_through_nginx() -> None:
    config = _toml("web")
    service = config["http_service"]
    assert (service["internal_port"], service["force_https"]) == (8081, True)
    assert [check["path"] for check in service["checks"]] == ["/"]
    assert config["files"] == [
        {"guest_path": "/etc/nginx/templates/fly/nginx.conf.template",
         "local_path": "infra/fly/nginx.conf.template"},
    ]  # fmt: skip
    # From the repository root, where fly.sh runs flyctl deploy.
    assert (ROOT / config["files"][0]["local_path"]).is_file()
    assert config["experimental"]["cmd"][:3] == ["nginx", "-c", RENDERED]


def test_the_api_is_raw_tcp_on_8000_and_routed_only_when_ready() -> None:
    (service,) = _toml("api")["services"]
    assert (service["internal_port"], service["protocol"]) == (8000, "tcp")
    # Raw TCP: nginx's headers and WebSocket frames pass untouched.
    assert service["ports"] == [{"port": 8000, "handlers": []}]
    assert [check["path"] for check in service["http_checks"]] == ["/readyz"]
    assert _toml("api")["env"]["TRUSTED_PROXIES"] == "172.16.0.0/16"


def test_redis_keeps_its_data_on_a_volume_with_the_compose_durability() -> None:
    config = _toml("redis")
    assert config["mounts"] == [{"source": "redis_data", "destination": "/data"}]
    assert config["checks"]["redis"]["port"] == 6379
    command = config["experimental"]["cmd"][2]
    for option in (
        "--appendonly yes",
        "--appendfsync everysec",
        "--maxmemory-policy noeviction",
        '--requirepass "$REDIS_PASSWORD"',
        "--bind '* ::*'",  # .internal names resolve to IPv6 addresses only
        "--dir /data/redis",
    ):
        assert option in command
    # The compose stack's pinned image, by digest alone: flyctl refuses a tag with a digest.
    image = config["build"]["image"]
    name, digest = image.split("@")
    assert name == "docker.io/library/redis"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert re.search(rf"image: redis:\S+@{digest}$", compose, re.MULTILINE)


def _lines(path: Path) -> list[str]:
    """The config's lines without comments and blank lines."""
    text = path.read_text(encoding="utf-8")
    return [line for line in (raw.split("#")[0].rstrip() for raw in text.splitlines()) if line]


def test_the_fly_edge_is_the_vm_edge_with_only_the_fly_lines_changed() -> None:
    """A change to the VM edge must reach the Fly edge too, and the VM edge keeps its own
    real-address source: Caddy's X-Forwarded-For from the edge network."""
    vm = _lines(ROOT / "infra" / "nginx" / "nginx.conf")
    fly = _lines(FLY / "nginx.conf.template")
    removed = [line for line in vm if line not in fly]
    added = [line for line in fly if line not in vm]
    assert removed == [
        "    include /tmp/edge/*.conf;",
        "    resolver 127.0.0.11 valid=5s ipv6=off;",
        "        server api-1:8000 resolve max_fails=0;",
        "        server api-2:8000 resolve max_fails=0;",
        "        server web:8080 resolve;",
        "        listen 8080;",
    ]
    assert added == [
        "    set_real_ip_from 172.16.0.0/16;",
        "    real_ip_header Fly-Client-IP;",
        "    resolver [fdaa::3] valid=5s ipv6=on;",
        "        server ${QUIZ_API_HOST}:8000 resolve max_fails=0;",
        "    include /etc/nginx/mime.types;",
        "    default_type application/octet-stream;",
        "    include /etc/nginx/conf.d/default.conf;",
        "        server 127.0.0.1:8080;",
        "        listen 8081;",
        '            add_header Strict-Transport-Security "max-age=31536000" always;',
    ]
    assert not any("real_ip" in line or "Fly-Client-IP" in line for line in vm)
    assert _lines(ROOT / "infra" / "nginx" / "real-ip.conf.template") == [
        "set_real_ip_from ${EDGE_SUBNET};",
        "real_ip_header X-Forwarded-For;",
    ]


def _docker_runs() -> bool:
    """A daemon too busy to answer within 30 s counts as not running."""
    if DOCKER is None:
        return False
    try:
        info = subprocess.run([DOCKER, "info"], capture_output=True, check=False, timeout=30)
    except subprocess.TimeoutExpired:
        return False
    return info.returncode == 0


@pytest.mark.skipif(DOCKER is None, reason="needs Docker")
@pytest.mark.slow
def test_the_rendered_fly_edge_passes_nginx_t_and_trusts_only_flys_proxy() -> None:
    """As on Fly: the web image's site and headers, and the template rendered by the entrypoint
    with QUIZ_API_HOST alone substituted."""
    if not _docker_runs():
        pytest.skip("the Docker daemon is not running")
    dockerfile = (ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")
    image = re.search(r"^FROM (nginxinc/nginx-unprivileged:\S+)", dockerfile, re.MULTILINE)
    assert image
    mounts = {
        FLY / "nginx.conf.template": "/etc/nginx/templates/fly/nginx.conf.template",
        ROOT / "web" / "nginx.conf": "/etc/nginx/conf.d/default.conf",
        ROOT / "web" / "security-headers.conf": "/etc/nginx/security-headers.conf",
    }
    env = {**_toml("web")["env"], "QUIZ_API_HOST": "myquiz-api.flycast", "remote_addr": "x"}
    result = subprocess.run(
        [str(DOCKER), "run", "--rm", "--network", "none", "--tmpfs", "/tmp",  # noqa: S108
         *(f"-v{src}:{dst}:ro" for src, dst in mounts.items()),
         *(f"-e{k}={v}" for k, v in env.items()),
         image[1], "nginx", "-T", "-c", RENDERED],
        capture_output=True, text=True, check=False, timeout=50,
    )  # fmt: skip
    if result.returncode != 0 and "Unable to find image" in result.stderr:
        pytest.skip(f"cannot pull {image[1]}")
    assert "test is successful" in result.stderr, result.stderr
    lines = [line.strip() for line in result.stdout.splitlines()]
    assert [line for line in lines if line.startswith(("set_real_ip_from", "real_ip"))] == [
        "set_real_ip_from 172.16.0.0/16;",
        "real_ip_header Fly-Client-IP;",
    ]
    assert "server myquiz-api.flycast:8000 resolve max_fails=0;" in lines
    # The site's scripts and stylesheets go out with their content types.
    assert "# configuration file /etc/nginx/mime.types:" in lines
    assert any(re.fullmatch(r"application/javascript\s+js;", line) for line in lines)
    assert (
        "log_format edge '$remote_addr [$time_local] \"$request_method $uri $server_protocol\" '"
        in lines
    )


def test_the_fly_secrets_file_stays_out_of_git_and_the_images() -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".env.fly"],  # noqa: S607
        cwd=ROOT,
        check=False,
    )
    assert ignored.returncode == 0
    assert "**/.env.fly" in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
