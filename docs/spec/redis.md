<!-- AI-ASSISTED: Redis key schema, script contracts and cross-node coalescing design, drafted with Claude Code and checked by hand against the domain and protocol specs. -->
# Redis spec: keys, scripts and coalescing across nodes

This document is the store design behind the quiz rules. It keeps the consistency contract (domain §8, C1–C6) true when two or more API nodes serve the same quiz against one Redis, with no node owning a quiz. The rules themselves are in `docs/spec/domain.md` and the messages in `docs/spec/protocol.md`; where this file disagrees with the domain spec, the domain spec wins. The decisions are ADR-005 to ADR-008 in `docs/DECISIONS.md`.

## 1. Principles

- **One schema** for scoring and fan-out (ADR-008). Every key of quiz `Q` starts with `quiz:{Q}:`; the braces are a hash tag, so all keys of a quiz live in one Redis Cluster slot and one script may touch all of them.
- **Every write with more than one step is one Lua script** (ADR-005). Redis runs one script at a time, so no interleaving of nodes can see or leave a half-done write. Each script receives every key of the quiz as `KEYS`, in the fixed order of §2, built by one function in the Redis adapter; scripts never build key names themselves.
- **One clock.** Scripts read `TIME` (`now = sec × 1000 + floor(usec / 1000)`, integer ms) for every serve time, answer time, deadline check and reach time. The Python side never passes a time or points to a script. The in-memory store used by unit tests implements the same port with an injected clock (`clock: Callable[[], int]`, ms), which tests advance by hand.
- **The `seq` rule** (C2). Only a script that publishes a broadcast runs `INCR seq`: `publish_leaderboard` and `end_quiz`. `create_quiz`, `join`, `serve_question`, `score_answer` and `leave` never increment or publish; they read `seq` for `atSeq`.
- **The points formula exists once**, in `lua/lib/points.lua`; the loader puts it in front of `score_answer`. The Python twin is checked against it for every elapsed value from 0 to `T + 1`.

## 2. Keys

`Q` is the quiz ID. Hash fields that hold lists are JSON arrays (booleans as `0`/`1`). `uid` is the user ID and `i` a question index; `|` never occurs in a user ID, so it is a safe separator.

| # | Key | Type | Content |
|---|---|---|---|
| 1 | `quiz:{Q}:meta` | hash | `questionCount`, `timeLimitMs`, `windowMs`, `startMs`, `deadlineMs`, `questionIds` (JSON array, in serve order); `endedMs` and `endSeq` are absent until the quiz ends |
| 2 | `quiz:{Q}:key` | hash | the answer key: `i` → the correct choice index. Never leaves Redis except in that player's own `answer_result` |
| 3 | `quiz:{Q}:names` | hash | `uid` → display name (trimmed and normalized) |
| 4 | `quiz:{Q}:present` | hash | `uid` → the ID of the player's current connection. `HLEN` is `onlineCount` |
| 5 | `quiz:{Q}:totals` | hash | `uid` → total (integer) |
| 6 | `quiz:{Q}:board` | sorted set | member `uid`, score = the composite of §4. `ZCARD` is `playerCount` |
| 7 | `quiz:{Q}:serve` | hash | `uid` → `[cursor, serveMs, finished]`; `[-1, 0, 0]` after the first join |
| 8 | `quiz:{Q}:subs` | hash | `uid\|submissionId` → the stored reply `[questionIndex, choiceIndex, correctChoiceIndex, correct, late, pointsAwarded, score, atSeq]` |
| 9 | `quiz:{Q}:answered` | hash | `uid\|i` → `[choiceIndex, pointsAwarded, elapsedMs]`, `choiceIndex = -1` for a skip. The field's existence closes question `i` for that player |
| 10 | `quiz:{Q}:seq` | string | the broadcast counter, `0` at creation |
| 11 | `quiz:{Q}:dirty` | string | `1` while the standings or counts changed since the last `leaderboard` frame |
| 12 | `quiz:{Q}:tick` | string | the tick token: the publishing node's ID, set with `SET NX PX 200` |
| — | `quiz:{Q}:events` | pub/sub channel | the broadcast JSON (`leaderboard`, `quiz_ended`), one message per `seq` |

**TTL.** Keys 1–11 are the data keys. They share one TTL, `QUIZ_TTL_MS` = 24 h, and every write script ends by running `PEXPIRE` on all of them, so a quiz expires as a whole 24 h after its last write and is never half there. A key that a script creates gets its TTL in the same script. The tick token keeps its own 200 ms expiry and is never refreshed. The channel is not a key and has no TTL.

**Encoding notes.** Redis Lua's `cjson` encodes an empty table as `{}`, so an empty list is written as the literal `[]`. Lua turns numbers into strings with 14 significant digits, so a composite score is passed to `ZADD` as `string.format('%.0f', s)`, never as a bare number.

## 3. Scripts

All scripts return a flat array whose first element is a status (`ok` or an error code of protocol §7). "Deadline check" means: if `endedMs` is set or `now ≥ deadlineMs`, return `QUIZ_ENDED` plus `endSeq` (or `nil` when no `quiz_ended` was published yet), write nothing, and let the caller run `end_quiz` when `endSeq` is `nil` (§3.1). "Refresh" means the TTL step of §2.

