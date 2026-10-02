# AI-ASSISTED: the bot swarm image: Python with the load dependency group only; run it with `make load`.
# Build from the repository root: docker build -f load/Dockerfile .

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY api/pyproject.toml api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --only-group load --no-install-project
COPY load/bots.py load/latency.py load/player.py ./
# make load runs it as the host user, so its result files in the bind-mounted load/results are
# the user's; a run is a batch job with no service to probe.
USER 10001:10001
HEALTHCHECK NONE
ENTRYPOINT ["python", "bots.py"]
