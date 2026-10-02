# Load: the bot swarm

<!-- AI-ASSISTED: written with Claude Code from load/bots.py and the measured runs in load/results/. -->

`load/bots.py` fills quizzes with bots and measures what a player sees. Each of `--bots` slots
plays one player at a time: a fresh mock session (`POST /sessions`), a ticket, the socket,
`join`, every question with a think time, then the next cohort's player takes the slot, so the
bots keep answering for the whole run (or until each slot has played `--cohorts` players). Slots start spread over `--ramp` and over the quizzes
round-robin.

## What it measures

| Sample | From | To |
|---|---|---|
| answer | the bot sends `answer` | its `answer_result` arrives |
| leaderboard | the bot receives an `answer_result` with points (the server accepted it) | the first `leaderboard` entry or `rank_update` that shows the new total |

The leaderboard sample is the latency target of the design: 99% of updates delivered below
500 ms from "answer accepted" to "leaderboard delivered". The interval starts when the client
receives `answer_result`, the first moment it knows the answer was accepted, so it leaves out the
reply's own trip (the answer sample above). The swarm prints p50, p95 and p99 in milliseconds
with the number of samples, the missing samples (the socket dropped or the run ended first) and
the timed-out ones (slower than `--timeout-ms`), and writes the same, with the options, message
rates and counters (errors, reconnects, seq gaps), to `load/results/<UTC time>-<label>.json`.
Each latency block there has a `completion` ratio: samples / (samples + missing + timed out).

Two verdicts close the run. `valid` judges the measurement: each process reports its own CPU and
peak RSS, and a run where any swarm process used more than 80% of a core is invalid, because then
the swarm, not the server, sets the latency. `slo_met` judges the server: `slo_within` is the
share of leaderboard updates delivered below 500 ms, where a missing or timed-out sample counts
as a miss, so a run cannot pass on the samples that arrived alone, and a total that a frame
showed before its `answer_result` (`board_first`) counts as on time. An answer whose own
`answer_result` was missing or timed out opened no leaderboard wait, so nothing shows its update
was on time: it counts as a miss too, even if it was a wrong answer that changed nothing.
`slo_met` is true when that share, unrounded, is at least 99%; a run with no leaderboard sample at
all is invalid (`no leaderboard samples`), since it measured nothing. The swarm exits with status
1 unless the run is valid and meets the SLO.

Bots behave like the web client: every bot sends an `Origin` header, gets a fresh ticket before
each connect, reconnects with full-jitter backoff (none after close 1000, 1008 or 4001; 5 s more
after 1013), rejoins, sends one `resync`, resends an open answer with the same `submissionId`, and
resyncs after a `seq` gap. Like the web client, a bot holds a frame that arrives after a gap or
during a resync until the snapshot, and times the leaderboard when it applies a frame that shows
its new total, not when the frame arrives. A bot learns the correct choice of each question from the
`answer_result` of the first bot that answers it; `--accuracy` applies from then on.

## Run it

`make load` runs the swarm as a container on the stack network (the `load` Compose profile,
`nofile` 65536, one descriptor per bot socket) against nginx of the running full stack, and
passes `LOAD_ARGS` to it. All bots come from one address, and the API caps sockets per client
address at 50, so set `PER_IP_CONN_CAP` in `.env` above the number of bots before the stack
starts. `--admin-token` creates the quizzes first through the mock admin endpoint; without it
the quizzes must exist and be open.

```sh
echo PER_IP_CONN_CAP=20000 >> .env
make build && docker compose --profile full up -d --wait
set -a; . ./.env; set +a
make load LOAD_ARGS="--quiz-ids VOCAB-42 --bots 1000 --procs 4 --duration 180 --ramp 30 --think-ms 5000 --admin-token $ADMIN_TOKEN --label hot"
```

`LOAD_URL` sets the HTTP base (default `http://nginx:8080/api`; the socket is `/ws` on the same
host). Outside Docker, from the host against the same stack through nginx (the default `--url`):
`uv run --project api python load/bots.py --admin-token "$ADMIN_TOKEN" --bots 50 --duration 30`.

