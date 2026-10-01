## PR-6 — Add the internal-content guard and the server quality harness

- **Tool:** Claude Code (claude-opus-5-5)
- **Task:** Add `scripts/check_internal.py` with its tests, the ruff, mypy and pytest configuration (strict markers, folder markers, Hypothesis `dev` and `ci` profiles), a server smoke test, and the `check`, `test` and `test-integration` recipes.
- **Prompt / interaction:** The agent wrote the guard tests and the guard together, configured the tools, then ran each `make` target and fed deliberately bad files to confirm that each step fails and names itself.
- **What was wrong or changed:** (1) A must-catch sample in the guard's test file spelled one flagged word in full, so the guard failed on its own tracked files; the sample is now assembled from parts. (2) A bad `--commits` range crashed with a traceback; it now exits 2 with a message. (3) Ruff run from the repository root with `--config api/pyproject.toml` resolved the per-file-ignore globs against the working directory, so `scripts/` got the wrong ignores; the recipes now run ruff from `api/`, where both folders get the same settings. (4) The first draft also held the client checks, pre-commit and the CI workflow and came to 560 changed lines; those moved to the next PR.
- **Verification:** `make check` (exit 0; 40 tests), `make test-integration` (exit 0, no integration tests yet), a deliberately unformatted file stopping `make check` at the ruff format step. Tests: `scripts/tests/test_check_internal.py` (including `test_bad_commit_range_is_an_error_not_a_crash`) and `api/tests/unit/test_smoke.py`.
- **Reviewed by:** Claude Code `/code-review` (high) and Codex (`gpt-6-astra`, high reasoning), after the merge; the verified findings are in the PR comment.
- **Date:** 2026-10-01
- **Phase:** implementation
- **Commit:** 6806e9f
