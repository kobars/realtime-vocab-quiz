# AI-ASSISTED: static guards on the Dockerfiles, the image pins, the build context and make build.
"""The image rules that a build alone does not enforce: images pinned by digest, the locked
install, the non-root user, the healthchecks, the uvicorn transport flags, the SPA fallback and
a build context without local state.

The files are read as text, so the tests need no Docker daemon.
"""

import json
import re
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


# The ``docker run`` options that take a value as the next argument.
_RUN_OPTIONS_WITH_VALUE = {"-e", "--env", "-p", "--publish", "-v", "--volume", "-w", "--workdir"}
_RUN_OPTIONS_WITH_VALUE |= {"--name", "--tmpfs", "-u", "--user", "--network", "--entrypoint"}


def _docker_run_images(text: str) -> list[str]:
    """Return the image of each ``docker run`` in a shell script or a workflow: its first argument
    that is neither an option nor an option's value. An image held in a shell variable, such as
    the ``"$image"`` that ``make build`` makes, is left out."""
    lines = text.replace("\\\n", " ").splitlines()
    commands = [line for line in lines if not line.lstrip().startswith("#")]
    images: list[str] = []
    for match in (m for line in commands for m in re.finditer(r"docker run\s(.*)", line)):
        args = iter(match.group(1).split())
        for arg in args:
            if arg in _RUN_OPTIONS_WITH_VALUE:
                next(args, None)
            elif not arg.startswith("-"):
                if not arg.strip('"').startswith("$"):
                    images.append(arg)
                break
    return images


def _pulled_images(path: Path) -> list[str]:
    """Return each image that a file pulls. A Dockerfile pulls every ``FROM`` image and every
    ``COPY --from`` image that is not a build stage; any other file pulls every ``image:`` value
    except the images that ``make build`` makes here (``elsaquiz-*``), and every ``docker run``
    image."""
    if path.name != "Dockerfile":
        text = path.read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines()]
        values = [
            line.removeprefix("image:").strip() for line in lines if line.startswith("image:")
        ]
        return [value for value in values if not value.startswith("elsaquiz-")] + (
            _docker_run_images(text)
        )
    images: list[str] = []
    stage_names: set[str] = set()
    for stage in _stages(path):
        image, *alias = stage[0].split()[1:]
        images.append(image)
        for line in stage[1:]:
            source = line.split()[1].removeprefix("--from=")
            if line.startswith("COPY --from=") and source not in stage_names:
                images.append(source)
        stage_names.update(alias[-1:])
    return images


def _api_cmd() -> list[str]:
    _, runtime = _stages(ROOT / "api" / "Dockerfile")
    cmd: list[str] = json.loads(next(line for line in runtime if line.startswith("CMD "))[3:])
    return cmd


DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def _image_files() -> list[Path]:
    """Every file that can pull an image: the Dockerfiles, the compose files, the workflows and
    the shell scripts."""
    globs = ("*/Dockerfile", "compose*.yaml", ".github/workflows/*.yml", "scripts/*.sh")
    return sorted(path for pattern in globs for path in ROOT.glob(pattern))


def test_every_pulled_image_is_pinned_by_digest() -> None:
    """A tag can move; a digest is the exact image that the scans and the tests ran."""
    images = {str(path.relative_to(ROOT)): _pulled_images(path) for path in _image_files()}
    unpinned = {path: [i for i in found if not DIGEST.search(i)] for path, found in images.items()}
    assert {path: found for path, found in unpinned.items() if found} == {}
    # Each kind of file still yields its images, so a parser that finds nothing cannot pass.
    for path in ("api/Dockerfile", "compose.yaml", ".github/workflows/containers.yml"):
        assert images[path], path
    assert images["scripts/check_links.sh"], "scripts/check_links.sh"


