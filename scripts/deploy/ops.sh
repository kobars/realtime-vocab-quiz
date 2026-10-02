#!/usr/bin/env bash
# AI-ASSISTED: the public host's update with rollback, backup and restore (make prod-update,
# make prod-backup, make prod-restore; docs/operations.md, "Deploy to a VM").
# Usage: scripts/deploy/ops.sh update | backup [FILE] | restore FILE   (as root, on the VM)
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=install.sh
. "$(dirname "$0")/install.sh"
cd "$(dirname "$0")/../.."

PROD_COMPOSE=(docker compose -f compose.yaml -f compose.prod.yaml)

ready() { wait_ready "$(env_value DOMAIN .env)" "$(env_value TLS_ISSUER .env)"; }

# Pulls the branch and restarts on it; when the stack does not get ready, goes back to the commit
# that ran before and restarts on that.
update() {
  local before after
  before=$(git rev-parse HEAD)
  git pull --ff-only || die "git pull --ff-only failed; nothing changed, the stack still runs $before"
  after=$(git rev-parse HEAD)
  if make prod-up && ready; then
    log "Updated $before -> $after; the stack is ready"
    return 0
  fi
  printf 'error: %s did not get ready; rolling back to %s\n' "$after" "$before" >&2
  git reset --keep "$before" || die "could not check out $before; the checkout has local changes"
  if make prod-up && ready; then
    die "update to $after failed; rolled back to $before, which is ready again"
  fi
  die "update to $after failed, and $before is not ready either; see make prod-logs"
}

info_persistence() {
  "${PROD_COMPOSE[@]}" exec -T stack-redis redis-cli INFO persistence | tr -d '\r' | sed -n "s/^$1://p"
}

# BGSAVE writes the snapshot to a temporary file and renames it, so the copy is a whole one.
backup() {
  local out=${1:-backups/quiz-$(date -u +%Y%m%dT%H%M%SZ).tar.gz} saves tries=0
  [[ -f .env ]] || die "no .env in $PWD; run this in the install folder"
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  log "Snapshotting Redis"
  saves=$(info_persistence rdb_saves)
  "${PROD_COMPOSE[@]}" exec -T stack-redis redis-cli BGSAVE >/dev/null || true # one may be running
  until [[ $(info_persistence rdb_bgsave_in_progress) == 0 && $(info_persistence rdb_saves) -gt $saves ]]; do
    ((++tries < 300)) || die "the Redis snapshot did not finish in 5 minutes"
    sleep 1
  done
  [[ $(info_persistence rdb_last_bgsave_status) == ok ]] || die "the Redis snapshot failed; see make prod-logs"
  mkdir "$tmp/redis"
  "${PROD_COMPOSE[@]}" cp stack-redis:/data/dump.rdb "$tmp/redis/dump.rdb"
  log "Copying the certificates"
  "${PROD_COMPOSE[@]}" cp caddy:/data "$tmp/caddy"
  cp -p .env "$tmp/.env"
  mkdir -p "$(dirname "$out")"
  (umask 077 && tar -czf "$out" -C "$tmp" .env redis caddy)
  log "Wrote $out. It holds .env's secrets and the TLS private keys: keep it private and off this VM."
}

# With AOF on, Redis starts from the AOF alone and would ignore a dump.rdb. So a Redis without AOF
# loads the snapshot, writes it out as a new AOF, and stops.
REDIS_RESTORE='set -eu
unset REDISCLI_AUTH
rm -rf /data/appendonlydir /data/dump.rdb
cp /backup/dump.rdb /data/dump.rdb
redis-server --loglevel warning --appendonly no --save "" --port 0 --unixsocket /tmp/restore.sock --dir /data &
cli() { redis-cli -s /tmp/restore.sock "$@"; }
until cli PING >/dev/null 2>&1; do sleep 0.2; done
cli CONFIG SET appendonly yes >/dev/null
until cli INFO persistence | grep -q "^aof_enabled:1" && cli INFO persistence | grep -q "^aof_rewrite_in_progress:0" && cli INFO persistence | grep -q "^aof_rewrite_scheduled:0"; do sleep 0.2; done
cli INFO persistence | grep -q "^aof_last_bgrewrite_status:ok"
cli SHUTDOWN
wait
chown -R redis:redis /data'

# Root in the service's own image, with only the capabilities a copy and a chown need.
restore_volume() {
  local service=$1 from=$2 script=$3
  "${PROD_COMPOSE[@]}" run --rm --no-deps --user 0 --cap-add CHOWN --cap-add DAC_OVERRIDE \
    --cap-add FOWNER -v "$from:/backup:ro" --entrypoint sh "$service" -c "$script"
}

restore() {
  local file=${1:?usage: ops.sh restore FILE}
  [[ -f $file ]] || die "no backup file $file"
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  tar -xzf "$file" -C "$tmp" .env redis/dump.rdb caddy || die "$file is not a backup from make prod-backup"
  log "Stopping the stack"
  "${PROD_COMPOSE[@]}" --profile '*' down
  if [[ -f .env ]]; then cp -p .env .env.before-restore; fi
  (umask 077 && cp "$tmp/.env" .env)
  log "Restoring the Redis data"
  restore_volume stack-redis "$tmp/redis" "$REDIS_RESTORE"
  log "Restoring the certificates"
  restore_volume caddy "$tmp/caddy" 'rm -rf /data/caddy && cp -a /backup/. /data/ && chown -R 65532:65532 /data'
  make prod-up
  ready || die "restored, but https://$(env_value DOMAIN .env)/api/readyz is not ready; see make prod-logs"
  log "Restored $file; the previous .env is in .env.before-restore"
}

case ${1:-} in
  update) update ;;
  backup) backup "${2:-}" ;;
  restore) restore "${2:-}" ;;
  *) die "usage: ops.sh update | backup [FILE] | restore FILE" ;;
esac
