# AI-ASSISTED: static guards on the Dockerfiles, the build context and the make build recipe.
"""The image rules that a build alone does not enforce: the locked install, the non-root user,
the healthchecks, the SPA fallback and a build context without local state.

The files are read as text, so the tests need no Docker daemon.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _stages(dockerfile: Path) -> list[list[str]]:
    """Return the stripped instruction lines of each ``FROM`` stage, comments dropped."""
    stages: list[list[str]] = []
    for raw in dockerfile.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("FROM "):
            stages.append([])
        if stages and line and not line.startswith("#"):
            stages[-1].append(line)
    return stages


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


def test_web_image_serves_dist_from_unprivileged_nginx_with_an_spa_fallback() -> None:
    builder, runtime = _stages(ROOT / "web" / "Dockerfile")
    assert any("pnpm install --frozen-lockfile" in line for line in builder)
    assert "RUN pnpm build" in builder
    assert runtime[0].startswith("FROM nginxinc/nginx-unprivileged:")
    assert "try_files $uri $uri/ /index.html;" in runtime
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
