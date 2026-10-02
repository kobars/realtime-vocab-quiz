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
    tmp_path: Path,
    call: str,
    *args: str,
    env: dict[str, str] | None = None,
    **stubs: str,
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
        (
            "<html>404</html>",
            "198.51.100.2",
            "198.51.100.2",
        ),  # an answer that is not an address
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
    assert _sourced(tmp_path, call).stdout.split() == [
        "quiz.example.com",
        "203.0.113.7.sslip.io",
    ]


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
    """Here the public resolver cannot be reached, so the system's resolver answers."""
    getent = 'for a in $RECORDS; do echo "$a STREAM $2"; done; [[ -n $RECORDS ]] || exit 2'
    result = _sourced(
        tmp_path,
        "check_dns quiz.example.com 203.0.113.7 0",
        env={"RECORDS": records},
        getent=getent,
        curl="exit 7",
    )
    assert result.returncode == (1 if error else 0)
    assert error is None or error in result.stderr


# Google Public DNS's JSON answer for a name that is a CNAME of a name with one A record.
DOH_ANSWER = (
    """printf '{"Status":0,"Answer":[{"name":"quiz.example.com.","type":5,"TTL":60,"""
    """"data":"edge.example.net."},{"name":"edge.example.net.","type":1,"TTL":60,"""
    """"data":"%s"}]}\\n' "$ADDRESS" """
)


@pytest.mark.parametrize(("address", "code"), [("203.0.113.7", 0), ("198.51.100.2", 1)])
def test_the_dns_check_asks_public_dns_not_etc_hosts(
    tmp_path: Path, address: str, code: int
) -> None:
    """/etc/hosts may map the VM's own host name, the domain here, to 127.0.1.1."""
    result = _sourced(
        tmp_path,
        "check_dns quiz.example.com 203.0.113.7 0",
        env={"ADDRESS": address},
        curl=DOH_ANSWER,
        getent='echo "127.0.1.1 STREAM $2"',
    )
    assert result.returncode == code
    assert not code or f"resolves to {address}, not to this VM" in result.stderr


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
    for domain, expected in (
        ("", "a.sslip.io"),
        ("quiz.example.com", "quiz.example.com"),
    ):
        _sourced(tmp_path, render, str(env), domain)
        assert _env(env) == {**first, "DOMAIN": expected}


@pytest.mark.parametrize(
    ("tag", "files"),
    [
        ("main", "compose.yaml:compose.prod.yaml:compose.images.yaml"),
        ("v1.2.0", "compose.yaml:compose.prod.yaml:compose.images.yaml"),
        ("", "compose.yaml:compose.prod.yaml"),  # --build: the images built on the VM
    ],
)
def test_the_env_names_the_image_tag_and_the_compose_files_that_run_it(
    tmp_path: Path, tag: str, files: str
) -> None:
    """An .env from before the published images has neither line: both are added."""
    env, old = tmp_path / ".env", tmp_path / "old.env"
    for src in (ROOT / ".env.prod.example", old):
        old.write_text("DOMAIN=a.sslip.io\nADMIN_TOKEN=x\n", encoding="utf-8")
        _sourced(tmp_path, f'render_env "$2" "{env}" "" "$3"', str(src), tag)
        values = _env(env)
        assert (values["IMAGE_TAG"], values["COMPOSE_FILE"]) == (tag, files)
        assert values.keys() == _env(src).keys() | {"IMAGE_TAG", "COMPOSE_FILE"}


@pytest.mark.parametrize(
    ("ref", "build", "tag"),
    [
        ("main", "0", "main"),
        ("v1.2.0", "0", "v1.2.0"),
        ("main", "1", ""),
        ("my-branch", "1", ""),
    ],
)
def test_main_and_release_tags_pull_their_published_images(
    tmp_path: Path, ref: str, build: str, tag: str
) -> None:
    result = _sourced(tmp_path, f"image_tag_for '{ref}' {build}")
    assert (result.returncode, result.stdout.strip()) == (0, tag)


@pytest.mark.parametrize("ref", ["my-branch", "v1.2", "1.2.0", "v1.2.0-rc1"])
def test_another_ref_has_no_published_images_and_needs_build(tmp_path: Path, ref: str) -> None:
    result = _sourced(tmp_path, f"image_tag_for '{ref}' 0")
    assert result.returncode == 1
    assert f"--ref {ref} has no published images" in result.stderr
    assert "add --build" in result.stderr


