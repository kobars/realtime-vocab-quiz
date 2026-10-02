# ADR-006 — No owner per quiz: the `dirty` gate and a tick token

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-006 drafted with Claude Code from the reviewed design drafts, checked by hand against docs/spec/. -->

- **Status:** accepted
- **Date:** 2026-10-01

## Context

The leaderboard is coalesced into at most one frame per 200 ms ([ADR-004](004-wire-protocol-standings-and-tick.md)), and players of one quiz are spread over several nodes. Something must decide, every 200 ms, whether a frame goes out and who sends it, without two nodes sending the same frame and without a gap in `seq`.

## Decision

No node owns a quiz. Every node that holds sockets of a quiz calls `publish_leaderboard` about every 200 ms. Inside the script the gate is atomic: if the tick token exists the call returns `busy` with its remaining TTL; if `DEL dirty` returns 0 it returns `clean`; otherwise it sets the token with `SET NX PX 200`, increments `seq` and publishes one frame. A node that got `busy` sleeps until the token expires. Ending a quiz is decided by the deadline check in each write script, and the idempotent `end_quiz` announces it.

## Alternatives considered

- **An owner lease per quiz** (one node holds a renewed lease with a fencing token and runs the tick and the timers): needed for a host-led quiz, where questions must open and close for everyone at a set moment. For a self-paced quiz it adds lease renewal, fencing and a failover delay of up to one lease period, and buys nothing, because no rule depends on a timer.
- **A single tick node:** simple, but a single point of failure that needs its own failover. Rejected.
- **Consistent hashing of quizzes to nodes:** still needs a membership protocol and a handover when a node leaves. Rejected.

## Consequences

- A node can die at any point without a failover step: the script ran entirely or not at all, and another node publishes within about one tick.
- At most one frame per quiz per 200 ms, whatever the number of nodes; the worst-case delay of a score is one token lifetime plus delivery.
- Each node calls the script about 5 times per second per active quiz, even when nothing changed.
- A host-led mode would need an owner lease ([ADR-002](002-self-paced-quiz-and-integer-scoring.md)); this ADR would be superseded for that mode.

<!-- AI-ASSISTED-END -->
