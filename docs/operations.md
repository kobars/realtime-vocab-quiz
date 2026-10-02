<!-- AI-ASSISTED: operating the stack: ports, endpoints, configuration, metrics, and the public-host deployment behind HTTPS: the published images, the Droplet from a laptop, install, update, backup and restore. -->
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
| `PUBLIC_HOSTING` | on | Any visitor may host a quiz (`POST /api/quizzes`) and end it with its host token; `0` removes the hosting routes (404). On in the source, the images and both `.env` examples |
| `HOSTING_WINDOW_MS` | `1800000` | Every self-hosted quiz's window: 1 to 60 min |
| `HOSTING_MAX_OPEN` | `50` | Open self-hosted quizzes, all nodes together; above it `POST /api/quizzes` answers 503 `HOSTING_FULL` |
| `HOSTING_PER_IP`, `HOSTING_PER_IP_WINDOW_S` | `5`, `600` | Quizzes one client address may host per window; above it 429 `RATE_LIMITED` with `Retry-After` |
| `HOSTING_BANKS` | `VOCAB-42,BIZ-20,ACAD-10` | The bank quizzes a visitor may host (`GET /api/banks`) |

`make dev-api` takes `DEV_API_PORT` (8001) and `DEV_ORIGINS`; the client dev server takes
`QUIZ_API_URL` to proxy to another API node.

## Deploy to a VM