| Option | Default | Meaning |
|---|---|---|
| `--url` | `$LOAD_URL` or `http://localhost:8080/api` | HTTP base of the API |
| `--origin` | `http://localhost:8080` | the `Origin` header; it must be in the API's `ALLOWED_ORIGINS` |
| `--quiz-ids`, `--quizzes` | the three seeded quizzes, 1 | spread the bots over the first N IDs |
| `--bots` | 10 | bots playing at the same time |
| `--cohorts` | 0 | players each slot plays in turn; 0 plays until the run ends. `make demo` passes 1, so its quiz holds one player per bot |
| `--accuracy` | 0.7 | share of correct answers |
| `--think-ms` | 2000 | mean think time before each answer (uniform, ±50%) |
| `--duration`, `--ramp` | 60, 10 | seconds of answering after a ramp of this many seconds |
| `--procs` | 1 | processes to spread the bots over |
| `--timeout-ms` | 5000 | a sample slower than this counts as timed out; at least 500, the SLO, so a timed-out sample is a real miss |
| `--label` | `run` | name part of the result file |

**API node CPU and memory.** Start `load/node_stats.py` on the host next to `make load`, with the
swarm's ramp (plus a few seconds for the image build) and a little less than its duration. It
samples `docker stats` of the API nodes every 5 s and writes each node's mean and peak CPU
(percent of one core) and its idle and peak memory to `load/results/<UTC time>-<label>-nodes.json`:

```sh
uv run --project api python load/node_stats.py --ramp 32 --duration 175 --label hot
```

**One node.** Stop the other node before the run (`docker compose stop api-2`); nginx drops its
name within 5 s and sends every bot to `api-1`. Pass `--containers elsaquiz-api-1-1` to
`load/node_stats.py`.

**Many quizzes.** The seeded bank holds three quizzes. `load/gen_bank.py` writes `--quizzes` quiz
files (`LOAD-001` and on, each with the `VOCAB-42` questions) into `load/bank/` and prints their
IDs; `load/compose.bank.yaml` mounts that folder over both nodes' bank and raises
`REDIS_MAX_CONNECTIONS`, because each quiz a node serves holds one connection of its subscription
pool, which has that size (the default of 100 would refuse the 101st quiz on a node). The nodes
read the bank only at start, so `--force-recreate` restarts them on the new files:

```sh
IDS=$(uv run --project api python load/gen_bank.py --quizzes 500)
export COMPOSE_FILE=compose.yaml:load/compose.bank.yaml
docker compose --profile full up -d --wait --force-recreate
make load LOAD_ARGS="--quiz-ids $IDS --quizzes 500 --bots 5000 --procs 10 --duration 180 --ramp 30 --think-ms 5000 --admin-token $ADMIN_TOKEN --label many"
```

## Measured runs

Machine: an Apple M4 Pro laptop (12 cores, 24 GB) running Docker Desktop 29.8.1 with a Linux VM
of 12 CPUs and 7.7 GiB. Everything shares that VM: nginx, the API nodes (one Python process
each), Redis and the swarm. The stack is the `full` profile with `PER_IP_CONN_CAP=20000`; each
run starts on a flushed Redis and restarted nodes, built from commit `145284ba`, which adds the
Redis command timeouts (`REDIS_SOCKET_TIMEOUT_MS`, default 5 s), and the swarm is the one
described above. Every run: a 30 s ramp, then 180 s of answering (`--duration 180 --ramp 30`),
`--think-ms 5000` (one answer per player about every 5 s, the pace the capacity estimate
assumes), `--accuracy 0.7`.

Later commits on `main` postdate these runs but leave the answer → leaderboard path alone: since
`145284ba` no commit has changed the serve, score, tick, join or read scripts, the fan-out
(`api/src/quiz/fanout/`), the WebSocket adapter (`api/src/quiz/adapters/ws/`), the nginx config
or the swarm. The changes beside that path are the display-name rule on `join`, a split of the
parser's protocol-version check (a valid message passes the same checks) and the self-service
hosting routes and scripts. `git log 145284ba..main -- <path>` lists them.