OLD_ENV = "DOMAIN=quiz.example.com\nADMIN_TOKEN=old\n"
# The checkout is at the commit in $STATE, on branch main unless $DETACHED is set; the merge of
# main's upstream brings "new" (or fails on $PULL_FAILS). make fails on $BAD_UP, readyz on
# $BAD_READY.
FAKE_GIT = """[[ $1 != -C ]] || shift 2
echo "git $*" >> "$LOG"
case "$1" in
  rev-parse) cat "$STATE" ;;
  symbolic-ref) [[ -z ${DETACHED:-} ]] || exit 1; [[ $* != *--short* ]] || echo main ;;
  describe) echo v1 ;;
  checkout) [[ ${*: -1} == main ]] || echo "${*: -1}" > "$STATE" ;;
  merge) [[ -z ${PULL_FAILS:-} ]] || exit 1; echo new > "$STATE" ;;
  reset) echo "$3" > "$STATE" ;;
esac"""
FAKE_MAKE = 'echo "make $* @ $(cat "$STATE")" >> "$LOG"; [[ $(cat "$STATE") != "${BAD_UP:-}" ]]'
FAKE_READY = '[[ $(cat "$STATE") != "${BAD_READY:-}" ]]'


# compose's Redis counts one more save after each BGSAVE; each cp writes a file. The Redis restore
# fails on $REDIS_FAILS. The running api-1 and web containers run the images old-api and old-web
# (none run on $STOPPED); up fails on $BAD_UP on the published images (built ones fail in make),
# and the pull on $PULL_DENIED, as an anonymous pull of a private package does.
FAKE_DOCKER = """echo "docker $*" >> "$LOG"
saves="$(cat "$LOG.saves" 2>/dev/null || echo 0)"
case "$*" in
  *" up -d "*)
    echo "up on ${IMAGE_TAG-the .env tag} @ $(cat "$STATE")" >> "$LOG"
    [[ $(cat "$STATE") != "${BAD_UP:-}" || $* != *compose.images.yaml* ]] ;;
  *" pull --quiet") [[ -z ${PULL_DENIED:-} ]] ;;
  *" ps -q api-1") [[ -n ${STOPPED:-} ]] || echo c-api ;;
  *" ps -q web") [[ -n ${STOPPED:-} ]] || echo c-web ;;
  "inspect --format {{.Image}} c-api") echo old-api ;;
  "inspect --format {{.Image}} c-web") echo old-web ;;
  *"redis-cli BGSAVE SCHEDULE") echo $((saves + 1)) > "$LOG.saves" ;;
  *" --entrypoint sh stack-redis "*) [[ -z ${REDIS_FAILS:-} ]] ;;
  *"redis-cli INFO persistence")
    printf '%s\\r\\n' rdb_bgsave_in_progress:0 "rdb_saves:$saves" rdb_last_bgsave_status:ok ;;
  *" cp stack-redis:/data/dump.rdb "*) echo REDIS > "${@: -1}" ;;
  *" cp caddy:/data "*) mkdir -p "${@: -1}/caddy" && echo KEY > "${@: -1}/caddy/key.pem" ;;
esac"""


def _ops(
    tmp_path: Path, *args: str, dot_env: str = OLD_ENV, **env: str
) -> tuple[int, list[str], str, Path]:
    """Run ops.sh from a copy; return its exit code, the stubs' calls, its output and the copy."""
    repo = tmp_path / "repo"
    if not repo.exists():  # the first call: a checkout with DOT_ENV
        repo.mkdir()
        (repo / ".env").write_text(dot_env, encoding="utf-8")
    (repo / ".git").mkdir(exist_ok=True)
    shutil.copytree(DEPLOY, repo / "scripts" / "deploy", dirs_exist_ok=True)
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


PULL = ["git checkout --quiet main", "git merge --quiet --ff-only @{upstream}"]
BACK = ["git checkout --quiet main", "git reset --keep old"]


