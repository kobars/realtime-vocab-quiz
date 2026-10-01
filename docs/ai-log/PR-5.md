## PR-5 — Add the WebSocket protocol spec and ADR-003, ADR-004

- **Tool:** Claude Code (claude-opus-5-5)
- **Task:** Write `docs/spec/protocol.md`, the v1 wire contract of the self-paced quiz (envelope, field types, message catalog, `seq` and `atSeq` rules, standings policy, conflation, countdown, error and close codes, ticket authentication, limits, sequence diagrams), and ADR-003 and ADR-004 in `docs/DECISIONS.md`.
- **Prompt / interaction:** The agent worked from a written list of the protocol rules (message names, `seq` rules, answer semantics, codes, limits, the standings policy) and the merged domain spec, and drafted the catalog, the client rules, the diagrams and both ADRs itself.
- **What was wrong or changed:** The first draft of the client's `seq` table ignored every `leaderboard` frame with `seq` at or below the last applied one, with an exception for new sockets; that contradicted the rule that a lower `seq` means the store restarted. It now ignores only `seq = lastSeq` (a duplicate relayed right after a snapshot) and resyncs on a lower one. The draft also let a `pong` overtake a `leaderboard` frame held back for a slow socket, so `pong.seq > lastSeq` could fire a needless resync; the conflation section now keeps the held frame's place in the queue.
- **Verification:** `make check` (exit 0 after rebasing on `main`). Documentation only; no test file exists yet. The spec names the test that will prove the `seq` rule, `api/tests/integration/test_seq.py`.
- **Reviewed by:** Claude Code `/code-review` (high) and Codex (`gpt-6-astra`, high reasoning), after the merge; the verified findings are in the PR comment.
- **Date:** 2026-10-01
- **Phase:** design
- **Commit:** 8fe6210
