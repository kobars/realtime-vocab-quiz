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
# Unknown paths fall back to index.html, so client routes survive a reload; hashed assets cache long.
# No $uri/ step: a Vite build has no directory indexes, and it would 301 a directory path.
COPY <<'CONF' /etc/nginx/conf.d/default.conf
server {
    listen 8080;
    server_name _;
    server_tokens off;
    absolute_redirect off;
    root /usr/share/nginx/html;
    index index.html;

    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files $uri =404;
    }

    location / {
        add_header Cache-Control "no-cache";
        try_files $uri /index.html;
    }
}
CONF
COPY --from=builder /web/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "--spider", "http://127.0.0.1:8080/"]
