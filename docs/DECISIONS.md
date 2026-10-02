# Architecture decision records

Each decision has its own file, `docs/adr/NNN-<short-slug>.md`, in the format at the end of this page. ADRs are never renumbered; a later ADR supersedes an earlier one, and each new ADR adds one row to the index. An accepted ADR that a later one changes in part stays accepted and names that change after a semicolon, in its file and in the index.

## Index

<!-- AI-ASSISTED-BEGIN: one-line summaries drafted with Claude Code from the ADRs. -->

| ADR | Decision | Status |
|---|---|---|
| [ADR-001](adr/001-real-time-quiz-service-python-fastapi.md) | Build the real-time quiz service for real (Python and FastAPI server, Vue client); mock identity and tickets and the question bank behind ports; quiz admin is a token-gated mock admin API and a mock host action ("end now"). | accepted |
| [ADR-002](adr/002-self-paced-quiz-and-integer-scoring.md) | Self-paced quiz: each player sets their own pace on one shared live board; integer scoring `100 + (50 * (T - e)) // T`, wrong or late 0. | accepted |
| [ADR-003](adr/003-raw-websocket-transport.md) | One raw WebSocket per tab on FastAPI and uvicorn, subprotocol `quiz.v1`, a single-use ticket checked before the upgrade. | accepted |
| [ADR-004](adr/004-wire-protocol-standings-and-tick.md) | Versioned JSON messages with a per-quiz `seq` and resync; full standings up to 200 players, else the top 50 plus `rank_update`; one frame per 200 ms tick. | accepted |
| [ADR-005](adr/005-redis-sorted-set-and-lua-scoring.md) | Redis sorted set with a composite score and one Lua script per multi-step write, on Redis `TIME`; AOF `everysec`. | accepted |
| [ADR-006](adr/006-no-owner-per-quiz-dirty-gate-tick-token.md) | No owner per quiz: any node runs the tick; a `dirty` gate and a 200 ms tick token decide who publishes. | accepted |
| [ADR-007](adr/007-redis-pubsub-backplane.md) | Redis pub/sub carries frames and session replacement between nodes; a gap in `seq` triggers a snapshot; Streams are the next step. | accepted |
| [ADR-008](adr/008-one-redis-schema.md) | One Redis schema: every key of a quiz under the hash tag `quiz:{<quizId>}:*`, one 24 h TTL, ready for a Cluster. | accepted |
| [ADR-009](adr/009-repository-layout-and-vue-client.md) | One repository with `api/`, `web/` and generated `contracts/`; a Vue 3, Vite, Pinia and Tailwind client using types generated from the Pydantic models. | accepted; files moved to `web/packages/clay/` by [ADR-013](adr/013-clay-workspace-package.md) |
| [ADR-010](adr/010-clay-design-system.md) | Our own playful design system, "Clay": brand violet with role fills under dark text, a self-hosted rounded font, hard shadows tinted from the primary, and a dark theme that follows the OS; contrast is a test. | accepted; files moved to `web/packages/clay/` by [ADR-013](adr/013-clay-workspace-package.md) |
| [ADR-011](adr/011-images-pinned-by-digest.md) | Every image pinned by digest and updated by Dependabot; the runtime stages keep the OS package upgrade. | accepted |
| [ADR-012](adr/012-ghcr-images-and-doctl-droplet.md) | CI publishes scanned, attested multi-arch images to GHCR and the public host pulls them by `IMAGE_TAG`; a doctl script, not Terraform, creates the one Droplet, its firewall and DNS record. | accepted |
| [ADR-013](adr/013-clay-workspace-package.md) | The Clay design system is the pnpm workspace package `@quiz/clay` with a typed entry point, its own tests and a Vite gallery page instead of Storybook. | accepted |
| [ADR-014](adr/014-flyio-second-target.md) | A second target on Fly.io: web, API and Redis as three apps in one region; Fly's proxy terminates HTTPS and nginx trusts its `Fly-Client-IP`; nginx reaches the two API Machines through Flycast; Redis on a volume, not managed. | accepted |

<!-- AI-ASSISTED-END -->

## Template

```markdown
# ADR-NNN — <decision>

- **Status:** proposed | accepted | superseded by ADR-NNN
- **Date:** YYYY-MM-DD

## Context
## Decision
## Alternatives considered
## Consequences
```