@pytest.mark.parametrize(
    ("args", "env", "calls", "message"),
    [
        ([], {}, [*PULL, "make build IMAGE_TAG=dev @ new"], "Updated old -> new"),
        (
            [],
            {"BAD_UP": "new"},
            [*PULL, "make build IMAGE_TAG=dev @ new", *BACK, "make build IMAGE_TAG=dev @ old"],
            "rolled back to old, which is ready again",
        ),
        (
            [],
            {"BAD_READY": "new"},
            [*PULL, "make build IMAGE_TAG=dev @ new", *BACK, "make build IMAGE_TAG=dev @ old"],
            "rolled back to old, which is ready again",
        ),
        (
            [],
            {"BAD_UP": "new", "BAD_READY": "old"},
            [*PULL, "make build IMAGE_TAG=dev @ new", *BACK, "make build IMAGE_TAG=dev @ old"],
            "old is not ready either",
        ),
        (
            [],
            {"PULL_FAILS": "1"},
            [*PULL, *BACK],
            "could not move to main; the stack still runs old",
        ),
        # A tag install: the checkout is on no branch.
        ([], {"DETACHED": "1"}, [], "on v1, not on a branch; name the tag or branch"),
        (
            ["v2"],
            {"DETACHED": "1"},
            ["git checkout --quiet v2", "make build IMAGE_TAG=dev @ v2"],
            "old -> v2",
        ),
        (
            ["v2"],
            {"DETACHED": "1", "BAD_READY": "v2"},
            [
                "git checkout --quiet v2",
                "make build IMAGE_TAG=dev @ v2",
                "git checkout --quiet --detach old",
                "make build IMAGE_TAG=dev @ old",
            ],
            "rolled back to old, which is ready again",
        ),
    ],
)
def test_an_update_that_does_not_get_ready_rolls_back_to_the_commit_that_ran(
    tmp_path: Path, args: list[str], env: dict[str, str], calls: list[str], message: str
) -> None:
    """Without an image tag in .env, the images are built here from each commit."""
    code, log, out, _ = _ops(tmp_path, "update", *args, **env)
    assert code == (1 if {"BAD_UP", "BAD_READY", "PULL_FAILS"} & set(env) or not calls else 0), out
    assert [
        c for c in log if c.startswith(("make", "git checkout", "git merge", "git reset"))
    ] == calls
    assert message in out


PULL_ENV = OLD_ENV + "IMAGE_TAG=main\n"


@pytest.mark.parametrize(
    ("env", "ups", "message"),
    [
        ({}, ["up on the .env tag @ new"], "Updated old -> new"),
        (
            {"BAD_UP": "new"},
            ["up on the .env tag @ new", "up on main @ old"],
            "rolled back to old, which is ready again",
        ),
        (
            {"BAD_READY": "new"},
            ["up on the .env tag @ new", "up on main @ old"],
            "rolled back to old, which is ready again",
        ),
    ],
)
def test_an_update_on_published_images_rolls_back_to_the_images_that_ran(
    tmp_path: Path, env: dict[str, str], ups: list[str], message: str
) -> None:
    """A pull replaces the tag's local images, so the running ones are kept as :rollback first;
    a rollback makes them the tag's local images again, so every prod target runs them."""
    code, log, out, _ = _ops(tmp_path, "update", dot_env=PULL_ENV, **env)
    assert code == (0 if env == {} else 1), out
    assert message in out
    tags = [c for c in log if c.startswith("docker tag ")]
    assert tags[:2] == [
        "docker tag old-api ghcr.io/kobars/realtime-vocab-quiz-api:rollback",
        "docker tag old-web ghcr.io/kobars/realtime-vocab-quiz-web:rollback",
    ]
    assert tags[2:] == (
        []
        if env == {}
        else [
            f"docker tag ghcr.io/kobars/realtime-vocab-quiz-{name}:rollback "
            f"ghcr.io/kobars/realtime-vocab-quiz-{name}:main"
            for name in ("api", "web")
        ]
    )
    assert log.index(tags[1]) < next(i for i, c in enumerate(log) if c.startswith("git merge"))
    pulls = [c for c in log if c.endswith(" pull --quiet")]
    assert len(pulls) == 1  # the rollback runs the kept images without a pull
    assert all("-f compose.images.yaml" in c for c in [*pulls, *log] if " compose " in c)
    assert list(dict.fromkeys(c for c in log if c.startswith("up on "))) == ups
    assert not any(c.startswith("make") for c in log)


