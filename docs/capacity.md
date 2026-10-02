# Capacity estimate

[System design](../DESIGN.md#9-performance-and-capacity)

<!-- AI-ASSISTED-BEGIN: capacity estimate drafted with Claude Code from api/src/quiz/config.py, the contracts, docs/spec/ and the ADRs; the frame sizes were computed by encoding sample frames in compact JSON; the memory per socket is computed from the load runs in load/results/. -->

Every number below is either an input with its source, a value computed from those inputs (the
formula is given), or a measurement from a load-run file. The measured results are summed up in
[DESIGN §9](../DESIGN.md#measured-results), and given in full in [load/README.md](../load/README.md#measured-runs).

**Assumptions.**

| # | Assumption | Value | Source |
|---|---|---|---|
| A1 | Quiz shape | 10 questions, 4 choices, `T` = 20 s each | ADR-002; [domain spec](spec/domain.md) |
| A2 | Coalescing tick | a poll every 200 ms by each node that holds a socket of the quiz; a frame only when the quiz is dirty | `tick_ms` in `api/src/quiz/config.py` |
| A3 | Rows per `leaderboard` frame | every player up to 200 (`FULL_LIST_MAX`), else the top 50 (`TOP_N`) | `api/src/quiz/contracts/messages.py` |
| A4 | Socket caps | 10,000 per process (`MAX_CONNECTIONS`), 50 per client address | `api/src/quiz/config.py` |
| A5 | Send buffer per socket | soft 64 KiB (conflate leaderboards), hard 256 KiB (close 1013) | `api/src/quiz/config.py` |
| A6 | Inbound limits | 16 KiB per message, checked before parsing; 64 KiB per transport frame; 20 msg/s, burst 40 | `api/src/quiz/contracts/codec.py`, `api/src/quiz/adapters/ws/heartbeat.py`, `api/src/quiz/config.py` |
| A7 | Messages per connection per tick | at most 2: one `leaderboard` and, above 200 players, one `rank_update` | ADR-004 |
| A8 | `userId` length | 18 characters (`u_` and 16 base64url characters) | `api/src/quiz/adapters/mock_auth/tokens.py` |
| A9 | `displayName` length | 12 characters typical (our assumption), 32 characters at most (not bytes) | our assumption; `api/src/quiz/contracts/messages.py` |
| A10 | Highest total | 1,500 (10 × 150), so a score has at most 4 digits | the scoring rule (ADR-002) |
| A11 | Player pace | one answer per player every 5 s (reading plus thinking) | our assumption; the load bot's think time `think_s` (`load/player.py`) |
| A12 | API nodes | 2, each one Python process on one event loop | ADR-001; ADR-003 |
| A13 | Quiz subscriptions per node | active quizzes per node <= `REDIS_MAX_CONNECTIONS` (default 100): each quiz a node serves holds one connection of the node's subscription pool, which has that size | `connect_redis` in `api/src/quiz/main.py`; `redis_max_connections` in `api/src/quiz/config.py` |

**Leaderboard frame size** (computed). One row is
`{"rank":123,"userId":"u_…","displayName":"…","score":1234}`: 84 bytes with A8, a 12-character
name and A10. A frame is about `100 + 85 × rows` bytes. Encoding sample frames gives:

| Frame | Rows | Bytes, 12-character names | Bytes, 32 ASCII characters |
|---|---|---|---|
| 10 players | 10 | 932 | 1,132 |
| 200 players (largest full frame) | 200 | 16,995 | 20,995 |
| Above 200 players (top 50) | 50 | 4,296 | 5,296 |

The cap of A9 counts characters, not bytes, and allows any text: the JSON writes non-ASCII
characters as raw UTF-8 (up to 4 bytes each) and control characters as 6-byte `\u00XX` escapes.
So a 200-row frame of 32-character names is at most about 40 KB with 4-byte characters
(`20,995 + 200 × 32 × 3`) and about 53 KB with control characters (`20,995 + 200 × 32 × 5`).
The rest of this page uses the 12-character column.

**Per-connection memory** (computed, a partial estimate). A healthy socket's send queue is
empty between ticks; one queued 200-row frame is 17 KB. The soft limit (A5) holds
`64 KiB / 16,995 B` ≈ 3.9 full frames, so a client about 0.8 s behind at 5 frames/s gets
conflated frames. A slow or abusive socket can fill these buffers in the process:

| Buffer | Bound | Source |
|---|---|---|
| Send queue (`Sender.buffered`, the frame in flight included) | 256 KiB, then close 1013 | A5 |
| Transport write buffer | 64 KiB high-water mark, plus the one frame that crossed it; WebSocket pongs to client pings skip that wait, so a client that floods pings and reads nothing grows it further | the event loop's default; uvicorn waits for `resume_writing` before the next message |
| Inbound messages parsed from one read | 250 KiB: uvloop reads up to 256,000 bytes at a time, and uvicorn queues every complete frame of that read before reading pauses | uvloop's read size (uvicorn uses uvloop when it is installed); uvicorn's WebSocket protocol |
| Partial inbound frame in the parser | 64 KiB (A6) | A6 |

Their sum is about 634 KiB per socket plus one outbound frame, or 10,000 × 634 KiB ≈ 6.0 GiB
at the 10,000-socket cap if every client is slow and floods at once. Python's object overhead,
the decoded copies of queued messages and the kernel's socket buffers come on top, so this is
not an upper bound. The steady-state memory per socket (RSS divided by sockets), at the end of
this page, comes from the [measured runs](../load/README.md#measured-runs).

**Connections per node** (computed). The cap is 10,000 sockets per process (A4); two nodes
hold 20,000. In one hot quiz above 200 players, each socket gets at most 5 frames per second
(A2), so 10,000 sockets need 50,000 frame writes per second, which is
`50,000 × 4,296 B` ≈ 215 MB/s of egress per node, plus at most one `rank_update` per socket
per tick (A7). All of it runs on one core (A12), so CPU or the network is likely to set the
practical number below the cap: 215 MB/s is about 1.7 Gbit/s before framing, above a 1 Gbit/s
link. Measured ([load/README.md](../load/README.md#measured-runs)): one node held 2,500 sockets of one hot quiz within C5 (p99
364 ms) at 63 % of its core on average, peaking at 89 %, and each node of the two-node run held
about 2,500 at 71 to 73 %, peaking just above a full core (p99 409 ms). So the practical number per node in one hot quiz is 2,500
measured, and by extrapolating the CPU about 3,500 at most (an estimate, not measured), against
the computed cap of 10,000: CPU, not memory, sets it. Across many quizzes the first ceiling is
A13: with the default pool a node serves at most 100 quizzes at once, so the [500-quiz run](../DESIGN.md#measured-results)
set `REDIS_MAX_CONNECTIONS` to 1,000 (`load/compose.bank.yaml`). Past that limit a node refuses
a `join` to one more quiz with `UNAVAILABLE` and close 1013, and counts it in
`feed_subscribe_failures_total{reason="limit"}`; the client reconnects after 5 s plus its
backoff, through the load balancer, which may reach the other node. A join holds its
subscription while its store write runs, so concurrent joins never pass the limit together. The
quizzes the node already follows are not affected, and a join to an ended quiz still gets the
final standings, which need no subscription. It never accepts a player that it could not send
live updates to.

**When one node is lost** (computed from the measured numbers). The availability target ([DESIGN §8](../DESIGN.md#8-non-functional-requirements))
moves every client of a stopped node to the other one. One hot quiz keeps C5 through that only
while all its sockets fit on one node: about 2,500 measured, about 3,500 estimated. The 5,000
sockets that the two nodes held within C5 do not: after one node stops, the other would serve
twice its measured load and is expected to miss C5 until enough players leave. So the
population that survives losing a node is about 2,500 to 3,500 sockets in one hot quiz, not the
5,000 of the two-node run; no load run has stopped a node under load yet.

**Messages per question** (computed). For a quiz of `N` players, per player and question:

- in: 2 (`next`, then `answer`); out: 2 unicasts (`question`, `answer_result`);
- broadcast: at most 5 `leaderboard` frames per second per quiz (A2), so at most
  `T / 200 ms` = 100 frames in one 20 s question window, each sent to all `N` sockets: at most
  `100 × N` frame writes per quiz per question window;
- above 200 players, at most one `rank_update` per socket per tick (A7).

The tick publishes only after a change: an answer that scores, a join or a leave sets `dirty`
(`score_answer.lua`, `join.lua`, `leave.lua`). Counting answers only, with A11 they arrive at
`N / 5` per second; if a share `p` of them scores, a 200 ms tick sees no change with probability `e^(−pN/25)` (Poisson arrivals): 1.8 % at
`N` = 100 when every answer scores, 37 % when a quarter does. From about `100 / p` players on,
nearly every tick publishes.

| Players in one quiz | Frame | Frame writes per second (`5 × N`) | Egress per second (`5 × N × bytes`) | Answers per second (`N / 5`) |
|---|---|---|---|---|
| 10 | full, 932 B | 50 (if every tick has a change) | 47 KB | 2 |
| 200 | full, 16,995 B | 1,000 | 17.0 MB | 40 |
| 1,000 | top 50, 4,296 B | 5,000 | 21.5 MB | 200 |
| 5,000 | top 50, 4,296 B | 25,000 | 107.4 MB | 1,000 |

Redis load per second (computed, a subtotal of the main calls):

- `N / 5` scoring scripts and `N / 5` serving scripts for `next`;
- 5 tick-script calls per active quiz for every node that holds a socket of the quiz (ADR-006,
  [DESIGN §10](../DESIGN.md#10-scalability-and-trade-offs)); above 200 players each call that publishes also runs one `ZRANK` for each scorer since
  the last frame and one `HGET` for each of those outside the top 50, and the frames cost one
  `PUBLISH` per tick per quiz;
- one `GET` per `ping` for `pong.seq`: sockets / 25 s, 400 per second for 10,000 sockets
  (ADR-004);
- above 200 players, one `read_standings` per 1,000 local players per node per quiz per second
  for players whose rank only shifted ([redis spec](spec/redis.md), "Reads at one `seq`").

5,000 players in one quiz on two nodes cost 1,000 + 1,000 + 10 + 6 script calls (3 reads of up to 1,000 players per node) and 200 `GET`s
per second, plus up to 2,000 calls inside the tick script at A11's pace. Not counted: snapshots (1 to 3
script calls each; concurrent misses of the cached standings share one read), the presence renew every 3 s per node and quiz, joins and reconnects, and
clients that send faster than A11 (up to 20 messages per second per socket, A6).

**Steady-state memory per socket** = `(peak RSS − idle RSS) / sockets on the node`, with the
idle RSS taken before the run (in the `-nodes.json` files): 1,000 sockets
`(121.0 − 56.5) MiB / 1,000` = 66 KiB; 2,500 sockets `(196.7 − 55.6) MiB / 2,500` = 58 KiB; the
two-node hot quiz 60 and 61 KiB; 500 quizzes 76 KiB on each node (each served quiz adds its own
state and a Redis subscription). The two-node figures assume an even split of 2,500 sockets per
node: nginx balances requests round-robin and no result file counts sockets per node, but the
nodes' near-equal CPU and memory growth agree with it. That is about a tenth of the 634 KiB per socket that the buffer bounds
above allow a slow, flooding client, so 10,000 healthy sockets need about 0.5 to 0.8 GiB per
node.

<!-- AI-ASSISTED-END -->
