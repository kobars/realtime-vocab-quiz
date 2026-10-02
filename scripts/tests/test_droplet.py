# AI-ASSISTED: the laptop's DigitalOcean deploy and destroy, run against a stub doctl.
"""``scripts/deploy/droplet.sh`` runs with stubs first on ``PATH`` for doctl, curl and ssh, so no
cloud resource is created. The doctl stub records each call's arguments and answers the lookups
from environment variables."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy" / "droplet.sh"
TAG = "realtime-vocab-quiz"
ANYWHERE = "address:0.0.0.0/0,address:::/0"
BASH = shutil.which("bash") or "/bin/bash"
MAKE = shutil.which("make") or "make"

# Each call is one shell-quoted line; the Droplet's user data is copied next to the log.
FAKE_DOCTL = """printf '%q ' "$@" >> "$LOG"; echo >> "$LOG"
case "$*" in
  "account get") [[ -z ${SIGNED_OUT:-} ]] ;;
  "compute droplet list --tag-name realtime-vocab-quiz --format Name --no-header")
    printf '%s' "${DROPLETS:-}" | awk '{ print $2 }' ;;
  "compute droplet list --tag-name realtime-vocab-quiz --format ID,Name,PublicIPv4 --no-header")
    printf '%s' "${DROPLETS:-}" ;;
  "compute ssh-key list --format ID --no-header") printf '%s' "${KEYS-$'111\\n222\\n'}" ;;
  "compute firewall list --format ID,Name --no-header") printf '%s' "${FIREWALLS:-}" ;;
  "compute domain list --format Domain --no-header") printf '%s' "${ZONES:-}" ;;
  "compute domain records list "*) printf '%s' "${RECORDS:-}" ;;
  "compute droplet create "*)
    while (($#)); do [[ $1 != --user-data-file ]] || cp "$2" "$LOG.user-data"; shift; done
    echo 203.0.113.7 ;;
esac"""


def _run(
    tmp_path: Path, *args: str, stdin: str = "", **env: str
) -> tuple[int, list[list[str]], str]:
    """Run droplet.sh; return its exit code, the doctl calls' arguments and its output."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stubs = {
        "doctl": FAKE_DOCTL,
        "curl": "true",  # readyz answers
        "ssh": 'echo "ssh $*"; echo "Player URL: https://quiz.example.com/play/VOCAB-42"',
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "doctl.log"
    log.write_text("", encoding="utf-8")
    result = subprocess.run(
        [BASH, str(SCRIPT), *args],
        input=stdin,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "LOG": str(log),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    calls = [shlex.split(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return result.returncode, calls, result.stdout + result.stderr


LOOKUPS = [
    ["account", "get"],
    ["compute", "droplet", "list", "--tag-name", TAG, "--format", "Name", "--no-header"],
    ["compute", "ssh-key", "list", "--format", "ID", "--no-header"],
    ["compute", "firewall", "list", "--format", "ID,Name", "--no-header"],
]
FIREWALL = [
    "compute", "firewall", "create", "--name", TAG, "--tag-names", TAG,
    "--inbound-rules",
    " ".join(f"protocol:tcp,ports:{port},{ANYWHERE}" for port in (22, 80, 443)),
    "--outbound-rules",
    f"protocol:tcp,ports:all,{ANYWHERE} protocol:udp,ports:all,{ANYWHERE} protocol:icmp,{ANYWHERE}",
]  # fmt: skip


def _droplet(name: str, region: str, size: str, user_data: str) -> list[str]:
    return [
        "compute", "droplet", "create", name, "--image", "ubuntu-24-04-x64", "--region", region,
        "--size", size, "--ssh-keys", "111,222", "--tag-names", TAG, "--user-data-file", user_data,
        "--wait", "--format", "PublicIPv4", "--no-header",
    ]  # fmt: skip


def test_deploy_creates_the_firewall_the_droplet_and_the_a_record(tmp_path: Path) -> None:
    code, calls, out = _run(
        tmp_path, "deploy", "--domain", "quiz.example.com", ZONES="example.org\nexample.com\n"
    )
    assert code == 0, out
    user_data = calls[5][calls[5].index("--user-data-file") + 1]
    assert calls == [
        *LOOKUPS,
        FIREWALL,
        _droplet("quiz.example.com", "sgp1", "s-2vcpu-4gb", user_data),
        ["compute", "domain", "list", "--format", "Domain", "--no-header"],
        [
            "compute", "domain", "records", "create", "example.com", "--record-type", "A",
            "--record-name", "quiz", "--record-data", "203.0.113.7", "--record-ttl", "300",
        ],
    ]  # fmt: skip
    # The repository's user data, with the domain filled in.
    template = (ROOT / "infra" / "deploy" / "cloud-init.yaml").read_text(encoding="utf-8")
    sent = (tmp_path / "doctl.log.user-data").read_text(encoding="utf-8")
    assert sent == template.replace("      DOMAIN=\n", "      DOMAIN=quiz.example.com\n")
    assert sent != template
    assert not Path(user_data).exists()  # removed on exit
    assert "ssh -o StrictHostKeyChecking=accept-new root@203.0.113.7 make -C " in out
    assert "Player URL: https://quiz.example.com/play/VOCAB-42" in out
    assert "The quiz app is live at https://quiz.example.com/" in out


def test_deploy_without_a_domain_serves_on_the_ips_sslip_io_name(tmp_path: Path) -> None:
    code, calls, out = _run(tmp_path, "deploy", "--region", "nyc3", "--size", "s-1vcpu-1gb")
    assert code == 0, out
    assert calls[5][:12] == _droplet(TAG, "nyc3", "s-1vcpu-1gb", "")[:12]
    assert len(calls) == 6  # no domain lookup and no record
    template = (ROOT / "infra" / "deploy" / "cloud-init.yaml").read_text(encoding="utf-8")
    assert (tmp_path / "doctl.log.user-data").read_text(encoding="utf-8") == template
    assert "The quiz app is live at https://203.0.113.7.sslip.io/" in out


def test_a_domain_elsewhere_gets_no_record_and_an_existing_firewall_is_kept(
    tmp_path: Path,
) -> None:
    code, calls, out = _run(
        tmp_path,
        "deploy",
        "--domain",
        "quiz.example.com",
        ZONES="example.org\n",
        FIREWALLS=f"fw-1 {TAG}\n",
    )
    assert code == 0, out
    assert [c[:3] for c in calls[4:]] == [
        ["compute", "droplet", "create"],
        ["compute", "domain", "list"],
    ]
    assert "point its A record at 203.0.113.7 now" in out


def test_the_apex_of_a_zone_is_the_at_record(tmp_path: Path) -> None:
    code, calls, out = _run(tmp_path, "deploy", "--domain", "example.com", ZONES="example.com\n")
    assert code == 0, out
    assert calls[-1][calls[-1].index("--record-name") + 1] == "@"


def test_dry_run_prints_every_command_that_creates_and_runs_only_lookups(tmp_path: Path) -> None:
    code, calls, out = _run(
        tmp_path, "deploy", "--domain", "quiz.example.com", "--dry-run", ZONES="example.com\n"
    )
    assert code == 0, out
    assert calls == [*LOOKUPS, ["compute", "domain", "list", "--format", "Domain", "--no-header"]]
    skipped = [line for line in out.splitlines() if line.startswith("dry run, skipped: ")]
    assert [shlex.split(line.removeprefix("dry run, skipped: "))[:4] for line in skipped] == [
        ["doctl", "compute", "firewall", "create"],
        ["doctl", "compute", "droplet", "create"],
        ["doctl", "compute", "domain", "records"],
        ["the", "wait"],
        ["ssh", "-o", "StrictHostKeyChecking=accept-new", "root@<droplet-ip>"],
    ]
    assert "--record-data <droplet-ip>" in skipped[2]


@pytest.mark.parametrize(
    ("env", "error"),
    [
        ({"SIGNED_OUT": "1"}, "doctl is not signed in; run doctl auth init"),
        ({"KEYS": ""}, "the DigitalOcean account has no SSH key"),
        ({"DROPLETS": "9 quiz.example.com 198.51.100.4\n"}, f"a Droplet tagged {TAG} exists"),
    ],
)
def test_deploy_stops_before_creating_anything(
    tmp_path: Path, env: dict[str, str], error: str
) -> None:
    code, calls, out = _run(tmp_path, "deploy", "--domain", "quiz.example.com", **env)
    assert code == 1
    assert error in out
    assert not any("create" in call for call in calls)


def test_deploy_refuses_a_domain_that_is_not_a_host_name(tmp_path: Path) -> None:
    code, calls, out = _run(tmp_path, "deploy", "--domain", "quiz example;com")
    assert (code, calls) == (1, [])
    assert "is not a host name" in out


DESTROY_ENV = {
    "DROPLETS": "123 quiz.example.com 203.0.113.7\n",
    "ZONES": "example.com\n",
    # Only the A record of the Droplet's name that points at it is the one deploy created.
    "RECORDS": "9 A quiz 203.0.113.7\n10 A quiz 198.51.100.1\n11 A www 203.0.113.7\n"
    "12 TXT quiz 203.0.113.7\n",
    "FIREWALLS": f"fw-1 {TAG}\nfw-2 other\n",
}
DELETES = [
    ["compute", "domain", "records", "delete", "example.com", "9", "--force"],
    ["compute", "droplet", "delete", "123", "--force"],
    ["compute", "firewall", "delete", "fw-1", "--force"],
]


def test_destroy_deletes_the_tagged_droplet_its_record_and_the_firewall_after_yes(
    tmp_path: Path,
) -> None:
    code, calls, out = _run(tmp_path, "destroy", stdin="yes\n", **DESTROY_ENV)
    assert code == 0, out
    assert [c for c in calls if "delete" in c] == DELETES
    assert calls[1] == [
        "compute", "droplet", "list", "--tag-name", TAG, "--format", "ID,Name,PublicIPv4",
        "--no-header",
    ]  # fmt: skip
    for line in (
        "DNS A record quiz.example.com -> 203.0.113.7",
        "Droplet quiz.example.com (203.0.113.7)",
        f"firewall {TAG}",
    ):
        assert f"  {line}\n" in out


@pytest.mark.parametrize("answer", ["", "no\n", "y\n"])
def test_destroy_deletes_nothing_without_yes(tmp_path: Path, answer: str) -> None:
    code, calls, out = _run(tmp_path, "destroy", stdin=answer, **DESTROY_ENV)
    assert code == 1
    assert "nothing deleted" in out
    assert not any("delete" in call for call in calls)


def test_destroy_dry_run_prints_the_deletes_without_asking(tmp_path: Path) -> None:
    code, calls, out = _run(tmp_path, "destroy", "--dry-run", **DESTROY_ENV)
    assert code == 0, out
    assert not any("delete" in call for call in calls)
    assert [
        shlex.split(line.removeprefix("dry run, skipped: doctl "))
        for line in out.splitlines()
        if line.startswith("dry run, skipped: ")
    ] == DELETES


def test_destroy_with_nothing_tagged_deletes_nothing(tmp_path: Path) -> None:
    code, calls, out = _run(tmp_path, "destroy")
    assert code == 0, out
    assert "Nothing to delete" in out
    assert not any("delete" in call for call in calls)


def test_the_make_targets_pass_their_variables_to_the_script() -> None:
    def dry(*args: str) -> str:
        # Run from make check, the inner make would inherit its flags and name its folder.
        env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MAKELEVEL", "MFLAGS"}}
        result = subprocess.run(
            [MAKE, "-n", "--no-print-directory", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return " ".join(result.stdout.split())  # an empty option leaves its spaces

    assert dry("do-deploy", "DOMAIN=quiz.example.com", "REGION=nyc3", "SIZE=s-1vcpu-1gb") == (
        "scripts/deploy/droplet.sh deploy --domain 'quiz.example.com' --region 'nyc3' "
        "--size 's-1vcpu-1gb'"
    )
    assert dry("do-deploy", "DRY_RUN=1") == "scripts/deploy/droplet.sh deploy --dry-run"
    assert dry("do-destroy") == "scripts/deploy/droplet.sh destroy"