def test_an_update_to_a_release_tag_runs_its_images_and_keeps_the_tag_once_ready(
    tmp_path: Path,
) -> None:
    code, log, out, repo = _ops(tmp_path, "update", "v2.0.0", dot_env=PULL_ENV, DETACHED="1")
    assert code == 0, out
    assert next(c for c in log if c.startswith("up on ")) == "up on v2.0.0 @ v2.0.0"
    assert _env(repo / ".env")["IMAGE_TAG"] == "v2.0.0"
    assert _env(repo / ".env")["COMPOSE_FILE"].endswith(":compose.images.yaml")


def test_a_failed_update_to_a_release_tag_leaves_the_env_tag(tmp_path: Path) -> None:
    code, log, out, repo = _ops(
        tmp_path, "update", "v2.0.0", dot_env=PULL_ENV, DETACHED="1", BAD_READY="v2.0.0"
    )
    assert code == 1, out
    assert list(dict.fromkeys(c for c in log if c.startswith("up on "))) == [
        "up on v2.0.0 @ v2.0.0",
        "up on main @ old",
    ]
    assert (repo / ".env").read_text(encoding="utf-8") == PULL_ENV


def test_an_update_to_a_branch_needs_build_on_published_images(tmp_path: Path) -> None:
    code, log, out, _ = _ops(tmp_path, "update", "my-branch", dot_env=PULL_ENV)
    assert code == 1
    assert "--ref my-branch has no published images" in out
    assert not any(c.startswith(("git checkout", "docker", "make")) for c in log)
    code, log, out, _ = _ops(
        tmp_path, "update", "--build", "my-branch", dot_env=PULL_ENV, DETACHED="1"
    )
    assert code == 0, out
    assert [c for c in log if c.startswith("make")] == ["make build IMAGE_TAG=main @ my-branch"]


BUILT_AS_MAIN = [
    "docker tag elsaquiz-api:main ghcr.io/kobars/realtime-vocab-quiz-api:main",
    "docker tag elsaquiz-web:main ghcr.io/kobars/realtime-vocab-quiz-web:main",
]


def test_an_update_with_build_builds_here_under_the_image_tag(tmp_path: Path) -> None:
    """The build takes the published names, so every prod target runs it until a pull."""
    code, log, out, _ = _ops(tmp_path, "update", "--build", dot_env=PULL_ENV)
    assert code == 0, out
    assert [c for c in log if c.startswith("make")] == ["make build IMAGE_TAG=main @ new"]
    assert [c for c in log if c.startswith("docker tag elsaquiz-")] == BUILT_AS_MAIN
    assert not any(c.endswith(" pull --quiet") for c in log)
    assert all("-f compose.images.yaml" in c for c in log if " compose " in c)


@pytest.mark.parametrize("args", [["up"], ["update"]])
def test_images_that_cannot_be_pulled_are_built_here(tmp_path: Path, args: list[str]) -> None:
    """A new GHCR package is private, and a tag is published only after its push: the host
    still starts, on images built from its checkout."""
    code, log, out, _ = _ops(tmp_path, *args, dot_env=PULL_ENV, PULL_DENIED="1")
    assert code == 0, out
    assert "could not pull the published main images" in out
    assert "building them here instead" in out
    assert [c for c in log if c.startswith("make")] == [
        f"make build IMAGE_TAG=main @ {'new' if args == ['update'] else 'old'}"
    ]
    assert [c for c in log if c.startswith("docker tag elsaquiz-")] == BUILT_AS_MAIN
    assert any(c.startswith("up on ") for c in log)


def test_an_update_of_a_stopped_stack_starts_it_but_cannot_roll_back(tmp_path: Path) -> None:
    code, log, out, _ = _ops(tmp_path, "update", dot_env=PULL_ENV, STOPPED="1")
    assert code == 0, out
    assert "no images are kept to roll back to" in out
    assert not any(c.startswith("docker tag") for c in log)
    retry = tmp_path / "failed"
    retry.mkdir()
    code, log, out, _ = _ops(retry, "update", dot_env=PULL_ENV, STOPPED="1", BAD_READY="new")
    assert code == 1
    assert "there are no images to go back to" in out
    assert BACK == [c for c in log if c.startswith(("git checkout", "git reset"))][-2:]