def test_pulled_images_read_docker_run_and_skip_comments_and_variables(tmp_path: Path) -> None:
    script = tmp_path / "check.sh"
    script.write_text(
        "# usage: check <image> [docker run options...]\n"
        'docker run --rm -i -e TOKEN -v "$PWD:/in:ro" -w /in owner/tool:1.2 \\\n'
        "  --flag value\n"
        'uid="$(docker run --rm "$image" id -u)"\n'
        "xargs docker run --tmpfs /tmp alpine:3.22 true\n",
        encoding="utf-8",
    )
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(
        "services:\n  redis:\n    image: redis:8-alpine\n"
        "steps:\n  - run: git ls-files | xargs docker run --rm hadolint/hadolint:v2 hadolint\n",
        encoding="utf-8",
    )
    assert _pulled_images(script) == ["owner/tool:1.2", "alpine:3.22"]
    assert _pulled_images(workflow) == ["redis:8-alpine", "hadolint/hadolint:v2"]


def test_pulled_images_skip_build_stages_and_keep_an_image_without_a_digest(
    tmp_path: Path,
) -> None:
    pinned = f"python:3.14-slim@sha256:{'0' * 64}"
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        f"FROM {pinned} AS builder\nCOPY --from=uv:0.10 /uv /uv\n"
        "FROM nginx:1.29-alpine\nCOPY --from=builder /dist /html\n",
        encoding="utf-8",
    )
    images = _pulled_images(dockerfile)
    assert images == [pinned, "uv:0.10", "nginx:1.29-alpine"]
    assert [image for image in images if not DIGEST.search(image)] == images[1:]


def test_the_tests_and_ci_run_the_redis_image_that_compose_runs() -> None:
    """Dependabot updates compose.yaml only; the CI service and the test fixture follow it."""
    # Not a host name such as stack-redis:6379.
    redis = re.compile(r"(?<![\w.-])redis:[\w.-]+(?:@sha256:[0-9a-f]{64})?")
    paths = ["compose.yaml", ".github/workflows/ci.yml", "api/tests/conftest.py"]
    found = [set(redis.findall((ROOT / path).read_text(encoding="utf-8"))) for path in paths]
    assert len(found[0]) == 1
    assert all(images == found[0] for images in found), dict(zip(paths, found, strict=True))


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


def test_api_image_defaults_to_the_redis_store() -> None:
    """A replica started without STORE would otherwise keep quizzes and tickets of its own."""
    _, runtime = _stages(ROOT / "api" / "Dockerfile")
    envs = [line for line in runtime if line.startswith("ENV ")]
    assert any(re.search(r"(^ENV | )STORE=redis( |$)", line) for line in envs), envs


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
    assert "COPY web/nginx.conf /etc/nginx/conf.d/default.conf" in runtime
    conf = (ROOT / "web" / "nginx.conf").read_text(encoding="utf-8").splitlines()
    try_files = [line.strip() for line in conf if line.strip().startswith("try_files")]
    # No $uri/ fallback: it answers a directory path with a 301 to the internal port.
    assert "try_files $uri /index.html;" in try_files
    assert not any("$uri/" in line for line in try_files)
    assert "COPY --from=builder /web/dist /usr/share/nginx/html" in runtime
    assert any(line.startswith("HEALTHCHECK") for line in runtime)


def _location_blocks(conf: str) -> list[str]:
    """Return the body of each ``location`` block of an nginx config, comments dropped and
    nested blocks kept inside their location."""
    text = re.sub(r"#.*", "", conf)
    blocks = []
    for match in re.finditer(r"^\s*location\b[^{;]*\{", text, re.MULTILINE):
        depth, end = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(text[end], 0)
            end += 1
        blocks.append(text[match.end() : end - 1])
    return blocks


