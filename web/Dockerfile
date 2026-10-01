# AI-ASSISTED: the web image: pnpm builds the Vue app, then unprivileged nginx serves dist/ as an SPA.
# Build from the repository root: docker build -f web/Dockerfile .

FROM node:24-slim AS builder
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /web
# Dependencies first, so a source change reuses this layer.
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/pnpm/store \
    pnpm config set store-dir /pnpm/store \
    && pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime
# The base image runs as nginx (101); root only to take the Alpine security fixes its tag lacks.
USER 0
RUN apk upgrade --no-cache
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /web/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "--spider", "http://127.0.0.1:8080/"]
