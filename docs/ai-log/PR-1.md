## PR-1 — Bootstrap the repository layout, dependencies, Makefile and document skeletons

- **Tool:** Claude Code (claude-opus-5-5)
- **Task:** Create the folder layout, the uv and pnpm projects with locked dependencies, the Makefile with every target, the contributor rules and templates, and the DESIGN, DECISIONS and TRACEABILITY skeletons.
- **Prompt / interaction:** The agent worked from a written list of acceptance criteria (layout, dependency list, target names, document headings) and ran `uv add`, `pnpm add` and the checks itself.
- **What was wrong or changed:** The first `pnpm add -D` resolved TypeScript 7.0.2, which typescript-eslint 8.71 does not support (peer range `<6.1`); `pnpm peers check` showed it and TypeScript was pinned to `~6.0.3`. pnpm 11 failed the install on the unapproved `vue-demi` build script; it is now explicitly disallowed in `web/pnpm-workspace.yaml`. `uv init` generated a placeholder `hello()` function and description, both replaced. The first draft exceeded the 400-line budget (417 lines without lock files) and was compacted. Review found that `make check` verified only `api/uv.lock`: a `web/package.json` change without a regenerated `web/pnpm-lock.yaml` still passed. `make check` now also runs `pnpm -C web install --frozen-lockfile`; with a dependency added to `package.json` by hand, it now exits 2.
- **Verification:** `make check` (exit 0), `make help` (14 targets), `uv run --project api python -c 'import fastapi, redis, structlog, hypothesis'` and `pnpm -C web install --frozen-lockfile` all succeeded. No test file exists yet; the first tests arrive with the quality harness.
- **Reviewed by:** a second Claude Code agent (claude-opus-5-5) with `/code-review high`, plus Codex (gpt-6-astra, high reasoning); findings combined and verified in one round
- **Date:** 2026-10-01
- **Phase:** implementation
- **Commit:** 93113d1
