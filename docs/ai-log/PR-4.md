## PR-4 — Describe the merge-first review order in AGENTS.md

- **Tool:** Claude Code (claude-opus-5-5)
- **Task:** Update the review lines of `AGENTS.md` to the review order the repository uses: a PR merges when CI and `make check` are green, gets one review round after the merge (two reviewers, findings combined and each verified), and confirmed findings are fixed in a separate small fix PR with no second round.
- **Prompt / interaction:** The agent was given the confirmed finding from the review of PR-1 that `AGENTS.md` still described fixing findings in the same PR before the merge, and rewrote that one bullet.
- **What was wrong or changed:** `AGENTS.md` line 10 said "Confirmed findings are fixed in the same PR"; that text matched the review order in place when PR-1 was written, so it is a stale rule rather than an AI mistake. The bullet now describes the merge-first order and sits after the rebase-and-check bullet. Documentation only; no code changed.
- **Verification:** `make check` (exit 0), `grep -n "same PR" AGENTS.md` (no output), `wc -l AGENTS.md` (48 lines). The change is prose, so no test covers it, and no test file exists in the repository yet.
- **Reviewed by:** Claude Code `/code-review` (high) and Codex (`gpt-6-astra`, high reasoning), after the merge; the verified findings are in the PR comment.
- **Date:** 2026-10-01
- **Phase:** implementation
- **Commit:** cc3ce7f
