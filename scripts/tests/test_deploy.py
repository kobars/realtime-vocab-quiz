# AI-ASSISTED: the VM install script, the update rollback, backup and restore, and the cloud-init
# user data, run against stub commands.
"""``scripts/deploy/install.sh`` is sourced (sourcing runs nothing) to call one helper at a time,
with stubs first on ``PATH`` for curl, getent, ss, docker, git and make; ``scripts/deploy/ops.sh``
runs in a copy of the scripts. One test runs the whole install with ``--dry-run`` in an offline
``ubuntu:24.04`` container, when Docker is available."""

import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest
from pre_commit.yaml import yaml_load

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy"
UBUNTU = "ubuntu:24.04@sha256:a853f94d226358a79c740cfc7bce0c289748f3fe3488d921d038ccd752c61b60"
SECRET = re.compile(r"[0-9a-f]{48}")
DOCKER = shutil.which("docker")


def _stubs(tmp_path: Path, **bodies: str) -> Path:
    """A folder of executable stubs, one per name, each running its shell body."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in bodies.items():
        stub = bin_dir / name
        stub.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
        stub.chmod(0o755)
    return bin_dir


def _run(
    args: list[str], bin_dir: Path, env: dict[str, str], cwd: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    return subprocess.run(
        args,
        cwd=cwd,
        env={**os.environ, "PATH": path, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def _sourced(
    tmp_path: Path, call: str, *args: str, env: dict[str, str] | None = None, **stubs: str
) -> subprocess.CompletedProcess[str]:
    """Source install.sh and run one helper call; ARGS are $2, $3 and so on."""
    install = str(DEPLOY / "install.sh")
    return _run(
        ["bash", "-c", f'. "$1"; {call}', "bash", install, *args],
        _stubs(tmp_path, **stubs),
        env or {},
    )


@pytest.mark.parametrize("ip", ["203.0.113.7", "1.0.0.0", "255.255.255.255", "10.01.0.9"])
def test_an_ipv4_address_is_valid(tmp_path: Path, ip: str) -> None:
    assert _sourced(tmp_path, f"valid_ipv4 '{ip}'").returncode == 0


@pytest.mark.parametrize(
    "ip", ["256.1.1.1", "1.2.3", "1.2.3.4.5", "a.b.c.d", "", " 1.2.3.4", "<html>"]
)
def test_anything_else_is_not_an_ipv4_address(tmp_path: Path, ip: str) -> None:
    assert _sourced(tmp_path, f"valid_ipv4 '{ip}'").returncode == 1


# The metadata service answers $META (or fails when it is unset); the echo service answers $ECHO.
FAKE_CURL = """case "$*" in
  *169.254.169.254*) [[ -n ${META:-} ]] && printf '%s\\n' "$META" ;;
  *checkip*) [[ -n ${ECHO:-} ]] && printf '%s\\n' "$ECHO" ;;
  *) exit 1 ;;