One Linux VM with Docker runs the whole stack behind HTTPS. It pulls the images that CI
publishes (see [Image tags](#image-tags)), so the VM builds nothing: 2 vCPU and 4 GB of memory
are enough for a busy demo, and a 1 GiB Droplet runs a small one. Measured on an isolated copy of
the stack, the containers used at most 255 MiB with 300 bots answering (the two API nodes 73
and 62 MiB, nginx 94, Redis 15, the client 11) and Caddy 54 MiB idle. nginx starts one worker
per CPU, about 10 MiB each, and that host had 12 CPUs; a 1 vCPU Droplet runs one worker. On
1 GiB, set `REDIS_MAXMEMORY=256mb` in `.env`, since the example's `1gb` would let Redis outgrow
the machine, and keep the published images: building them needs more memory than that.
[compose.prod.yaml](../compose.prod.yaml) adds Caddy in front of nginx: it gets a
Let's Encrypt certificate for `DOMAIN` and renews it, redirects HTTP to HTTPS and proxies the
page, the API and the WebSocket to nginx, which publishes no port of its own. nginx takes each
player's address from Caddy, so the per-address caps count every player apart.

In the VM's firewall, allow inbound TCP 22, 80 and 443 only. Without a domain, the stack serves
on `<ip>.sslip.io` (for example `203.0.113.7.sslip.io`), a name that resolves to the address it
contains. With a domain, its DNS A record (IPv4, and no AAAA record) points at the VM.

### From a laptop

With [`doctl`](https://docs.digitalocean.com/reference/doctl/how-to/install/) installed and
signed in (`doctl auth init`; the script never reads or stores a token) and an SSH key in the
DigitalOcean account (`doctl compute ssh-key import`), one command creates the host:

```bash
make do-deploy DOMAIN=quiz.example.com   # REGION=sgp1 and SIZE=s-2vcpu-4gb by default
```

[scripts/deploy/droplet.sh](../scripts/deploy/droplet.sh) creates a Cloud Firewall that allows
inbound TCP 22, 80 and 443 only, for every Droplet tagged `realtime-vocab-quiz`; an Ubuntu
24.04 Droplet with that tag, every SSH key of the account and no root password, whose user data
is [infra/deploy/cloud-init.yaml](../infra/deploy/cloud-init.yaml) with `DOMAIN` filled in; and,
when the domain is a DigitalOcean zone, its A record. For a domain hosted elsewhere it prints
the address to point the record at. Without `DOMAIN` the stack serves on
`<droplet-ip>.sslip.io`. It then waits up to 40 minutes (the install waits up to 30 for a DNS
record hosted elsewhere) for `https://DOMAIN/api/readyz`, starts
a 60-minute quiz over SSH (`make prod-demo` on the Droplet) and prints its player link. It stops
before creating anything when doctl is not signed in, a lookup fails, the account has no SSH key,
a Droplet with the tag exists, or the domain's DigitalOcean zone already has an A or AAAA record
of that name (the install needs the name to point at the new Droplet alone). `DRY_RUN=1` runs only the lookups and prints each command that would create
something.

`make do-destroy` lists the Droplets tagged `realtime-vocab-quiz`, the A records that point at
them under their own name, and the firewall of that name, and deletes them once you type `yes`;
the Droplet's quiz data goes with it (`make prod-backup` first to keep it). `DRY_RUN=1` prints
the deletes instead.

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
`make prod-up` on the published images of `--ref` (`main` or a `vX.Y.Z` tag; `--build` builds
them on the VM instead, and another ref needs it), waits up to 3 minutes for
`https://DOMAIN/api/readyz` and prints the next steps.
Without `--domain` it finds the VM's public IPv4 address from DigitalOcean's metadata service or
a public echo service. It stops with a clear error when it is not run as root, on another OS,
when ports 80 or 443 are in use, or when the domain does not resolve to this VM in public DNS
(asked through Google Public DNS's JSON API, else the system's resolver): that check runs before
Caddy asks for a certificate, so a wrong record does not use up Let's Encrypt's rate limits.
Running it again is safe: it keeps `.env` and its secrets, changes `DOMAIN` only when `--domain`
is given, and sets `IMAGE_TAG` and `COMPOSE_FILE` from `--ref` and `--build`. `--ref` picks
another branch or tag, `--ip` gives the address, and
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

3. `make prod-up` pulls the published images of `main` and starts the stack (to build them
   instead, see [Image tags](#image-tags)); Caddy gets the certificate within a minute. Check
   it from any machine: `curl https://quiz.example.com/api/readyz` prints `{"status":"ready"}`.

### Image tags

On every push to `main` and on every `vX.Y.Z` tag, the containers workflow builds the API and
web images for amd64 and arm64, pushes them by digest with an SBOM and their build provenance,
scans each with Trivy as pulled (a CRITICAL or HIGH finding with a fix stops the publish), and
only then tags them and adds a signed provenance attestation:

| Image | Tags |
|---|---|
| `ghcr.io/kobars/realtime-vocab-quiz-api`, `ghcr.io/kobars/realtime-vocab-quiz-web` | `main` (the latest commit of `main`), the commit's short SHA (7 characters, for example `1a2b3c4`), `vX.Y.Z` for a release tag |

GHCR creates each package as private on its first publish. Make both public once, so that a VM
pulls them without a login: open
`https://github.com/users/kobars/packages/container/realtime-vocab-quiz-api/settings` (and the
same page for `realtime-vocab-quiz-web`), choose **Change visibility** under **Danger Zone**,
select **Public** and type the package name to confirm. GitHub's REST API reads a package's
visibility but cannot change it; `gh api /users/kobars/packages/container/realtime-vocab-quiz-api
--jq .visibility` prints it (after `gh auth refresh -s read:packages`). While a package is private,
or before the first publish of a tag, an anonymous pull fails ("denied" or "manifest unknown"):
`make prod-up`, `make prod-update` and the install script then print a warning and build the
images on the host from the checkout instead, under the published names, so the stack still
starts (on 1 GiB that build may run out of memory).
`gh attestation verify oci://ghcr.io/kobars/realtime-vocab-quiz-api:main -R
kobars/realtime-vocab-quiz` checks that an image was built by this repository's workflow.

`IMAGE_TAG` in `.env` picks the tag, and [compose.images.yaml](../compose.images.yaml), listed
in the example's `COMPOSE_FILE`, puts those images in place of the ones `make build` makes. The
prod targets add that override whenever `IMAGE_TAG` is set, in `.env` or on the command line:
`make prod-up IMAGE_TAG=1a2b3c4` runs one commit's images for that command (set it in `.env` to
keep them for the other targets). To build the images on the host
instead (a branch with no published images, or a local change), leave `IMAGE_TAG` empty and drop
`:compose.images.yaml` from `COMPOSE_FILE`, or run the install with `--build`.

### Update

`make prod-update` notes the running commit, fast-forwards the branch the checkout is on to its
newest commit on GitHub, starts the stack again (pulling the tag's images, or building them when
`IMAGE_TAG` is empty; nginx and Caddy are recreated for new config) and waits for `readyz`.
`make prod-update REF=<tag or branch>` moves to that ref instead; an install from a tag
(`--ref v1.2.0`) is on no branch, so its updates name the next tag. On published images, a
`vX.Y.Z` ref or a commit's short SHA runs that tag's images and becomes `IMAGE_TAG` in `.env`
once it is ready; a short-SHA `IMAGE_TAG` follows the checkout to its new commit. A branch other
than `main` needs `BUILD=1`, which builds the images on the host under the current tag's name
(the next pull replaces them). The `main` images follow the branch a few minutes after a merge,
once the containers workflow has published them. When the update does not get ready, it checks
out the commit that ran before and starts it on the images that ran before (kept as the
`rollback` tag before the pull, then tagged as `IMAGE_TAG` again, so every prod target runs
them), then exits non-zero with a message that says whether the rollback is ready. An update of
a stopped stack keeps no images, so when it fails it puts the checkout back and stops there.

### Backup and restore

`make prod-backup` writes `backups/quiz-<UTC time>.tar.gz` (or `FILE=<path>`): a Redis snapshot
taken with `BGSAVE` while the stack runs, Caddy's data volume (the certificates and the ACME
account) and `.env`. **The file holds the secrets and the TLS private keys**: it is readable by
root only, even when it replaces an older file; copy it off the VM and keep it private. The
image builds leave out `backups/` and `.env.before-restore`.

`make prod-restore FILE=<backup>` restores one, for example onto a fresh install on a new VM
(after pointing the domain at it): it stops the stack, keeps the current `.env` as
`.env.before-restore`, puts back the backup's `.env`, Redis data and certificates, and starts
the stack again. When the backup's `DOMAIN` is an `<ip>.sslip.io` name, which points at the old
VM, the new VM keeps its own `DOMAIN`. The current Redis data stays until the backup's snapshot
has loaded: when it does not load, the restore puts the previous `.env` back, starts the stack on
its old data and exits non-zero.

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