def _snippet_headers(snippet: str) -> dict[str, str]:
    """Map each header name of the snippet to its line; every other non-comment line fails."""
    lines = [
        line for line in snippet.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    # The unindented quoted form is the one smoke_images.sh parses; always: a missing asset's
    # 404 has them too.
    for line in lines:
        assert re.fullmatch(r'add_header \S+ "[^"]+" always;', line), line
    names = [line.split()[1] for line in lines]
    assert len(names) == len(set(names)), names
    return dict(zip(names, lines, strict=True))


def test_location_blocks_skip_comments_and_keep_nested_blocks() -> None:
    conf = """# each location sets Cache-Control
    location /a/ {
        if ($x) { return 404; }
        include /etc/nginx/security-headers.conf;
    }
    location / { add_header Cache-Control "no-cache"; }
"""
    first, second = _location_blocks(conf)
    assert "include /etc/nginx/security-headers.conf;" in first
    assert "add_header Cache-Control" in second


@pytest.mark.parametrize(
    "snippet",
    [
        '    add_header Strict-Transport-Security "x" always;',
        (
            'add_header Referrer-Policy "no-referrer" always;\n'
            'add_header Referrer-Policy "same-origin" always;'
        ),
    ],
)
def test_snippet_headers_reject_an_indented_or_repeated_header(snippet: str) -> None:
    with pytest.raises(AssertionError):
        _snippet_headers(snippet)


def test_web_image_sends_the_security_headers_from_every_location_that_adds_headers() -> None:
    """nginx drops the inherited add_header lines in a location that sets its own."""
    _, runtime = _stages(ROOT / "web" / "Dockerfile")
    assert "COPY web/security-headers.conf /etc/nginx/security-headers.conf" in runtime
    conf = (ROOT / "web" / "nginx.conf").read_text(encoding="utf-8")
    with_headers = [block for block in _location_blocks(conf) if "add_header" in block]
    assert with_headers
    for block in with_headers:
        assert "include /etc/nginx/security-headers.conf;" in block, block
    headers = _snippet_headers((ROOT / "web" / "security-headers.conf").read_text(encoding="utf-8"))
    assert set(headers) == {
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    }
    csp = headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    # form-action has no default-src fallback.
    assert "form-action 'self'" in csp
    assert "unsafe-inline" not in csp


def test_runtime_stages_take_the_os_security_fixes_and_end_as_a_non_root_user() -> None:
    """The base tags lag behind the distribution's security fixes, which the image scan fails on."""
    _, api = _stages(ROOT / "api" / "Dockerfile")
    _, web = _stages(ROOT / "web" / "Dockerfile")
    assert any("apt-get upgrade -y" in line for line in api if line.startswith("RUN"))
    assert any("apk upgrade --no-cache" in line for line in web if line.startswith("RUN"))
    # pip is never used at run time, and its vendored libraries carry their own advisories.
    assert any("pip uninstall --yes pip" in line for line in api if line.startswith("RUN"))
    users = [[line for line in stage if line.startswith("USER ")] for stage in (api, web)]
    assert [stage_users[-1] for stage_users in users] == [
        "USER 10001:10001",
        "USER 101:101",
    ]


def test_build_context_leaves_out_local_state() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in ("**/.git", ".worktrees", "**/.venv", "**/node_modules", "**/.env"):
        assert entry in ignored


def test_make_build_builds_both_images_from_the_repository_root() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\nbuild:", 1)[1].split("\nup:", 1)[0]
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


def test_api_image_bounds_its_shutdown_and_names_its_protocol_classes() -> None:
    """A protocol given by name ("auto") may pick a class without the head and fragment limits."""
    config = _server_config()
    grace = config.timeout_graceful_shutdown
    assert grace is not None
    assert grace < 10  # the container engine's default stop grace period
    assert not isinstance(config.http, str)
    assert not isinstance(config.ws, str)


@pytest.mark.parametrize(
    ("argv", "address"),
    [
        ([], ("0.0.0.0", 8000)),  # noqa: S104 - the image's command
        (["--host", "127.0.0.1", "--port", "8001"], ("127.0.0.1", 8001)),  # make dev-api
    ],
)
def test_python_m_quiz_serves_the_module_app_with_the_server_config(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], address: tuple[str, int]
) -> None:
    started: list[uvicorn.Config] = []

    class Server:
        def __init__(self, config: uvicorn.Config) -> None:
            self.config = config

        def run(self) -> None:
            started.append(self.config)

    monkeypatch.setattr(uvicorn, "Server", Server)
    quiz_main.main(argv)
    (config,) = started
    assert config.app is module_app()
    assert (config.host, config.port, config.ws_ping_interval) == (*address, 25)