def test_a_short_sha_tag_follows_the_checkout_and_a_short_sha_ref_is_published(
    tmp_path: Path,
) -> None:
    """A commit's tag never moves: an update runs the new commit's images and keeps its tag.
    (The stub git names the new commit "new", so its short SHA is "new" too.)"""
    code, log, out, repo = _ops(tmp_path, "update", dot_env=OLD_ENV + "IMAGE_TAG=0a1b2c3\n")
    assert code == 0, out
    assert next(c for c in log if c.startswith("up on ")) == "up on new @ new"
    assert _env(repo / ".env")["IMAGE_TAG"] == "new"
    code, log, out, repo = _ops(tmp_path, "update", "1a2b3c4", DETACHED="1")
    assert code == 0, out
    assert next(c for c in log if c.startswith("up on ")) == "up on 1a2b3c4 @ 1a2b3c4"
    assert _env(repo / ".env")["IMAGE_TAG"] == "1a2b3c4"


BOTH = "-f compose.yaml -f compose.prod.yaml"


@pytest.mark.parametrize(
    ("dot_env", "env", "files"),
    [
        (OLD_ENV, {}, BOTH),
        (PULL_ENV, {}, f"{BOTH} -f compose.images.yaml"),
        (OLD_ENV, {"IMAGE_TAG": "v1.2.0"}, f"{BOTH} -f compose.images.yaml"),
        (PULL_ENV, {"IMAGE_TAG": ""}, BOTH),  # set but empty: built here
    ],
)
def test_the_prod_targets_add_the_published_images_when_an_image_tag_is_set(
    tmp_path: Path, dot_env: str, env: dict[str, str], files: str
) -> None:
    code, log, out, _ = _ops(tmp_path, "compose", "ps", dot_env=dot_env, **env)
    assert code == 0, out
    assert log == [f"docker compose {files} ps"]


def _backup(tmp_path: Path) -> tuple[Path, Path]:
    """Back up to out/b.tar.gz, relative to the folder ops.sh runs in; return it and the copy."""
    code, _, out, repo = _ops(tmp_path, "backup", "out/b.tar.gz")
    assert code == 0, out
    return tmp_path / "out" / "b.tar.gz", repo


def test_a_backup_holds_the_redis_snapshot_the_certificates_and_env_and_restores(
    tmp_path: Path,
) -> None:
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "b.tar.gz").write_text("an older backup", encoding="utf-8")
    (tmp_path / "out" / "b.tar.gz").chmod(0o644)
    code, log, out, repo = _ops(tmp_path, "backup", "out/b.tar.gz")
    assert code == 0, out
    backup = tmp_path / "out" / "b.tar.gz"
    assert backup.stat().st_mode & 0o077 == 0  # it holds the secrets and the private keys
    with tarfile.open(backup) as tar:
        assert {m.name for m in tar.getmembers() if m.isfile()} == {
            ".env",
            "redis/dump.rdb",
            "caddy/caddy/key.pem",
        }
    assert any(c.endswith("redis-cli BGSAVE SCHEDULE") for c in log)

    fresh = "DOMAIN=quiz.example.com\nADMIN_TOKEN=fresh\n"
    (repo / ".env").write_text(fresh, encoding="utf-8")
    code, log, out, _ = _ops(tmp_path, "restore", "out/b.tar.gz")
    assert code == 0, out
    assert (repo / ".env").read_text(encoding="utf-8") == OLD_ENV
    assert (repo / ".env.before-restore").read_text(encoding="utf-8") == fresh
    runs = [c for c in log if " run --rm --no-deps --user 0 " in c]
    services = [re.findall(r"-v (\S+):/backup:ro --entrypoint sh (\S+) -c", run) for run in runs]
    assert [found[0][1] for found in services] == ["stack-redis", "caddy"]
    assert all(found[0][0].endswith(("/redis", "/caddy")) for found in services)
    assert "make build IMAGE_TAG=dev @ old" in log
    assert [c for c in log if c.startswith("docker compose")][-1].endswith(
        "--force-recreate nginx caddy"
    )


