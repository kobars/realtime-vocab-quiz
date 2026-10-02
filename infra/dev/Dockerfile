# AI-ASSISTED: the development image: the repository with its locked Python and web dependencies, so
# the tests run in a container (compose service test) with no uv or pnpm on the host.
# Build from the repository root: docker build -f infra/dev/Dockerfile .
# The build context's ignore file is infra/dev/Dockerfile.dockerignore: the tests stay in.

FROM node:24-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS node

FROM python:3.14-slim@sha256:0741d101873c12ab927e6f8653feb8862b9bd58771177acb1b885b95141f91b4
COPY --from=ghcr.io/astral-sh/uv:0.10.2@sha256:94a23af2d50e97b87b522d3cea24aaf8a1faedec1344c952767434f69585cbf9 /uv /usr/local/bin/uv
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/corepack /usr/local/lib/node_modules/corepack
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    COREPACK_HOME=/opt/corepack \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    PATH=/repo/api/.venv/bin:$PATH
# make runs the test targets; the script tests build throwaway git repositories. The test image
# takes the distribution's current packages, so they are not pinned.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends git make \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
    && corepack enable pnpm \
    && groupadd --system --gid 10001 dev \
    && useradd --system --uid 10001 --gid dev --create-home --shell /usr/sbin/nologin dev \
    && mkdir -p /repo "$COREPACK_HOME" \
    && chown dev:dev /repo "$COREPACK_HOME"
WORKDIR /repo
USER 10001:10001
# Dependencies first, so a source change reuses these layers.
COPY --chown=10001:10001 .python-version ./
COPY --chown=10001:10001 api/pyproject.toml api/uv.lock api/
RUN uv sync --project api --locked --no-install-project
COPY --chown=10001:10001 web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml web/
# Corepack takes the pnpm of package.json only inside web/; make runs pnpm -C web from the root.
RUN corepack install --global "$(node -p "require('./web/package.json').packageManager")" \
    && pnpm -C web install --frozen-lockfile
COPY --chown=10001:10001 . .
RUN uv sync --project api --locked
# A one-off command (the tests, the bots), not a service with a health to report.
HEALTHCHECK NONE
CMD ["make", "test", "acceptance"]
