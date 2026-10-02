#!/usr/bin/env bash
# AI-ASSISTED: make demo: starts the full stack, a fresh 60-minute quiz and the bots that play it.
# Usage: scripts/demo.sh [bots]   (make demo BOTS=200; default 20). Needs Docker with Compose v2;
# make demo builds the images first.
set -euo pipefail
cd "$(dirname "$0")/.."

bots="${1:-20}"
if [[ ! "$bots" =~ ^[1-9][0-9]*$ ]]; then
  echo "BOTS must be a whole number above 0, not '$bots'" >&2
  exit 2
fi

# A fresh clone has no .env: write the two secrets that compose requires.
if [[ ! -f .env ]]; then
  secret() { od -An -tx1 -N24 /dev/urandom | tr -d ' \n'; }
  (umask 077 && printf 'ADMIN_TOKEN=%s\nREDIS_PASSWORD=%s\n' "$(secret)" "$(secret)" > .env)
  echo "Wrote .env with a new ADMIN_TOKEN and REDIS_PASSWORD."
fi

# Every bot connects from the bots container's one address, and each player it starts takes a
# session and a ticket from that address's budget (2 x PER_IP_CONN_CAP a minute). Unless the shell
# or .env sets the cap, raise it far above the bots. A changed cap recreates the API nodes and
# drops every socket, so it stays at 10,000 up to 1,799 bots and grows in steps of 1,000 above.
if [[ -z "${PER_IP_CONN_CAP:-}" ]] && ! grep -q '^PER_IP_CONN_CAP=.' .env; then
  cap=$(( (bots * 5 / 1000 + 1) * 1000 ))
  export PER_IP_CONN_CAP=$(( cap > 10000 ? cap : 10000 ))
fi

# The bots image first: the quiz's window starts when the seed creates it.
echo "Building the bots image..."
docker compose --progress quiet build bots
docker compose --profile full up -d --wait --wait-timeout 120
seeded="$(docker compose --progress quiet run --rm -T seed)"
quiz_id="$(sed -n 's/^Quiz ID: *\([A-Z0-9-]*\).*/\1/p' <<<"$seeded")"
if [[ -z "$quiz_id" ]]; then
  echo "the seed printed no quiz ID: $seeded" >&2
  exit 1
fi
echo "Starting $bots bots..."
DEMO_QUIZ_ID="$quiz_id" DEMO_BOTS="$bots" docker compose --progress quiet up -d --no-build bots

echo
echo "$seeded"
echo "Bots:       $bots playing $quiz_id until its window ends (make demo-stop stops them)."
echo "Open the player URL in two browser windows, join, and watch the leaderboard move."
echo "End it with the command above: both windows then show the final podium."
