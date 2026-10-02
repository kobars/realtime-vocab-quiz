#!/usr/bin/env bash
# AI-ASSISTED: make demo: starts the full stack, a fresh 60-minute quiz and the bots that play it.
# Usage: scripts/demo.sh [bots]   (make demo BOTS=200; default 20), or scripts/demo.sh stop
# (make demo-stop). Needs Docker with Compose v2; make demo builds the images first.
set -euo pipefail
cd "$(dirname "$0")/.."

# The bots are the bot swarm of make load, in a container of this name.
bots_container=elsaquiz-demo-bots
if [[ "${1:-}" == stop ]]; then
  if docker rm --force "$bots_container" >/dev/null 2>&1; then
    echo "Removed the demo bots."
  else
    echo "No demo bots to remove."
  fi
  exit 0
fi

bots="${1:-20}"
if [[ ! "$bots" =~ ^[1-9][0-9]*$ ]]; then
  echo "BOTS must be a whole number above 0, not '$bots'" >&2
  exit 2
fi

# A fresh clone has no .env: write the two secrets that compose requires.
if [[ ! -f .env ]]; then
  secret() { od -An -tx1 -N24 /dev/urandom | tr -d ' \n'; }
  printf 'ADMIN_TOKEN=%s\nREDIS_PASSWORD=%s\n' "$(secret)" "$(secret)" > .env
  echo "Wrote .env with a new ADMIN_TOKEN and REDIS_PASSWORD."
fi

# Every bot connects from the bots container's one address, and each player it starts takes a
# session and a ticket from that address's budget (2 x PER_IP_CONN_CAP a minute). Unless the shell
# or .env sets the cap, raise it far above the bots, in steps of 1,000 so that a change of BOTS
# rarely restarts the API nodes.
if [[ -z "${PER_IP_CONN_CAP:-}" ]] && ! grep -q '^PER_IP_CONN_CAP=.' .env; then
  export PER_IP_CONN_CAP=$(( (bots * 5 / 1000 + 1) * 1000 ))
fi

docker compose --profile full up -d --wait --wait-timeout 120
seeded="$(docker compose --progress quiet run --rm -T seed)"
quiz_id="$(sed -n 's/^Quiz ID: *\([A-Z0-9-]*\).*/\1/p' <<<"$seeded")"
if [[ -z "$quiz_id" ]]; then
  echo "the seed printed no quiz ID: $seeded" >&2
  exit 1
fi
echo "Building the bots image and starting $bots bots..."
# The API allows the Origin of QUIZ_PORT, which compose reads from the shell, else from .env.
port="${QUIZ_PORT:-$(sed -n 's/^QUIZ_PORT=\([0-9]*\).*/\1/p' .env)}"
# As make load: the host user owns the result file that the bots write when the quiz ends.
mkdir -p load/results
docker rm --force "$bots_container" >/dev/null 2>&1 || true
docker compose --progress quiet --profile load run --detach --build --name "$bots_container" \
  --user "$(id -u):$(id -g)" load --quiz-ids "$quiz_id" --bots "$bots" --duration 3600 \
  --origin "http://localhost:${port:-8080}" --label demo >/dev/null

echo
echo "$seeded"
echo "Bots:       $bots playing $quiz_id until its window ends (make demo-stop stops them)."
echo "Open the player URL in two browser windows, join, and watch the leaderboard move."
