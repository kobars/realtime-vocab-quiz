<!-- AI-ASSISTED: operating the stack: ports, endpoints, configuration, metrics, and the public-host deployment behind HTTPS. -->
# Operations

## Ports and endpoints

| What | Where |
|---|---|
| nginx, the stack's only published port | `127.0.0.1:8080` (`QUIZ_PORT`): `/` the client, `/api/*` (prefix dropped) and `/ws` the API nodes |
| API nodes `api-1`, `api-2` | port 8000 inside the Compose network only |
| Stack Redis | port 6379 inside the Compose network only, with a password |
| Development API (`make dev-api`) | `127.0.0.1:8001` |
| Client dev server (`pnpm -C web dev`) | `localhost:5173` |
| Development Redis (`make up`) | `127.0.0.1:6381`, no password |

Each API node serves `/healthz` (liveness: the process answers), `/readyz` (readiness: 503
when Redis is unreachable) and `/metrics` (Prometheus text format). nginx passes the first two
on as `/api/healthz` and `/api/readyz`, and both return 200 on a healthy stack:

```bash
curl -s -w ' %{http_code}\n' http://localhost:8080/api/healthz   # {"status":"ok"} 200
curl -s -w ' %{http_code}\n' http://localhost:8080/api/readyz    # {"status":"ready"} 200
```

## Metrics

nginx answers 404 for `/api/metrics`, so the metrics are read from inside a node. There is no
Prometheus server or dashboard container; any Prometheus can scrape the nodes on the Compose
network.

```bash
docker compose exec api-1 python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/metrics').read().decode())"
```

[DESIGN.md §13](../DESIGN.md#13-observability) lists every metric, the logs and the SLO they
check.

## Configuration

The API reads environment variables only (it never loads a `.env` file; Compose reads `.env`
for the stack). [`api/src/quiz/config.py`](../api/src/quiz/config.py) lists every setting with
its default, and [`.env.example`](../.env.example) shows the common ones.

| Variable | Default | Meaning |
|---|---|---|
| `STORE` | `memory`; `redis` in the API image | `memory` for one process, `redis` for several nodes |
| `REDIS_URL` | `redis://127.0.0.1:6381/0` | The Redis that `make up` starts (`make down` stops it) |
| `ALLOWED_ORIGINS` | `http://localhost:8080`, `http://127.0.0.1:8080` | Comma-separated origins allowed to open the WebSocket; others get HTTP 403. `make dev-api` sets the client dev server's origins |
| `QUIZ_PORT` | `8080` | The public port; the default allowed origins use it |
| `ADMIN_MOCK`, `ADMIN_TOKEN` | off, none | Turn on the mock admin API; it needs a non-blank token |
| `REDIS_PASSWORD` | none | The stack Redis password (Docker stack only) |
| `PER_IP_CONN_CAP` | `50` | WebSocket connections per client address; `make demo` raises it when it is unset |

`make dev-api` takes `DEV_API_PORT` (8001) and `DEV_ORIGINS`; the client dev server takes
`QUIZ_API_URL` to proxy to another API node.

## Deploy to a VM

One Linux VM with Docker runs the whole stack behind HTTPS: 2 vCPU and 4 GB of memory are enough
for the demo. [compose.prod.yaml](../compose.prod.yaml) adds Caddy in front of nginx: it gets a
Let's Encrypt certificate for `DOMAIN` and renews it, redirects HTTP to HTTPS and proxies the
page, the API and the WebSocket to nginx, which publishes no port of its own. nginx takes each
player's address from Caddy, so the per-address caps count every player apart.

1. Create an Ubuntu LTS VM with Docker Engine and the Compose plugin installed, plus `git`,
   `make` and `openssl`. In its firewall, allow inbound TCP 22, 80 and 443 only.
2. Point a DNS A record (IPv4, no AAAA record) for your host name at the VM's public address.
   Without a domain, use `<ip>.sslip.io` as `DOMAIN`, for example `203.0.113.7.sslip.io`.
3. Clone the repository and write `.env` from the example, with your host name and two new
   secrets:

   ```bash
   git clone https://github.com/kobars/realtime-vocab-quiz.git && cd realtime-vocab-quiz
   cp .env.prod.example .env
   sed -i "s/^DOMAIN=.*/DOMAIN=quiz.example.com/" .env
   sed -i "s/^ADMIN_TOKEN=$/&$(openssl rand -hex 24)/; s/^REDIS_PASSWORD=$/&$(openssl rand -hex 24)/" .env
   ```

4. `make prod-up` builds the images and starts the stack; Caddy gets the certificate within a
   minute. Check it from any machine: `curl https://quiz.example.com/api/readyz` prints
   `{"status":"ready"}`.
5. `make prod-demo` starts a fresh 60-minute quiz and prints its HTTPS player URL.
   `make prod-logs` follows the logs and `make prod-down` stops the stack; the quiz data and
   the certificate stay in their volumes. The example's `COMPOSE_FILE` makes plain
   `docker compose` and the other make targets act on this stack too.
6. To update: `git pull && make prod-up`, which also recreates nginx and Caddy for new config.

The admin API stays the mock one (`ADMIN_MOCK=1`): anyone who holds `ADMIN_TOKEN` can create and
end quizzes, and the token is its only guard, so keep `.env` private.
