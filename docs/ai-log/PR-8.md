## PR-8 — Add the web checks, pre-commit hooks and the pull-request CI workflow

- **Tool:** Claude Code (claude-opus-5-5)
- **Task:** Add ESLint (typescript-eslint strict, eslint-plugin-vue), strict `vue-tsc --noEmit` and Vitest with happy-dom to `make check` and `make test`; add pre-commit hooks for the internal-content guard, ruff and ESLint; add one GitHub Actions workflow that runs `make check`, the Redis integration tests and the guard on every pull request.
- **Prompt / interaction:** The agent configured the client tools and the hooks, wrote a smoke test that mounts a Vue component, wrote the workflow, then ran every gate locally and fed a deliberately bad file to confirm the ESLint step fails and names itself.
- **What was wrong or changed:** (1) The workflow referenced `astral-sh/setup-uv@v10`, a major tag that the action does not publish (it ships only full version tags since v8), so the first CI run failed at "Set up job" in the `check` and `integration` jobs; the workflow now pins `astral-sh/setup-uv@v10.2.0`, and the other three actions were checked to have the major tags used. (2) These files were split out of the previous PR to keep each PR under 400 changed lines.
- **Verification:** `make check` (exit 0; Vitest 2 passed), `make test-integration` (exit 0, no integration tests yet), `uvx pre-commit run --all-files` (all four hooks pass), a file containing `const x: any = 1` stopping `make check` with `make: step "eslint" failed`, and the workflow's own run on this PR (`check`, `integration` and `internal` green after the fix). Test: `web/src/smoke.test.ts`.
- **Reviewed by:** Claude Code `/code-review` (high) and Codex (`gpt-6-astra`, high reasoning), after the merge; the verified findings are in the PR comment.
- **Date:** 2026-10-01
- **Phase:** implementation
- **Commit:** 62aecd5