| Script | Inputs (ARGV) | Checks, in order | Writes | Returns | `seq` |
|---|---|---|---|---|---|
| `create_quiz` | `questionIds` (JSON), answer key (JSON), `timeLimitMs`, `windowMs` | `meta` absent, else `INVALID_STATE`; `1 ≤ windowMs ≤ 3,600,000`, else `INVALID_MESSAGE` (keeps `reachedRelMs < 2^22`, §4); one answer per question, each `0…3` | `meta` (`startMs = now`, `deadlineMs = now + windowMs`), `key`, `seq = 0`; refresh | `ok, startMs, deadlineMs` | no |
| `join` | `uid`, `displayName`, `connId` | `meta` exists, else `QUIZ_NOT_FOUND`; deadline check | First join: `names`, `totals = 0`, `board` with total 0 and `reachedRelMs = now − startMs`, `serve = [-1, 0, 0]`. Every join: `present[uid] = connId`, `SET dirty 1`; refresh | `ok, atSeq, cursor, cursorOpen, finished, total, questionCount, timeLimitMs, quizRemainingMs, replacedConnId` | no |
| `serve_question` | `uid`, `i` | `meta` exists; deadline check; `serve[uid]` exists, else `NOT_JOINED`; the cases of domain §5.1 (`i = c` re-serves the stored `serveMs` and writes nothing; any other `i` than `c`, `c + 1`, `N` is `INVALID_STATE`) | If question `c` is open: `answered[uid\|c] = [-1, 0, e]` (skip, 0 points). Then `serve[uid] = [i, now, 0]`, or `[c, serveMs, 1]` for `i = N`; refresh. No `dirty`: a skip changes no standing | `ok, kind (question or finished), i, questionId, remainingMs, atSeq`; for `finished` also `total, rank, playerCount` | no |
| `score_answer` | `uid`, `i`, `choiceIndex`, `submissionId` | In domain §5.2 order: `subs[uid\|submissionId]` for the same `i` → the stored reply; for another `i` → `INVALID_MESSAGE`; deadline check; `serve[uid]` exists, else `NOT_JOINED`; `i > cursor` → `QUESTION_NOT_OPEN`; `answered[uid\|i]` exists → `ALREADY_ANSWERED` | `e = max(0, now − serveMs)`; points from `points.lua` (0 if wrong or `e > T`); `answered[uid\|i]`; if points > 0: `totals`, `board` with the new total and `reachedRelMs = max(0, now − startMs)`, `SET dirty 1`; if `i = N − 1`: `finished = 1`; `subs[uid\|submissionId]` = the reply with `atSeq = GET seq`; refresh | the stored reply | no |
| `publish_leaderboard` | node ID | `meta` exists; `endedMs` set or `now ≥ deadlineMs` → `ended, endSeq`; `tick` exists → `busy, PTTL tick`; `DEL dirty` returns 0 → `clean` | `SET tick <node> NX PX 200`, `INCR seq`, `PUBLISH events` the frame (`playerCount`, `onlineCount`, every row up to 200 players, else the top 50, `rebase: false`); refresh | `published, seq` | yes |
| `leave` | `uid`, `connId` | `present[uid] = connId`, else `stale` (a newer connection took over; nothing is written) | `HDEL present uid`; `SET dirty 1` while the quiz is open; refresh | `ok` or `stale` | no |
| `end_quiz` | reason (`deadline` or `host`) | `meta` exists; `endSeq` set → `ended, endSeq` (idempotent); reason `deadline` and `now < deadlineMs` → `not_due` | `endedMs = min(now, deadlineMs)`, `DEL dirty`, `INCR seq`, `HSET meta endSeq`, `PUBLISH events` the `quiz_ended` frame (top 50, `playerCount`, `you: null`); refresh | `ended, endSeq` | yes, once per quiz |

A reconnecting `join` writes no player state (names, totals, board, serve): only the presence and `dirty` change, so the reconnect shows in `onlineCount`. The leave of a disconnected player runs after the 10 s grace, so a reconnect within the grace changes nothing. The compare on `connId` stops a late grace timer on one node from marking offline a player who already reconnected on the other node. Closing the replaced socket (`replacedConnId`, close 4001) is the gateway's job, not the store's.

Reads that must agree with one `seq` (`snapshot`, `leaderboard_page`, `rank_update`) use one read-only script, `read_standings(offset, limit)`, which returns `seq`, `playerCount`, `onlineCount`, the status and the rows in one step.

### 3.1 Ending a quiz

The quiz is `ended` from the clock alone (domain §3.1): every write script refuses at `now ≥ deadlineMs` and writes nothing. Announcing the end is separate, and three paths run the idempotent `end_quiz`; whichever runs first publishes `quiz_ended`, the others get `ended, endSeq`:

