# Load: the bot swarm

`load/bots.py` fills quizzes with bots and measures what a player sees. Each of `--bots` slots
plays one player at a time: a fresh mock session (`POST /sessions`), a ticket, the socket,
`join`, every question with a think time, then the next cohort's player takes the slot, so the
bots keep answering for the whole run. Slots start spread over `--ramp` and over the quizzes
round-robin.

## What it measures

| Sample | From | To |
|---|---|---|
| answer | the bot sends `answer` | its `answer_result` arrives |
| leaderboard | an `answer_result` with points (the server accepted it) | the first `leaderboard` entry or `rank_update` that shows the new total |

It prints p50, p95 and p99 in milliseconds with the number of samples, the missing samples (the
socket dropped or the run ended first) and the timed-out ones (slower than `--timeout-ms`), and
writes the same, with the options, message rates and counters (errors, reconnects, seq gaps), to
`load/results/<UTC time>-<label>.json`. Each process reports its own CPU and peak RSS; a run where
any swarm process used more than 80% of a core is marked invalid and exits with status 1, because
then the swarm, not the server, sets the latency.

Bots behave like the web client: every bot sends an `Origin` header, gets a fresh ticket before
each connect, reconnects with full-jitter backoff (none after close 1000, 1008 or 4001; 5 s more
after 1013), rejoins, sends one `resync`, resends an open answer with the same `submissionId`, and
resyncs after a `seq` gap. A bot learns the correct choice of each question from the
`answer_result` of the first bot that answers it; `--accuracy` applies from then on.

## Run it

In the compose network (the `load` profile, `nofile` 65536), against nginx of the full stack:

```sh
make load LOAD_ARGS="--quizzes 3 --bots 1000 --duration 180 --ramp 30 --procs 4"
```

`LOAD_URL` sets the HTTP base (default `http://nginx:8080/api`; the socket is `/ws` on the same
host). Against one API node on the host, for example `uvicorn` on port 8001:

```sh
LOAD_URL=http://host.docker.internal:8001 make load LOAD_ARGS="--bots 200 --admin-token …"
uv run --project api python load/bots.py --url http://127.0.0.1:8001 --bots 50 --duration 30
```

The API caps sockets per client address at 50 (`PER_IP_CONN_CAP`); raise it on the API for runs
with more bots. `--admin-token` creates the quizzes first through the mock admin endpoint
(`ADMIN_MOCK=1` on the API); without it the quizzes must exist.

| Option | Default | Meaning |
|---|---|---|
| `--url` | `$LOAD_URL` or `http://localhost:8080/api` | HTTP base of the API |
| `--origin` | `http://localhost:8080` | the `Origin` header |
| `--quiz-ids`, `--quizzes` | the three seeded quizzes, 1 | spread the bots over the first N IDs |
| `--bots` | 10 | bots playing at the same time |
| `--accuracy` | 0.7 | share of correct answers |
| `--think-ms` | 2000 | mean think time before each answer (uniform, ±50%) |
| `--duration`, `--ramp` | 60, 10 | seconds of answering after a ramp of this many seconds |
| `--procs` | 1 | processes to spread the bots over |
| `--timeout-ms` | 5000 | a sample slower than this counts as timed out |
| `--label` | `run` | name part of the result file |