def test_a_restore_onto_a_new_host_keeps_its_own_sslip_io_name(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / ".env").write_text(
        "DOMAIN=203.0.113.7.sslip.io\nADMIN_TOKEN=old\n", encoding="utf-8"
    )
    backup, repo = _backup(tmp_path)
    (repo / ".env").write_text(
        "DOMAIN=198.51.100.2.sslip.io\nADMIN_TOKEN=fresh\n", encoding="utf-8"
    )
    code, _, out, _ = _ops(tmp_path, "restore", str(backup))
    assert code == 0, out
    assert _env(repo / ".env") == {
        "DOMAIN": "198.51.100.2.sslip.io",
        "ADMIN_TOKEN": "old",
    }
    assert (repo / ".env").stat().st_mode & 0o077 == 0


def test_a_restore_of_a_backup_without_an_image_tag_keeps_the_hosts_own(tmp_path: Path) -> None:
    """A backup from before the published images would otherwise switch the host to building."""
    backup, repo = _backup(tmp_path)
    (repo / ".env").write_text(PULL_ENV.replace("old", "fresh"), encoding="utf-8")
    code, log, out, _ = _ops(tmp_path, "restore", str(backup))
    assert code == 0, out
    assert "Keeping IMAGE_TAG=main" in out
    assert _env(repo / ".env")["ADMIN_TOKEN"] == "old"
    assert _env(repo / ".env")["IMAGE_TAG"] == "main"
    assert _env(repo / ".env")["COMPOSE_FILE"].endswith(":compose.images.yaml")
    assert not any(c.startswith("make") for c in log)


def test_a_snapshot_that_does_not_load_puts_the_previous_env_back_and_restarts(
    tmp_path: Path,
) -> None:
    backup, repo = _backup(tmp_path)
    fresh = "DOMAIN=quiz.example.com\nADMIN_TOKEN=fresh\n"
    (repo / ".env").write_text(fresh, encoding="utf-8")
    code, log, out, _ = _ops(tmp_path, "restore", str(backup), REDIS_FAILS="1")
    assert code == 1
    assert "did not load; the previous .env and data are back" in out
    assert (repo / ".env").read_text(encoding="utf-8") == fresh
    assert not any(" --entrypoint sh caddy " in c for c in log)
    assert "make build IMAGE_TAG=dev @ old" in log
    assert [c for c in log if c.startswith("docker compose")][-1].endswith(
        "--force-recreate nginx caddy"
    )


def test_a_restore_into_a_checkout_without_env_stops_nothing(tmp_path: Path) -> None:
    backup, repo = _backup(tmp_path)
    (repo / ".env").unlink()
    code, log, out, _ = _ops(tmp_path, "restore", str(backup))
    assert code == 0, out
    assert (repo / ".env").read_text(encoding="utf-8") == OLD_ENV
    assert not any(c.endswith(" down") for c in log)


def _docker_runs() -> bool:
    return DOCKER is not None and (
        subprocess.run([DOCKER, "info"], capture_output=True, check=False, timeout=30).returncode
        == 0
    )


@pytest.mark.skipif(DOCKER is None, reason="needs Docker")
@pytest.mark.slow
def test_the_install_writes_env_once_in_a_fresh_ubuntu() -> None:
    """Offline, as root, without Docker in the container: --dry-run prints the package, clone and
    stack commands and writes .env; a run with a domain that does not resolve stops before them."""
    if not _docker_runs():
        pytest.skip("the Docker daemon is not running")
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


def test_the_cloud_init_user_data_runs_the_install_script_and_logs_it(
    tmp_path: Path,
) -> None:
    text = (ROOT / "infra" / "deploy" / "cloud-init.yaml").read_text(encoding="utf-8")
    assert text.startswith("#cloud-config\n")  # cloud-init ignores user data without it
    data = yaml_load(text)
    assert set(data) == {"runcmd"}
    ((shell, flag, script),) = data["runcmd"]
    assert (shell, flag) == ("bash", "-c")
    url = re.search(
        r"https://raw\.githubusercontent\.com/kobars/realtime-vocab-quiz/main/(\S+)",
        script,
    )
    assert url is not None
    assert url[1] == "scripts/deploy/install.sh"
    assert "tee -a /var/log/quiz-install.log" in script
    assert re.search(r"^DOMAIN=$", script, re.MULTILINE)  # empty: <ip>.sslip.io
    (tmp_path / "user-data.sh").write_text(f"#!/usr/bin/env bash\n{script}", encoding="utf-8")
    for check in (["bash", "-n"], ["shellcheck"]):
        result = subprocess.run(
            [*check, str(tmp_path / "user-data.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
