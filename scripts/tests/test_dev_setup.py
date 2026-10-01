# AI-ASSISTED: make dev-api serves where the Vite dev proxy points and allows its origin.
"""``pnpm -C web dev`` proxies ``/api`` and ``/ws`` to one API node and the browser sends the
Vite server's origin with the WebSocket upgrade; the gateway refuses an origin that is not
allowed with 403. ``make dev-api`` must start that node, with that origin allowed.

The recipe is read with ``make -n``, so the test binds no port."""

import re
import shlex
import subprocess
from pathlib import Path

import pytest

from quiz.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def _vite_defaults() -> tuple[int, str]:
    """Return the Vite dev server's port and the proxy's default API target."""
    config = (ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")
    port = re.search(r"\bport: (\d+)", config)
    target = re.search(r"QUIZ_API_URL\?\.trim\(\) \|\| '([^']+)'", config)
    assert port
    assert target
    return int(port[1]), target[1]


def _dev_api_command() -> list[str]:
    recipe = subprocess.run(
        ["make", "--no-print-directory", "-n", "-s", "dev-api"],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return shlex.split(recipe)


def test_dev_api_listens_on_the_proxy_target_and_allows_the_vite_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vite_port, target = _vite_defaults()
    command = _dev_api_command()
    assert command[command.index("--port") + 1] == target.rsplit(":", 1)[1]
    assert target.startswith(f"http://{command[command.index('--host') + 1]}:")
    (origins,) = (word.split("=", 1)[1] for word in command if word.startswith("ALLOWED_ORIGINS="))
    monkeypatch.setenv("ALLOWED_ORIGINS", origins)
    allowed = Settings().allowed_origins
    assert f"http://localhost:{vite_port}" in allowed
    assert f"http://127.0.0.1:{vite_port}" in allowed
