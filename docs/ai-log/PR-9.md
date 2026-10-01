## PR-9 — Add the Redis store spec and ADR-005 to ADR-008

- **Tool:** Claude Code (claude-opus-5-5)
- **Task:** Write `docs/spec/redis.md` (key schema, the seven Lua script contracts, one clock, the composite sorted-set score and its limits, coalescing across nodes without an owner, and its failure cases) and ADR-005 to ADR-008 in `docs/DECISIONS.md`.
- **Prompt / interaction:** The agent worked from a written list of the store rules (hash-tagged keys, the `seq` rule, one TTL, the composite score, the dirty gate with a 200 ms token) and the merged domain and protocol specs, and designed the script contracts, the tick loop, the failure table and the four ADRs itself.
- **What was wrong or changed:** While drafting, the agent first planned to run the end of the quiz inside the write script that hit the deadline; that would have made the scoring and join scripts increment `seq` and publish, which breaks the rule that only a publishing script increments `seq`. It caught this against the `seq` rule before writing the table: the refused script returns `QUIZ_ENDED` with `endSeq = nil` and the node calls the idempotent `end_quiz`. It also first planned presence as a plain set that `leave` removes from, so a late grace timer on one node could mark offline a player who had already reconnected on the other node; presence now maps each user to a connection ID and `leave` compares it first.
- **Verification:** `make check` (exit 0 after rebasing on `main`, including `scripts/tests/test_check_internal.py`); `scripts/check_internal.py` and `scripts/check_internal.py --commits origin/main..HEAD` pass. Documentation only; the spec names the tests that will prove it, such as `api/tests/integration/test_seq.py` and `api/tests/integration/test_tick.py`.
- **Reviewed by:** Claude Code `/code-review` (high) and Codex (`gpt-6-astra`, high reasoning), after the merge; the verified findings are in the PR comment.
- **Date:** 2026-10-01
- **Phase:** design
- **Commit:** 1906bf2
