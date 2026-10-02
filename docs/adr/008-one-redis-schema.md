# ADR-008 — One Redis schema for scoring and fan-out

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-008 drafted with Claude Code from the reviewed design drafts, checked by hand against docs/spec/. -->

- **Status:** accepted
- **Date:** 2026-10-01

## Context

Scoring, the standings, presence, the tick and the broadcast channel all belong to one quiz, and the tick script must read the standings and write `seq` and the channel in one atomic step. The service must be able to grow past one Redis later.

## Decision

One schema in one Redis: every key of a quiz is `quiz:{<quizId>}:<name>`, with the quiz ID as the hash tag, so a quiz lives in one Cluster slot and each script may touch all of its keys. Each script receives all keys of the quiz in one fixed order. The data keys share one TTL (24 h), kept by every write script, which runs `PEXPIRE` on all of them only once the `meta` TTL has dropped by a minute, and gives a key it creates the `meta` TTL; the tick token keeps its own 200 ms expiry. Lists inside hash fields are JSON arrays. The key table is `docs/spec/redis.md` §2.

## Alternatives considered

- **A separate Redis for pub/sub:** isolates fan-out load, but the tick could no longer increment `seq` and publish atomically. Rejected for v1.
- **Key names without a hash tag:** fine on one Redis, but multi-key scripts fail on a Cluster. Rejected.
- **A database for final results:** results outlive the TTL, but no current feature needs that. Out of scope.

## Consequences

- Scaling out means a Redis Cluster that spreads quizzes over shards; one quiz never spans shards, so the largest quiz is bounded by one shard. On a Cluster, sharded pub/sub (`SPUBLISH`) keeps the channel on the quiz's shard.
- A quiz expires as a whole 24 h after its last write, up to a minute sooner: the minute saves the 13 `PEXPIRE`s, and their AOF records, on every other write.

<!-- AI-ASSISTED-END -->
