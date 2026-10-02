# AI-ASSISTED: the API image: uv installs the locked runtime dependencies, then a slim non-root runtime.
# Build from the repository root: docker build -f api/Dockerfile .

FROM python:3.14-slim@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4 AS builder
COPY --from=ghcr.io/astral-sh/uv:0.10.2@sha256:94a23af2d50e97b87b522d3cea24aaf8a1faedec1344c952767434f69585cbf9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Dependencies first, so a source change reuses this layer.
COPY api/pyproject.toml api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY api/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.14-slim@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4 AS runtime
# STORE=redis: a node started without STORE never keeps state of its own. It loads its scripts at
# startup, so without a reachable Redis (REDIS_URL) it exits and its supervisor restarts it; /readyz
# answers 503 when Redis goes away later. make dev-api runs from source on the memory store.
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STORE=redis
# The base tag lags behind the Debian security fixes. pip is never used at run time, and its
# vendored libraries carry their own advisories.
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes pip \
    && groupadd --system --gid 10001 quiz \
    && useradd --system --uid 10001 --gid quiz --no-create-home --shell /usr/sbin/nologin quiz
WORKDIR /app
# Only the virtual environment and the source; the venv's editable install points at /app/src.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request, sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status != 200)"]
# python -m quiz runs uvicorn through quiz.adapters.ws.heartbeat.server_config, so the settings
# set the heartbeat (HEARTBEAT_MS) and the frame cap; proxy headers and permessage-deflate are off.
CMD ["python", "-m", "quiz"]
