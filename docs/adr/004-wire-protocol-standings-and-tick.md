# ADR-004 — Wire protocol, standings policy and the 200 ms coalescing tick

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-004 drafted with Claude Code from the reviewed design drafts, checked by hand against docs/spec/. -->

- **Status:** accepted
- **Date:** 2026-10-01

## Context

With a self-paced quiz (ADR-002), questions and results are per player, but the leaderboard is shared. If every answer, join or leave sent the leaderboard to everyone, cost would grow with the square of the players: 5,000 joins alone would mean about 12.5 million sends. Clients on several nodes must still converge on the same standings (C4), and a lost or dropped frame must be detectable.

## Decision

- **Protocol:** JSON messages `{"v": 1, "type": …}` with strict validation. Broadcasts (`leaderboard`, `quiz_ended`) carry a per-quiz `seq` that grows by exactly 1; unicasts carry `atSeq`; `pong` carries the latest `seq`. A client that sees a gap, a lost last frame or a lower `seq` sends `resync` and gets a full `snapshot`. `next` and `answer` carry the question index, and `answer` a client `submissionId`, so every request is safe to repeat.
- **Standings policy:** each frame carries every player up to 200 players, else the top 50; players outside the top 50 get their own `rank_update` (after the next tick when they scored, at most once per second otherwise). The full list is paged with `get_leaderboard` (1–200 rows). Frames always hold full standings, never a diff.
- **Coalescing tick:** joins, leaves and scoring answers only set a `dirty` flag. While it is set, one node per 200 ms (the holder of the tick token) clears it, increments `seq` and publishes one frame. A slow socket keeps only the newest frame, which then carries `rebase: true`.

## Alternatives considered

- **A broadcast per event:** lowest latency at small scale, but quadratic cost under load. Rejected.
- **Diff frames:** smaller, but a dropped or conflated diff breaks the client's state; full frames are self-healing and stay small with the 200-player cap. Rejected for v1.
- **A 50 ms tick:** four times the frames for little gain against a 500 ms budget. **A 1 s tick:** exceeds the 500 ms budget by itself, since a score could wait a full second before its frame leaves Redis. 200 ms keeps the worst case at one tick plus delivery.
- **Binary encoding (MessagePack, Protocol Buffers):** smaller frames, but harder to read in logs and browser tools; JSON frames of at most 200 rows are small enough. Rejected for v1.

## Consequences

- Fan-out cost per tick is bounded per connection, whatever the number of events in that tick: one `leaderboard` frame and, above 200 players, at most one `rank_update` for a player outside the top 50 (after a tick in which they scored, else at most once per second when their rank shifted). That is at most two messages per connection per tick, 10 per second.
- A score shows on other screens up to 200 ms late, by design; the load runs measure the answer → leaderboard latency against C5.
- Clients must buffer broadcasts while a `resync` is pending and handle `rebase`; the bots and the Vue client share these rules from the protocol spec.
- `pong.seq` is read from Redis for every `ping` (one `GET`; about 400 per second for 10,000 sockets on a node), so a node that relayed nothing yet, or missed a frame on its pub/sub link, still reports the quiz's counter.

<!-- AI-ASSISTED-END -->
