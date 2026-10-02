# AI-ASSISTED: the public host's HTTPS edge (compose.prod.yaml): HSTS and per-client addresses.
"""Run against the stack of ``make prod-up`` at an ``https://`` ``STACK_URL``; skipped otherwise.
Caddy replaces any X-Forwarded-For a client sends (``test_stack.py`` checks a spoofed one changes
nothing), so the proxy's own network is the only place a test can name two client addresses."""

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from quiz.config import Settings

pytestmark = pytest.mark.system

REPO = Path(__file__).resolve().parents[3]

PROD_COMPOSE = ("compose", "-f", "compose.yaml", "-f", "compose.prod.yaml")
# Run in the Caddy container with two client addresses and a request bound: POST /api/sessions
# through nginx as the first address until a refusal (or the bound), then once as the second;
# print the first address's count of 201s, its last status and the second address's status.
SESSIONS = r"""
status() {
  wget -S -q -O /dev/null --header "X-Forwarded-For: $1" --header 'Content-Type: application/json' \
    --post-data '{"displayName":"edge"}' http://nginx:8080/api/sessions 2>&1 |
    sed -n 's/^ *HTTP\/[0-9.]* \([0-9]*\).*/\1/p' | tail -n 1
}
n=0
while s=$(status "$1"); [ "$s" = 201 ] && [ "$n" -lt "$3" ]; do n=$((n + 1)); done
echo "$n $s $(status "$2")"
"""


@pytest.fixture(autouse=True)
def behind_tls(stack_url: str) -> None:
    if not stack_url.startswith("https://"):
        pytest.skip("not the HTTPS edge of compose.prod.yaml: set STACK_URL=https://<DOMAIN>")


async def test_https_replies_tell_browsers_to_stay_on_https(http: httpx.AsyncClient) -> None:
    reply = await http.get("/api/readyz")
    assert reply.status_code == 200
    assert reply.headers["Strict-Transport-Security"] == "max-age=31536000"


def test_two_client_addresses_behind_the_proxy_get_two_session_buckets() -> None:
    """Each node allows one address a bucket of 2 x PER_IP_CONN_CAP sessions, and nginx spreads
    the requests over both nodes: once the first address is refused, the second is not."""
    bound = 8 * Settings().per_ip_conn_cap  # make test-system exports .env
    docker = shutil.which("docker") or pytest.fail("the check runs in the Caddy container")
    exec_ = [docker, *PROD_COMPOSE, "exec", "-T", "caddy", "sh", "-c", SESSIONS, "sh"]
    run = subprocess.run(  # noqa: S603 - docker with fixed arguments
        [*exec_, "198.51.100.1", "198.51.100.2", str(bound)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    accepted, first, second = run.stdout.split()
    assert (first, second) == ("429", "201"), f"after {accepted} sessions from the first address"
