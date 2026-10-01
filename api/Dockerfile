# AI-ASSISTED: the API image: uv installs the locked runtime dependencies, then a slim non-root runtime.
# Build from the repository root: docker build -f api/Dockerfile .

FROM python:3.14-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /usr/local/bin/uv
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

FROM python:3.14-slim AS runtime
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 quiz \
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
