# ADR-005 — Redis sorted set and Lua scripts for scoring; AOF `everysec`

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-005 drafted with Claude Code from the reviewed design drafts, checked by hand against docs/spec/. -->

- **Status:** accepted
- **Date:** 2026-10-01

## Context

Any of two or more API nodes can receive any player's request. Scoring an answer reads the player's progress and the serve time, checks two idempotency layers and the deadline, and writes the answer, the total and the standing; a join and a serve are multi-step too. If two nodes interleave these steps, a (player, question) can score twice or a total can disagree with the leaderboard (C1, C3). The leaderboard must be read in rank order many times a second.

## Decision

Redis 8 (Valkey 8 also works) holds all quiz state. The standings are one sorted set per quiz with the composite score `(2^30 − total) × 2^22 + reachedRelMs`, read with `ZRANGE` ascending. Every multi-step write is one Lua script (`create_quiz`, `join`, `serve_question`, `score_answer`, `publish_leaderboard`, `leave`, `end_quiz`), and every time inside a script comes from Redis `TIME`. The points formula lives once in `lua/lib/points.lua`, put in front of the scoring script by the loader. Persistence is AOF with `appendfsync everysec`. The contracts are in `docs/spec/redis.md`.

## Alternatives considered

- **`WATCH`/`MULTI` optimistic transactions:** no Lua, but every conflict means a retry round trip, and a hot quiz conflicts on every answer. Rejected.
- **Redis Functions:** a cleaner way to ship shared code than a loader, but they need `FUNCTION LOAD` on deploy and differ in detail between Redis and Valkey. Plain scripts with a loader are enough for seven scripts.
- **PostgreSQL with row locks:** durable and familiar, but a leaderboard query per tick and a lock per answer cost far more than a sorted set. Rejected for v1.
- **State in each node's memory:** fastest, but two nodes would hold two truths. Rejected.
- **AOF `always`:** no loss on a crash, but an fsync per write. **No persistence:** a restart loses every quiz. `everysec` is the middle.

## Consequences

- C1, C3 and C6 hold by construction: every check and its write happen in one atomic script on one clock.
- A crash of Redis can lose about 1 s of writes; DESIGN §11 states it, and clients recover through `seq` and resync.
- Scripts block Redis while they run, so each one stays O(log N) per write, except the tick. The tick reads at most 200 rows, and above 200 players it also runs one `ZRANK` for each scorer since the last frame and one `HGET` for each of those outside the top 50, so its cost is O(S log N) for S scorers among N players and grows with a scoring burst. The load runs should measure the tick script under a synchronized scoring burst.
- The quiz window is capped at 60 min so that `reachedRelMs` fits in 22 bits.

<!-- AI-ASSISTED-END -->
