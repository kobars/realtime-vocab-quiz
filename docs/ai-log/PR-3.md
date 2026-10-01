## PR-3 — Add the domain spec and ADR-002 for the self-paced quiz

- **Tool:** Claude Code (claude-opus-5-5)
- **Task:** Write `docs/spec/domain.md`, the single definition of the self-paced quiz rules (states, time, scoring, `next`/`answer`/`join` semantics, standings, rule decisions, the consistency contract C1–C6 with the tests to write), and ADR-002 in `docs/DECISIONS.md`.
- **Prompt / interaction:** The agent worked from a written list of the rules to specify (scoring examples, answer-semantics cases, standings order, contract IDs, open rule questions with chosen defaults) and drafted the spec, the diagrams and the ADR itself.
- **What was wrong or changed:** The first draft let the leaderboard tick decide when `quiz_ended` is sent without saying that the final standings never depend on it; the paragraph now separates announcing the end (may follow the tick) from deciding it (the deadline check in each write script). A naive grep for internal IDs also matched `ADR-002`; the check was narrowed to word boundaries. Found after the merge: the §5.1 `next` table had no stated order, its `i = N` row overlapped the `i = c + 1` serve rows at `c = N−1`, a repeat of `next {N}` by a finished player was not specified, and §3.2 said `next {N}` closes only the last question while the table finished from any cursor. A later fix made the table ordered and matched it to the session core (finish from any cursor); `api/tests/unit/test_session.py` (`test_next_n_finishes_from_any_cursor`, `test_a_finished_player_gets_only_the_retry_rows_of_next`) now pins each row.
- **Verification:** `make check` (exit 0 after rebasing on `main`). The scoring examples were recomputed with `100 + (50 * (T - e)) // T`: 0 → 150, 6800 → 133, 20000 → 100, 20001 → 0. No test file exists yet; the spec names the files that will prove each rule, starting with `api/tests/unit/test_scoring.py`.
- **Reviewed by:** Claude Code `/code-review` (high) and Codex (`gpt-6-astra`, high reasoning), after the merge; the verified findings are in the PR comment.
- **Date:** 2026-10-01
- **Phase:** design
- **Commit:** de1f2d4