1. **The first write after the deadline.** `join`, `serve_question`, `score_answer` and `publish_leaderboard` return `QUIZ_ENDED` (or `ended`) with `endSeq = nil`; the node then calls `end_quiz`. The refused script itself never increments `seq`.
2. **A deadline timer** on each node that has sockets for the quiz calls `end_quiz` at `deadlineMs`. It only makes the announcement prompt; correctness never depends on it.
3. **The mock host action** "end now" calls `end_quiz` with reason `host`.

After `endSeq` is set, `publish_leaderboard` never publishes again, so `quiz_ended` is the last broadcast.

## 4. The composite score

```
score        = (2^30 − total) × 2^22 + reachedRelMs
total        = 2^30 − floor(score / 2^22)
reachedRelMs = score mod 2^22
```

`ZRANGE` ascending gives the standings order: a higher total has a smaller first term; equal totals sort by `reachedRelMs`; equal scores sort by member, which Redis compares byte by byte, so ties go to the smaller `userId` in ASCII order. The Python standings code sorts with the same byte order.

Limits:

- `0 ≤ reachedRelMs < 2^22` (4,194,304 ms, about 69.9 min). Writes are refused at `now ≥ deadlineMs`, so `reachedRelMs < windowMs ≤ 3,600,000`; `create_quiz` rejects a larger window. A clock step back is clamped to 0.
- `0 ≤ total < 2^30`. The highest possible total is 150 per question, far below.
- The largest score is below `2^30 × 2^22 + 2^22 = 2^52 + 2^22 < 2^53`, so a double, a Redis sorted-set score and a Lua number all hold it exactly.

## 5. Coalescing across nodes without an owner

No node owns a quiz (ADR-006). Every node that holds at least one socket of quiz `Q` runs the same loop for it:

```
loop while the node has sockets of Q:
    status, value = publish_leaderboard(Q, nodeId)
    if status == "busy":    sleep(value + 1 ms)    # value = the token's PTTL
    elif status == "ended": call end_quiz if value is nil; stop
    else:                   sleep(200 ms)          # "published" or "clean"
```

The gate is atomic: inside one script the node sees no token, deletes `dirty` (and gets 1) and sets the token. So at most one frame per quiz leaves Redis per 200 ms, whatever the number of nodes, and two nodes ticking at the same instant cannot both publish or skip a `seq`. A node that loses the race sleeps until the token expires, so the next frame goes out as soon as one is allowed.

**Worst-case staleness against C5** (p99 below 500 ms from "answer accepted" to "leaderboard delivered"). `score_answer` sets `dirty` in the same script that accepts the answer. The frame that carries it leaves Redis after at most one token lifetime (200 ms) plus the node's timer lag, then costs one script run (well below 1 ms for 200 rows), one `PUBLISH` to each node, and one write per socket. With a few milliseconds of timer lag the store part is about 200 ms, which leaves about 300 ms for the per-socket writes and the network; the load runs measure the client-observed latency. Cost: each node calls the script about 5 times per second per active quiz.

**Failure cases.**

| Failure | What happens | Clients see |
|---|---|---|
| A node dies before or during its call | The script runs entirely or not at all. If it did not run, `dirty` stays set and another node with sockets of the quiz publishes within about 200 ms. If the dead node held the only sockets, its clients reconnect to the other node, whose first `join` starts the loop there; `dirty` is still set | At most one tick of extra delay; reconnecting clients resync |
| A node dies right after the script | The frame is already published to every node | Only its own clients miss it; they reconnect and resync |
| Two nodes tick at once | The second one sees the token: `busy` | Nothing |
| Redis restarts (AOF `everysec`) | Up to about 1 s of writes is lost, `seq` may go back, and the token, `dirty` or `endSeq` may be gone. The script cache is empty, so the adapter reloads scripts on `NOSCRIPT`. After the reconnect each node sets `dirty` for its quizzes and sends each client a snapshot. A lost `endSeq` makes `end_quiz` run again, because the deadline is still in `meta` | `seq < lastSeq` or `pong.seq < lastSeq` → resync (protocol §3). A lost answer is scored again when the client retries it. A second `quiz_ended` is applied like the first |
| A node's pub/sub connection drops | Frames published meanwhile do not reach that node; on resubscribe it sends each of its clients a snapshot | A `seq` gap or `pong.seq` → resync |
| Redis unreachable | Scripts fail before any write; requests get `UNAVAILABLE`; `/readyz` returns 503 | Retries after backoff (`next` and `answer` are safe to repeat) |

## 6. Tests that prove this design

- `api/tests/integration/test_seq.py::test_seq_has_no_gaps_under_concurrent_answers` (C2, the `seq` rule).
- `api/tests/integration/test_tick.py::test_two_nodes_publish_one_frame_per_tick` and `::test_join_and_leave_set_dirty_without_seq` (the gate and the token).
- `api/tests/integration/test_deadline.py::test_writes_after_deadline_write_nothing` and `::test_end_quiz_is_idempotent`.
- `api/tests/unit/test_composite.py::test_encode_decode_round_trip_at_limits` and `api/tests/integration/test_create_quiz.py::test_window_above_60_min_is_rejected`.
- `api/tests/integration/test_points_parity.py::test_lua_points_match_python_for_every_elapsed`.
