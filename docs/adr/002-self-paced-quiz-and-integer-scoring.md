# ADR-002 — Self-paced quiz model and the integer scoring rule

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-002 drafted with Claude Code from the reviewed design drafts, checked by hand against docs/spec/. -->

- **Status:** accepted
- **Date:** 2026-10-01

## Context

The product is a real-time vocabulary quiz: users join with a quiz ID, scores update in real time, and a leaderboard shows everyone's standings; the scoring must be accurate and consistent (AC-4). Nothing says who decides when a question opens and closes. The service runs on two API nodes behind nginx with one Redis, so any rule that needs one node to act at a given moment needs coordination between nodes. The speed bonus depends on elapsed time, and the obvious floating-point formula rounds wrongly for some inputs (for `T = 20,000` it gives 132 instead of 133 at 6,800 ms).

## Decision

The quiz is **self-paced**: real-time means live scores and one shared live board; each player sets their own pace. Each player asks for the next question, the server serves it to that player only and records the serve time on Redis `TIME`, and scores the answer when it arrives. A quiz is open for a window that starts at creation (default 10 min, at most 60 min) or until a mock host ends it. Every write checks the deadline in the same Redis script; no timer decides lateness or the end. A correct, on-time answer scores `100 + (50 * (T - e)) // T` in integer milliseconds; wrong or late scores 0. The full rules are in `docs/spec/domain.md`.

## Alternatives considered

- **Host-led quiz:** one host opens each question for everyone at once, and it closes for everyone at once. It matches a classroom, but needs one owner per quiz on one node (a lease with a fencing token) to open and close questions on time, and a failover story when that node dies. Self-paced needs no owner: any node scores any answer atomically in Redis. Host-led stays future work.
- **Per-player question order:** stops answer sharing, but makes totals harder to compare and to test. Deferred; a per-player choice order is the cheaper fix (see Consequences).
- **Client-measured time:** simple, but a client can lie about its answer time. Rejected: the server decides time.
- **Floating-point bonus `50 * (1 - e / T)`:** wrong for 7 of the 20,001 on-time inputs at `T = 20,000`, in Python, Lua and JavaScript alike. Rejected for the exact integer form.

## Consequences

- No per-player or per-question timers on the server; lateness and the deadline are decided when a request arrives, so a node restart loses no timing state.
- Players finish at different times, so a finished player's rank is provisional until `quiz_ended`.
- The correct choice is revealed only in the answering player's own result. With one question order, players can still share answers with players behind them; a per-player choice order is the future fix.
- The window is capped at 60 min because the sorted-set score packs the reach time into 22 bits (about 69.9 min).
- The scoring formula exists in one integer form; a parity test checks the Lua script against Python for every elapsed value from 0 to `T + 1`.

<!-- AI-ASSISTED-END -->
