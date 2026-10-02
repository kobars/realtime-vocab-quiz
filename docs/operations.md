<!-- AI-ASSISTED: running the stack outside a laptop: the public-host deployment behind HTTPS. -->
# Operations

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
   the certificate stay in their volumes.
6. To update: `git pull && make prod-up`.

The admin API stays the mock one (`ADMIN_MOCK=1`): anyone who holds `ADMIN_TOKEN` can create and
end quizzes, and the token is its only guard, so keep `.env` private.