esac"""


@pytest.mark.parametrize(
    ("meta", "echo", "found"),
    [
        ("203.0.113.7", "198.51.100.2", "203.0.113.7"),  # the metadata service first
        ("", "198.51.100.2", "198.51.100.2"),  # not a Droplet: the echo service
        ("<html>404</html>", "198.51.100.2", "198.51.100.2"),  # an answer that is not an address
        ("", "300.1.1.1", None),
    ],
)
def test_the_public_ip_comes_from_the_metadata_service_then_the_echo_service(
    tmp_path: Path, meta: str, echo: str, found: str | None
) -> None:
    result = _sourced(tmp_path, "public_ipv4", env={"META": meta, "ECHO": echo}, curl=FAKE_CURL)
    assert (result.returncode, result.stdout.strip()) == ((0, found) if found else (1, ""))


def test_the_domain_is_the_one_given_else_the_ip_on_sslip_io(tmp_path: Path) -> None:
    call = "choose_domain quiz.example.com 203.0.113.7; choose_domain '' 203.0.113.7"
    assert _sourced(tmp_path, call).stdout.split() == ["quiz.example.com", "203.0.113.7.sslip.io"]


@pytest.mark.parametrize(
    ("records", "error"),
    [
        ("203.0.113.7", None),
        ("198.51.100.2", "resolves to 198.51.100.2, not to this VM (203.0.113.7)"),
        ("203.0.113.7 198.51.100.2", "resolves to 198.51.100.2 203.0.113.7, not"),
        ("", "resolves to nothing, not to this VM"),
    ],
)
def test_a_domain_must_point_at_this_vm_before_caddy_asks_for_a_certificate(
    tmp_path: Path, records: str, error: str | None
) -> None:
    getent = 'for a in $RECORDS; do echo "$a STREAM $2"; done; [[ -n $RECORDS ]] || exit 2'
    result = _sourced(
        tmp_path,
        "check_dns quiz.example.com 203.0.113.7 0",
        env={"RECORDS": records},
        getent=getent,
    )
    assert result.returncode == (1 if error else 0)
    assert error is None or error in result.stderr


def test_the_vms_own_sslip_io_name_needs_no_lookup(tmp_path: Path) -> None:
    result = _sourced(tmp_path, "check_dns 203.0.113.7.sslip.io 203.0.113.7 0", getent="exit 2")
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("release", "code"),
    [
        ('ID=ubuntu\nVERSION_ID="24.04"\n', 0),
        ('ID=ubuntu\nVERSION_ID="22.04"\n', 0),
        ('ID=ubuntu\nVERSION_ID="20.04"\n', 1),
        ('ID=debian\nVERSION_ID="12"\n', 1),
    ],
)
def test_only_ubuntu_22_04_and_24_04_are_supported(tmp_path: Path, release: str, code: int) -> None:
    (tmp_path / "os-release").write_text(release, encoding="utf-8")
    result = _sourced(tmp_path, f"check_os '{tmp_path / 'os-release'}'")
    assert result.returncode == code
    assert not code or "unsupported OS" in result.stderr


def test_busy_web_ports_stop_the_install_unless_this_stacks_caddy_holds_them(
    tmp_path: Path,
) -> None:
    ss = '[[ $* == *":80"* ]] && echo "LISTEN 0 511 0.0.0.0:80 0.0.0.0:*"; true'
    busy = _sourced(tmp_path, "check_ports", ss=ss, docker="true")
    assert busy.returncode == 1
    assert "port(s) 80 already in use" in busy.stderr
    assert _sourced(tmp_path, "check_ports", ss=ss, docker="echo 0123abcd").returncode == 0


def _env(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def test_the_env_gets_new_secrets_once_and_keeps_them(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    render = f'render_env "$2" "{env}" "$3"'
    _sourced(tmp_path, render, str(ROOT / ".env.prod.example"), "a.sslip.io")
    first = _env(env)
    example = _env(ROOT / ".env.prod.example")
    assert first["DOMAIN"] == "a.sslip.io"
    assert SECRET.fullmatch(first["ADMIN_TOKEN"])
    assert SECRET.fullmatch(first["REDIS_PASSWORD"])
    assert first["ADMIN_TOKEN"] != first["REDIS_PASSWORD"]
    assert {
        k: v for k, v in first.items() if k not in {"DOMAIN", "ADMIN_TOKEN", "REDIS_PASSWORD"}
    } == {k: v for k, v in example.items() if k not in {"DOMAIN", "ADMIN_TOKEN", "REDIS_PASSWORD"}}
    assert env.stat().st_mode & 0o077 == 0
    for domain, expected in (("", "a.sslip.io"), ("quiz.example.com", "quiz.example.com")):
        _sourced(tmp_path, render, str(env), domain)
        assert _env(env) == {**first, "DOMAIN": expected}


OLD_ENV = "DOMAIN=quiz.example.com\nADMIN_TOKEN=old\n"
# The checkout is at the commit in $STATE; make fails on $BAD_UP and readyz on $BAD_READY.
FAKE_GIT = """echo "git $*" >> "$LOG"
case "$1" in
  rev-parse) cat "$STATE" ;;
  pull) [[ -z ${PULL_FAILS:-} ]] || exit 1; echo new > "$STATE" ;;
  reset) echo "$3" > "$STATE" ;;
