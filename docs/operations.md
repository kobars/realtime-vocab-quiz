<!-- AI-ASSISTED: operating the stack: ports, endpoints, configuration, metrics, and the public-host deployment behind HTTPS: install, update, backup and restore. -->
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
on as `/api/healthz` and `/api/readyz`, and both return 200 on a healthy stack (step 3 of
[Run the full stack](../CONTRIBUTING.md#run-the-full-stack) checks them with `curl`).

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

In the VM's firewall, allow inbound TCP 22, 80 and 443 only. Without a domain, the stack serves
on `<ip>.sslip.io` (for example `203.0.113.7.sslip.io`), a name that resolves to the address it
contains. With a domain, its DNS A record (IPv4, and no AAAA record) points at the VM.

### Five-minute install

**DigitalOcean Droplet.** Create an Ubuntu 24.04 Droplet and paste
[infra/deploy/cloud-init.yaml](../infra/deploy/cloud-init.yaml) as its user data (*Advanced
options*, *Add Initialization scripts*). On the first boot it runs the install script below and
logs to `/var/log/quiz-install.log`; about five minutes later the quiz is at
`https://<droplet-ip>.sslip.io/`. For your own domain, fill in the `DOMAIN=` line before you
paste it and create the A record once the Droplet shows its address: the install waits up to 30
minutes for the record.

**Any Ubuntu 22.04 or 24.04 VM.** As root, in one command:

```bash
curl -fsSL https://raw.githubusercontent.com/kobars/realtime-vocab-quiz/main/scripts/deploy/install.sh \
  | sudo bash -s -- --domain quiz.example.com   # or no option: <ip>.sslip.io
```

[scripts/deploy/install.sh](../scripts/deploy/install.sh) installs Docker Engine with the
Compose plugin, `git`, `make` and `openssl` when they are missing, clones the repository into
`/opt/realtime-vocab-quiz` (or updates it), writes `.env` from
[.env.prod.example](../.env.prod.example) with a new `ADMIN_TOKEN` and `REDIS_PASSWORD`, runs
`make prod-up`, waits up to 3 minutes for `https://DOMAIN/api/readyz` and prints the next steps.
Without `--domain` it finds the VM's public IPv4 address from DigitalOcean's metadata service or
a public echo service. It stops with a clear error when it is not run as root, on another OS,
when ports 80 or 443 are in use, or when the domain does not resolve to this VM: that check runs
before Caddy asks for a certificate, so a wrong record does not use up Let's Encrypt's rate
limits. Running it again is safe: it keeps `.env` and its secrets, and changes `DOMAIN` only when
`--domain` is given. `--ref` picks another branch or tag, `--ip` gives the address, and
`--help` lists every option; `--dry-run` runs the checks and writes `.env` but only prints the
commands that install, clone, start or wait.

Then, in `/opt/realtime-vocab-quiz`, `make prod-demo` starts a fresh 60-minute quiz and prints
its HTTPS player URL. `make prod-logs` follows the logs and `make prod-down` stops the stack;
the quiz data and the certificate stay in their volumes. The example's `COMPOSE_FILE` makes
plain `docker compose` and the other make targets act on this stack too.

### Manual install

1. On an Ubuntu LTS VM, install Docker Engine with the Compose plugin, plus `git`, `make` and
   `openssl`.
2. Clone the repository and write `.env` from the example, with your host name and two new
   secrets:

   ```bash
   git clone https://github.com/kobars/realtime-vocab-quiz.git && cd realtime-vocab-quiz
   cp .env.prod.example .env
   sed -i "s/^DOMAIN=.*/DOMAIN=quiz.example.com/" .env
   sed -i "s/^ADMIN_TOKEN=$/&$(openssl rand -hex 24)/; s/^REDIS_PASSWORD=$/&$(openssl rand -hex 24)/" .env
   ```

3. `make prod-up` builds the images and starts the stack; Caddy gets the certificate within a
   minute. Check it from any machine: `curl https://quiz.example.com/api/readyz` prints
   `{"status":"ready"}`.

### Update

`make prod-update` notes the running commit, runs `git pull --ff-only` and `make prod-up` (which
also recreates nginx and Caddy for new config), and waits for `readyz`. When the new commit does
not get ready, it checks out the commit that ran before, starts that again and exits non-zero
with a message that says whether the rollback is ready.

### Backup and restore

`make prod-backup` writes `backups/quiz-<UTC time>.tar.gz` (or `FILE=<path>`): a Redis snapshot
taken with `BGSAVE` while the stack runs, Caddy's data volume (the certificates and the ACME
account) and `.env`. **The file holds the secrets and the TLS private keys**: it is readable by
root only; copy it off the VM and keep it private.

`make prod-restore FILE=<backup>` restores one, for example onto a fresh install on a new VM
(after pointing the domain at it): it stops the stack, keeps the current `.env` as
`.env.before-restore`, puts back the backup's `.env`, Redis data and certificates, and starts
the stack again.

### Uninstall

In `/opt/realtime-vocab-quiz`, `docker compose --profile '*' down --volumes --rmi all` stops
the stack and deletes its data, its certificates and its images; then `rm -rf
/opt/realtime-vocab-quiz`. Docker itself stays installed.

The admin API stays the mock one (`ADMIN_MOCK=1`): anyone who holds `ADMIN_TOKEN` can create and
end quizzes, and the token is its only guard, so keep `.env` private.

## Redis timeouts

Each API node bounds how long it waits for Redis, so a Redis that stops answering (a paused or
frozen process, a network that drops packets, a long fork) turns into errors a player can see
and retry, not a frozen screen:

| Setting | Default | Bounds |
|---|---|---|
| `REDIS_POOL_TIMEOUT_MS` | 2000 | the wait for a free connection when every pooled one is busy |
| `REDIS_CONNECT_TIMEOUT_MS` | 2000 | opening a connection to Redis |
| `REDIS_SOCKET_TIMEOUT_MS` | 5000 | the reply to one command or script |

A request whose wait runs out fails like a Redis outage: the socket gets `UNAVAILABLE` and the
HTTP API answers 503, and the client retries with backoff (`next` and `answer` are safe to
repeat, because a command that timed out may still have run). The command timeout must stay
above 2000 ms, the host end's `WAITAOF` wait, which the node refuses to start below, and below
nginx's 60 s proxy timeout, or nginx gives up first. A quiz subscription waits for its next
message without this timeout, so a quiet quiz keeps its feed. Set them in `.env`; compose passes
them to both nodes.
