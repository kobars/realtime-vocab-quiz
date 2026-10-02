# ADR-009 — Repository layout and the Vue client: `api/`, `web/`, generated `contracts/`

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-009 drafted with Claude Code from the repository layout, api/pyproject.toml and web/package.json, checked by hand against the code. -->

- **Status:** accepted; files moved to `web/packages/clay/` by [ADR-013](013-clay-workspace-package.md)
- **Date:** 2026-10-01

## Context

The service has a Python server and a browser client that must agree on every message. Both are reviewed and tested in one repository with one gate (`make check`), and the client is a small single-page app: a join screen, a question screen with feedback, a finished screen and the live leaderboard, with no server rendering and no search-engine needs.

## Decision

- **Layout:** one repository with `api/` (the Python package `quiz`, managed by uv), `web/` (the client, managed by pnpm) and `contracts/` (the generated JSON Schema). The Pydantic models in `api/src/quiz/contracts/` are the only hand-written definition of the protocol; `make contracts` writes `contracts/schema/protocol.json` and `web/src/protocol/types.generated.ts`, and `make check` fails when a generated file differs from git.
- **Client stack:** Vue 3 with Vite and TypeScript, Pinia for the quiz state, Vue Router for the screens, Tailwind CSS 4 with shadcn-vue components on reka-ui, tested with Vitest in happy-dom. The protocol client (backoff, `seq` tracking, resync) is plain TypeScript in `web/src/protocol/`, independent of Vue, so it is tested without a browser.

## Alternatives considered

- **Two repositories:** independent releases, but every protocol change becomes two PRs that must land together, and the drift check could not run in one gate. Rejected.
- **Hand-written TypeScript types, or a shared JSON Schema edited by hand:** no generator to maintain, but two definitions drift silently. Rejected for one generated source.
- **React (with Vite or Next.js):** the largest ecosystem, but Next.js brings server rendering that a socket-driven single page does not need, and React needs extra libraries for the store and for fine-grained updates of a list that changes five times a second. Vue's reactivity, single-file components and Pinia cover this app with fewer parts. Rejected by a small margin.
- **Svelte:** small bundles and simple stores, but a smaller set of ready accessible components; shadcn-vue on reka-ui gives accessible primitives that are copied in and styled with Tailwind. Rejected.

## Consequences

- A protocol change is one PR: edit the Pydantic model, run `make contracts`, and the client sees the new types at compile time (`vue-tsc` in `make check`).
- Two toolchains to install (uv and pnpm), each with a committed lock file; CI installs both from the locks.
- shadcn-vue components live in `web/src/components/ui/` as our own code, so we maintain them instead of upgrading a package.

<!-- AI-ASSISTED-END -->