| Run | Quizzes | Connections | Msg/s to / from bots (ramp included) | Leaderboard p50 / p95 / p99 ms | Answer p50 / p95 / p99 ms | Missing samples | Leaderboard completion | Below 500 ms (`slo_met`) | API node CPU % mean (peak) | Swarm CPU % per process (procs) | API node RSS MB idle → peak | Swarm RSS MB per process |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| One hot quiz, 1 node | 1 | 1,000 | 5,942 / 455 | 116.5 / 195.9 / 205.4 | 0.6 / 20.1 / 41.7 | 0 | 1 | 100.00% (true) | 31.2 (49.7) | 11.0 (4) | 57 → 121 | 69 |
| One hot quiz, 1 node | 1 | 2,500 | 13,989 / 1,133 | 128.0 / 218.5 / 363.9 | 1.0 / 74.0 / 243.4 | 0 | 1 | 99.99% (true) | 62.7 (89.1) | 16.7 (6) | 56 → 197 | 77 |
| One hot quiz, 2 nodes | 1 | 5,000 | 29,463 / 2,253 | 119.9 / 199.4 / 408.6 | 4.9 / 150.3 / 345.6 | 0 | 1 | 99.94% (true) | 72.8 (109.1), 71.0 (109.5) | 24.9 (10) | 56 → 202, 59 → 208 | 89 |
| Many quizzes, 2 nodes | 500 × 10 players | 5,000 | 8,802 / 2,242 | 89.7 / 192.6 / 384.4 | 2.2 / 113.7 / 438.3 | 0 | 1 | 99.32% (true) | 77.1 (98.2), 75.0 (109.0) | 9.9 (10) | 58 → 242, 59 → 244 | 90 |

Result files, in the order of the table (the swarm's, then the nodes'):

- `load/results/20261002T070755572662Z-hot-1node-1000.json`, `load/results/20261002T070747368871Z-hot-1node-1000-nodes.json`
- `load/results/20261002T071712779035Z-hot-1node-2500.json`, `load/results/20261002T071702549732Z-hot-1node-2500-nodes.json`
- `load/results/20261002T072125990027Z-hot-2node-5000.json`, `load/results/20261002T072118251231Z-hot-2node-5000-nodes.json`
- `load/results/20261002T072542653053Z-many-2node-500x10.json`, `load/results/20261002T072534161765Z-many-2node-500x10-nodes.json`

Every run is valid: no swarm process reached 80% of a core, and no run had a reconnect, a
failed open, a timed-out or a missing sample, so every latency block has a completion of 1, and
every run meets the SLO (`slo_met: true`). The two-node hot quiz counted 1 `seq` gap and the
many-quizzes run 4, each closed by a resync; the many-quizzes run also got one `RATE_LIMITED`
error reply. The other runs had neither.

**Verdict: the target is met.** The leaderboard p99 stays below 500 ms in every run, at 409 ms
in the worst (one hot quiz of 5,000 players on two nodes). The p50 near 120 ms in one hot quiz is
the coalescing tick: a total waits on average half of the 200 ms tick before a frame carries it.
The tail grows with CPU: at 2,500 sockets in one hot quiz a node spends about 63% of its one core
on average and peaks at 89%, and the p99 moves from about 205 ms (1,000 sockets) to 364 ms. Two
nodes hold twice the sockets of one at about the same latency (p99 409 ms), so the hot quiz scales
out, though each node of the two-node run works harder (about 72% of a core on average, with
peaks above a full core) than the single node at the same 2,500 sockets. The many-quizzes run has
the least margin by share: 99.32% of updates arrive below 500 ms, against the 99% target. Repeats
vary on this shared VM: three earlier sets of the same four runs, each on the code before a later
server change, measured p99s of 202, 385, 419 and 238 ms; of 205, 409, 436 and 313 ms; and of
206, 359, 379 and 233 ms, all within the target too. The headroom is small: from the CPU at 2,500
sockets, a node above about 3,500 sockets in one hot quiz nears a full core on average and is
likely to miss the target (an estimate, not measured), so the next step for more players per quiz
is more nodes, or fewer bytes per frame (the top-50 frame dominates the egress).
