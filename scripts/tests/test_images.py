# AI-ASSISTED: static guards on the Dockerfiles, the build context and the make build recipe.
"""The image rules that a build alone does not enforce: the locked install, the non-root user,
the healthchecks, the uvicorn transport flags, the SPA fallback and a build context without
local state.

The files are read as text, so the tests need no Docker daemon.
"""

import json
from pathlib import Path

import pytest
import uvicorn
from starlette.applications import Starlette

import quiz.__main__ as quiz_main
from quiz.adapters.ws.heartbeat import server_config
from quiz.config import Settings
from quiz.main import module_app

ROOT = Path(__file__).resolve().parents[2]


def _stages(dockerfile: Path) -> list[list[str]]:
    """Return the stripped instruction lines of each ``FROM`` stage, comments dropped and
    backslash continuations joined into one line."""
    stages: list[list[str]] = []
    text = dockerfile.read_text(encoding="utf-8").replace("\\\n", " ")
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if line.startswith("FROM "):
            stages.append([])
        if stages and line and not line.startswith("#"):
            stages[-1].append(line)
    return stages


def _api_cmd() -> list[str]:
    _, runtime = _stages(ROOT / "api" / "Dockerfile")
    cmd: list[str] = json.loads(next(line for line in runtime if line.startswith("CMD "))[3:])
    return cmd


def test_api_image_installs_locked_runtime_dependencies_only() -> None:
    builder, _ = _stages(ROOT / "api" / "Dockerfile")
    syncs = [line for line in builder if "uv sync" in line]
    assert syncs
    assert all("--frozen" in line and "--no-dev" in line for line in syncs)


def test_api_runtime_holds_only_the_venv_and_the_source_and_runs_as_10001() -> None:
    _, runtime = _stages(ROOT / "api" / "Dockerfile")
    copies = [line for line in runtime if line.startswith("COPY")]
    assert copies == [
        "COPY --from=builder /app/.venv /app/.venv",
        "COPY --from=builder /app/src /app/src",
    ]
    assert "USER 10001:10001" in runtime
    assert any("/healthz" in line for line in runtime if "CMD" in line)
    assert any(line.startswith("HEALTHCHECK") for line in runtime)


def _server_config() -> uvicorn.Config:
    """The config that ``python -m quiz``, the image's command, runs uvicorn with."""
    assert _api_cmd() == ["python", "-m", "quiz"]
    return server_config(Starlette(), Settings(), "0.0.0.0", 8000)  # noqa: S104


def test_api_image_caps_websocket_frames_just_above_the_gateway_limit() -> None:
    """uvicorn buffers a whole frame before the gateway sees it; its default cap is 16 MiB."""
    cap = _server_config().ws_max_size
    limit = Settings.model_fields["max_payload_bytes"].default
    # Above the limit, so the gateway's MESSAGE_TOO_LARGE and close 1009 still answer such frames.
    assert limit < cap <= 4 * limit


def test_web_image_serves_dist_from_unprivileged_nginx_with_an_spa_fallback() -> None:
    builder, runtime = _stages(ROOT / "web" / "Dockerfile")
    assert any("pnpm install --frozen-lockfile" in line for line in builder)
    assert "RUN pnpm build" in builder
    assert runtime[0].startswith("FROM nginxinc/nginx-unprivileged:")
    # No $uri/ fallback: it answers a directory path with a 301 to the internal port.
    assert "try_files $uri /index.html;" in runtime
    assert not any("$uri/" in line for line in runtime)
    assert "COPY --from=builder /web/dist /usr/share/nginx/html" in runtime
    assert any(line.startswith("HEALTHCHECK") for line in runtime)


def test_build_context_leaves_out_local_state() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in ("**/.git", ".worktrees", "**/.venv", "**/node_modules", "**/.env"):
        assert entry in ignored


def test_make_build_builds_both_images_from_the_repository_root() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\nbuild:", 1)[1].split("\nup:", 1)[0]
    assert "not yet" not in recipe
    assert "docker build -f api/Dockerfile" in recipe
    assert "docker build -f web/Dockerfile" in recipe


def test_api_image_leaves_x_forwarded_for_to_the_gateway_and_turns_deflate_off() -> None:
    """uvicorn's own proxy headers trust loopback peers before the gateway's trusted proxies."""
    config = _server_config()
    assert config.log_config is None  # keeps the app's JSON log handlers
    assert config.proxy_headers is False
    assert config.ws_per_message_deflate is False


def test_api_image_pings_every_heartbeat_and_drops_a_socket_without_a_pong_by_the_next() -> None:
    config, heartbeat_s = _server_config(), Settings().heartbeat_ms / 1000
    assert config.ws_ping_interval == config.ws_ping_timeout == heartbeat_s == 25


def test_python_m_quiz_serves_the_module_app_with_the_server_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[uvicorn.Config] = []

    class Server:
        def __init__(self, config: uvicorn.Config) -> None:
            self.config = config

        def run(self) -> None:
            started.append(self.config)

    monkeypatch.setattr(uvicorn, "Server", Server)
    quiz_main.main()
    (config,) = started
    assert config.app is module_app()
    assert (config.host, config.port, config.ws_ping_interval) == ("0.0.0.0", 8000, 25)  # noqa: S104