esac"""
FAKE_MAKE = 'echo "make $* @ $(cat "$STATE")" >> "$LOG"; [[ $(cat "$STATE") != "${BAD_UP:-}" ]]'
FAKE_READY = '[[ $(cat "$STATE") != "${BAD_READY:-}" ]]'


# compose's Redis counts one more save after each BGSAVE; each cp writes a file.
FAKE_DOCKER = """echo "docker $*" >> "$LOG"
saves="$(cat "$LOG.saves" 2>/dev/null || echo 0)"
case "$*" in
  *"redis-cli BGSAVE") echo $((saves + 1)) > "$LOG.saves" ;;
  *"redis-cli INFO persistence")
    printf '%s\\r\\n' rdb_bgsave_in_progress:0 "rdb_saves:$saves" rdb_last_bgsave_status:ok ;;
  *" cp stack-redis:/data/dump.rdb "*) echo REDIS > "${@: -1}" ;;
  *" cp caddy:/data "*) mkdir -p "${@: -1}/caddy" && echo KEY > "${@: -1}/caddy/key.pem" ;;
esac"""


def _ops(tmp_path: Path, *args: str, **env: str) -> tuple[int, list[str], str, Path]:
    """Run ops.sh from a copy; return its exit code, the stubs' calls, its output and the copy."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copytree(DEPLOY, repo / "scripts" / "deploy", dirs_exist_ok=True)
    if not (repo / ".env").exists():
        (repo / ".env").write_text(OLD_ENV, encoding="utf-8")
    state, log = tmp_path / "state", tmp_path / "calls.log"
    if not state.exists():
        state.write_text("old\n", encoding="utf-8")
    log.write_text("", encoding="utf-8")
    bin_dir = _stubs(tmp_path, git=FAKE_GIT, make=FAKE_MAKE, curl=FAKE_READY, docker=FAKE_DOCKER)
    result = _run(
        ["bash", str(repo / "scripts" / "deploy" / "ops.sh"), *args],
        bin_dir,
        # COPYFILE_DISABLE: macOS's tar adds no ._ files.
        {
            "STATE": str(state),
            "LOG": str(log),
            "READY_TIMEOUT": "0",
            "COPYFILE_DISABLE": "1",
            **env,
        },
        cwd=tmp_path,
    )
    return (
        result.returncode,
        log.read_text(encoding="utf-8").splitlines(),
        result.stdout + result.stderr,
        repo,
    )


@pytest.mark.parametrize(
    ("env", "calls", "message"),
    [
        ({}, ["make prod-up @ new"], "Updated old -> new"),
        (
            {"BAD_UP": "new"},
            ["make prod-up @ new", "git reset --keep old", "make prod-up @ old"],
            "rolled back to old, which is ready again",
        ),
        (
            {"BAD_READY": "new"},
            ["make prod-up @ new", "git reset --keep old", "make prod-up @ old"],
            "rolled back to old, which is ready again",
        ),
        (
            {"BAD_UP": "new", "BAD_READY": "old"},
            ["make prod-up @ new", "git reset --keep old", "make prod-up @ old"],
            "old is not ready either",
        ),
        ({"PULL_FAILS": "1"}, [], "nothing changed, the stack still runs old"),
    ],
)
def test_an_update_that_does_not_get_ready_rolls_back_to_the_commit_that_ran(
    tmp_path: Path, env: dict[str, str], calls: list[str], message: str
) -> None:
    code, log, out, _ = _ops(tmp_path, "update", **env)
    assert code == (0 if env == {} else 1), out
    assert [c for c in log if not c.startswith(("git rev-parse", "git pull"))] == calls
    assert message in out


def test_a_backup_holds_the_redis_snapshot_the_certificates_and_env_and_restores(
    tmp_path: Path,
) -> None:
    code, log, out, repo = _ops(tmp_path, "backup", "out/b.tar.gz")
    assert code == 0, out
    backup = repo / "out" / "b.tar.gz"  # relative to the checkout
    assert backup.stat().st_mode & 0o077 == 0  # it holds the secrets and the private keys
    with tarfile.open(backup) as tar:
        assert {m.name for m in tar.getmembers() if m.isfile()} == {
            ".env",
            "redis/dump.rdb",
            "caddy/caddy/key.pem",
        }
    assert any(c.endswith("redis-cli BGSAVE") for c in log)

    fresh = "DOMAIN=quiz.example.com\nADMIN_TOKEN=fresh\n"
    (repo / ".env").write_text(fresh, encoding="utf-8")
    code, log, out, _ = _ops(tmp_path, "restore", str(backup))
    assert code == 0, out
    assert (repo / ".env").read_text(encoding="utf-8") == OLD_ENV
    assert (repo / ".env.before-restore").read_text(encoding="utf-8") == fresh
    runs = [c for c in log if " run --rm --no-deps --user 0 " in c]
    services = [re.findall(r"-v (\S+):/backup:ro --entrypoint sh (\S+) -c", run) for run in runs]
    assert [found[0][1] for found in services] == ["stack-redis", "caddy"]
    assert all(found[0][0].endswith(("/redis", "/caddy")) for found in services)
    assert log[-1] == "make prod-up @ old"


