# AI-ASSISTED: the bot swarm image: Python with the load dependency group only; run it with `make load`.
# Build from the repository root: docker build -f load/Dockerfile .

FROM python:3.14-slim@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4
COPY --from=ghcr.io/astral-sh/uv:0.10.2@sha256:94a23af2d50e97b87b522d3cea24aaf8a1faedec1344c952767434f69585cbf9 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY api/pyproject.toml api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --only-group load --no-install-project
COPY load/*.py ./
# make load runs it as the host user, so its result files in the bind-mounted load/results are
# the user's; a run is a batch job with no service to probe.
USER 10001:10001
HEALTHCHECK NONE
ENTRYPOINT ["python", "bots.py"]
