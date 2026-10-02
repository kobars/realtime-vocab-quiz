# ADR-007 — Backplane: Redis pub/sub, `seq` and resync (Streams as the next step)

[All decisions](../DECISIONS.md)

<!-- AI-ASSISTED-BEGIN: ADR-007 drafted with Claude Code from the reviewed design drafts, checked by hand against docs/spec/. -->

- **Status:** accepted
- **Date:** 2026-10-01

## Context

A frame published by one node must reach the clients on every node. Nodes and their Redis connections can drop and come back; a client must be able to tell that it missed a frame and recover without a full reload.

## Decision

The script that publishes a broadcast also increments the quiz's `seq` and publishes the frame on `quiz:{<quizId>}:events` in the same step. Every node subscribes to the channels of the quizzes it serves and relays each frame to its sockets. Delivery is at most once: a client that sees a gap, a lost last frame (`pong.seq`) or a lower `seq` sends `resync` and gets a full `snapshot`; a node that resubscribes sends each of its clients a snapshot.

A second channel per quiz, `quiz:{<quizId>}:control`, carries `session_replaced` from the `join` script to whichever node holds the replaced socket, which closes it with 4001. It has no `seq` and is never relayed to clients. Because pub/sub may drop it, the serve and scoring scripts also check the caller's connection ID against the player's current one and refuse a replaced connection with `SESSION_REPLACED`.

## Alternatives considered

- **Redis Streams** (`XADD` with a cap, read with `XREAD` from the last ID): a node could replay what it missed instead of snapshotting, and the history would survive a node restart. It costs a reader loop per node, trimming, and replay logic on top of resync, which is needed anyway. It is the next step if snapshots after resubscribes become frequent.
- **A message broker (NATS, Kafka):** another service to run and monitor, for one channel per quiz. Rejected for v1.
- **Node-to-node messages:** every node needs the list of the others. Rejected.

## Consequences

- Frames reach each node in `seq` order, because Redis serves one subscription connection in publish order.
- A lost frame costs one snapshot per affected client, never a wrong board: frames are full standings (ADR-004).
- After a Redis data loss `seq` can go back; clients treat a lower `seq` as a restart and resync.
- Each node subscribes to two channels per quiz it serves. Session replacement works across nodes without node-to-node messages, and stays correct when a control message is lost.

<!-- AI-ASSISTED-END -->