@pytest.mark.skipif(DOCKER is None, reason="needs Docker")
@pytest.mark.slow
def test_the_install_writes_env_once_in_a_fresh_ubuntu() -> None:
    """Offline, as root, without Docker in the container: --dry-run prints the package, clone and
    stack commands and writes .env; a run with a domain that does not resolve stops before them."""
    script = """set -u
mkdir -p /opt/q && cp /example /opt/q/.env.prod.example
bash /install.sh --dry-run --dir /opt/q --ip 203.0.113.7 && cp /opt/q/.env /tmp/first
bash /install.sh --dry-run --dir /opt/q --ip 203.0.113.7 > /dev/null
bash /install.sh --dry-run --dir /opt/q --ip 203.0.113.7 --domain quiz.example.com > /dev/null
echo "exit=$? mode=$(stat -c %a /opt/q/.env)"; cat /tmp/first; echo ---; cat /opt/q/.env"""
    result = subprocess.run(
        [
            str(DOCKER),
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{DEPLOY / 'install.sh'}:/install.sh:ro",
            "-v",
            f"{ROOT / '.env.prod.example'}:/example:ro",
            UBUNTU,
            "bash",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=50,
    )
    if (
        result.returncode != 0
        and "Unable to find image" in result.stderr
        and "error" in result.stderr.lower()
    ):
        pytest.skip(f"cannot pull {UBUNTU}")
    out = result.stdout
    for skipped in (
        "apt-get install -yq ca-certificates",
        "get.docker.com",
        "git clone --quiet --branch main",
        "make -C /opt/q prod-up",
    ):
        assert re.search(rf"^dry run, skipped: .*{re.escape(skipped)}", out, re.MULTILINE), skipped
    assert "The quiz app is live at https://203.0.113.7.sslip.io/" in out
    first, last = out[out.index("exit=") :].split("---")
    assert "exit=1 mode=600" in first
    assert "quiz.example.com resolves to nothing, not to this VM (203.0.113.7)" in result.stderr
    first_env = dict(
        line.split("=", 1)
        for line in first.splitlines()[1:]
        if "=" in line and not line.startswith("#")
    )
    last_env = dict(
        line.split("=", 1) for line in last.splitlines() if "=" in line and not line.startswith("#")
    )
    assert first_env["DOMAIN"] == "203.0.113.7.sslip.io"
    assert SECRET.fullmatch(first_env["ADMIN_TOKEN"])
    assert last_env == {**first_env, "DOMAIN": "quiz.example.com"}  # the same secrets


def test_the_cloud_init_user_data_runs_the_install_script_and_logs_it(tmp_path: Path) -> None:
    text = (ROOT / "infra" / "deploy" / "cloud-init.yaml").read_text(encoding="utf-8")
    assert text.startswith("#cloud-config\n")  # cloud-init ignores user data without it
    data = yaml_load(text)
    assert set(data) == {"runcmd"}
    ((shell, flag, script),) = data["runcmd"]
    assert (shell, flag) == ("bash", "-c")
    url = re.search(
        r"https://raw\.githubusercontent\.com/kobars/realtime-vocab-quiz/main/(\S+)", script
    )
    assert url is not None
    assert url[1] == "scripts/deploy/install.sh"
    assert "tee -a /var/log/quiz-install.log" in script
    assert re.search(r"^DOMAIN=$", script, re.MULTILINE)  # empty: <ip>.sslip.io
    (tmp_path / "user-data.sh").write_text(f"#!/usr/bin/env bash\n{script}", encoding="utf-8")
    for check in (["bash", "-n"], ["shellcheck"]):
        result = subprocess.run(
            [*check, str(tmp_path / "user-data.sh")], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stdout + result.stderr
