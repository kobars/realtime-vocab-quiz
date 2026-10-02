# ADR-014 — Fly.io as a second target: three apps, Flycast to the API, Redis on a volume

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-014 drafted with Claude Code from infra/fly/ and scripts/deploy/fly.sh. -->

- **Status:** accepted
- **Date:** 2026-10-02

## Context

The stack deploys to one Ubuntu VM. A managed platform that runs containers in a region near the players, with TLS and addresses handled for us, removes the VM's upkeep (OS updates, firewall, certificates). Fly.io runs images as Firecracker Machines behind its own proxy; one app runs one image (or process groups of one image), every app of an organization shares a private IPv6 network (6PN) with `.internal` names, and an app can have a private, proxy-balanced Flycast address.

## Decision

- Three apps per deployment, named after a prefix: `<prefix>-web` (the web image: nginx serving the client and running the edge config; the only public app), `<prefix>-api` (two Machines of the API image) and `<prefix>-redis` (one Machine of the pinned Redis image on a volume). Every Machine is shared-cpu-1x (256 MB for the web, 512 MB for the others), auto-stop is off and the restart policy is `always`.
- Fly's proxy terminates TLS on `<prefix>-web.fly.dev` and redirects HTTP; there is no Caddy. nginx takes the client's address from `Fly-Client-IP`, trusted only from the proxy's source range 172.16.0.0/16; it listens on IPv4 only, so other Machines of the organization (6PN, IPv6) cannot reach it to set that header. The Fly edge is a template of its own, rendered by the image's entrypoint, and a test pins each line that differs from the VM edge, so the VM config stays as it is.
- nginx reaches the API through its Flycast address with a raw TCP service: the proxy balances each new connection over the Machines whose `/readyz` passes, keeps the address when a Machine restarts or is replaced, and passes nginx's `X-Forwarded-For` and WebSocket frames untouched. The nodes trust that header from 172.16.0.0/16.
- The API Machines reach Redis at `<prefix>-redis.internal` over 6PN; Redis listens on IPv4 and IPv6 with the compose stack's settings (AOF `everysec`, password, `maxmemory`, `noeviction`), its data in a folder of the volume.
- `scripts/deploy/fly.sh` (`make fly-launch`, `fly-deploy`, `fly-demo`, `fly-status`, `fly-destroy`) drives an already logged-in flyctl. The secrets are generated locally, set through stdin and kept in a git-ignored `.env.fly`, as Fly secrets cannot be read back. It deploys the GHCR images of a tag ([ADR-012](012-ghcr-images-and-doctl-droplet.md)), or builds the Dockerfiles on Fly's remote builder.

## Alternatives considered

- **One app with process groups:** one image only, while the web, the API and Redis use three. Rejected.
- **`.internal` DNS from nginx to the API Machines, re-resolved every few seconds:** nginx would balance and fail over itself, but each node would have to listen on IPv6, nginx would still send to a node that is up but not ready until its connect fails, and the nodes' trusted range would have to be the whole 6PN. Flycast routes on the readiness check and needs neither. Rejected.
- **Flycast with Fly's HTTP handler:** the proxy would append nginx's 6PN address to `X-Forwarded-For` and parse every request and WebSocket again. Raw TCP leaves both to nginx.
- **Caddy on Fly:** a second TLS layer behind Fly's, which already holds the certificate. Rejected.
- **Managed Redis on Fly (Upstash):** no persistence settings of our own: the host's end step waits on `WAITAOF`, and scoring runs Lua scripts, which a managed or serverless Redis may limit or not offer. Rejected for the pinned image on a volume.

## Consequences

- The stack runs in one region with one Redis Machine and one volume: a host failure there stops the quiz until the Machine comes back, as on the VM. Fly snapshots the volume daily.
- Every `make fly-deploy` restarts Redis for a few seconds; the nodes answer 503 meanwhile and the clients retry.
- nginx sees one upstream server, the Flycast address, so unlike the VM edge it cannot retry a failed request or upgrade on the other node. Fly's proxy stops routing to a node once its `/readyz` check fails (checked every 10 s), so a node that goes down can fail requests until then, and the clients retry.
- Any Machine in the organization can reach the API's Flycast address and name a client address; keep the deployment in an organization of its own when other apps share it.
- About 17 USD a month in Singapore for four always-on Machines (an estimate at Fly's published rates).

<!-- AI-ASSISTED-END -->
