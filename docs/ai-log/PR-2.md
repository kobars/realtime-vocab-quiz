## PR-2 — Follow-up fixes for the bootstrap review

- **Tool:** Claude Code (claude-opus-5-5)
- **Task:** Verify the review findings on PR-1 that its review round had not checked, and fix the confirmed ones: the `@types/node` major, the missing `AI-ASSISTED:` markers in two project files, the acceptance-folder rule in `AGENTS.md` and the stale target list in the README.
- **Prompt / interaction:** The agent re-read each finding against `main`, ran the commands that settle it, posted the verdicts on PR-1, and made the four small fixes.
- **What was wrong or changed:** Four of six findings were confirmed and fixed; two were refuted (the `contracts/` folder in the ADR index is the planned generated output, and the DESIGN.md section headings already match the planned requirement mapping). `pnpm add -D @types/node@^24.19.0` regenerated the lock; happy-dom still pulls `@types/node` 26 transitively, which does not change the client's own type definitions.
- **Verification:** `make check` (exit 0, including `pnpm -C web install --frozen-lockfile`), `pnpm -C web why @types/node` (direct dependency 24.19.0), `grep -n AI-ASSISTED api/pyproject.toml web/pnpm-workspace.yaml` (one marker each). No test file exists yet; the first tests arrive with the quality harness.
- **Reviewed by:** none of its own; it is the fix PR of the review round on PR-1, whose verified findings are in the PR-1 comment.
- **Date:** 2026-10-01
- **Phase:** implementation
- **Commit:** c2f667c
