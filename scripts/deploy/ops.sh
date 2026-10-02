#!/usr/bin/env bash
# AI-ASSISTED: the public host's start, update with rollback, backup and restore (make prod-up,
# make prod-update, make prod-backup, make prod-restore; docs/operations.md, "Deploy to a VM").
# Usage: scripts/deploy/ops.sh up | update [--build] [REF] | backup [FILE] | restore FILE
#        | compose ARGS...   (as root, on the VM)
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=install.sh
. "$(dirname "$0")/install.sh"
# A FILE argument is relative to the folder the command runs in.
CALLER_DIR=$PWD
cd "$(dirname "$0")/../.."

API_IMAGE=ghcr.io/kobars/realtime-vocab-quiz-api
WEB_IMAGE=ghcr.io/kobars/realtime-vocab-quiz-web

from_caller() { if [[ $1 == /* ]]; then printf '%s\n' "$1"; else printf '%s/%s\n' "$CALLER_DIR" "$1"; fi; }

ready() { wait_ready "$(env_value DOMAIN .env)" "$(env_value TLS_ISSUER .env)"; }

# IMAGE_TAG from the environment (set but empty counts), else from .env. Empty: images built here.
image_tag() {
  if [[ -n ${IMAGE_TAG+set} ]]; then
    printf '%s\n' "$IMAGE_TAG"
  elif [[ -f .env ]]; then
    env_value IMAGE_TAG .env
  fi
}

# docker compose on the public host's stack (the prod make targets run it): with an image tag, on
# the published images.
prod_compose() {
  local files=(-f compose.yaml -f compose.prod.yaml)
  [[ -z $(image_tag) ]] || files+=(-f compose.images.yaml)
  docker compose "${files[@]}" "$@"
}

# Starts the stack on the tag's published images, pulled first unless --no-pull, or on images
# built here from the checkout. The edge's config files are bind-mounted: a changed one shows only
# in a new nginx or Caddy container, so both are recreated. Each step returns on failure, as an
# update calls it where set -e does not apply.
up() {
  if [[ -z $(image_tag) ]]; then
    make build IMAGE_TAG=dev || return
  elif [[ ${1:-} != --no-pull ]]; then
    prod_compose --profile full pull --quiet || return
  fi
  prod_compose --profile full up -d --wait --wait-timeout 180 || return
  prod_compose --profile full up -d --wait --wait-timeout 180 --no-deps --force-recreate nginx caddy
}

# Tags the images that the stack runs now as :rollback, as a pull replaces the tag's local images.
keep_running_images() {
  local id
  id=$(prod_compose ps -q api-1) && [[ -n $id ]] || die "the stack is not running; start it with make prod-up"
  docker tag "$(docker inspect --format '{{.Image}}' "$id")" "$API_IMAGE:rollback"
  id=$(prod_compose ps -q web)
  docker tag "$(docker inspect --format '{{.Image}}' "$id")" "$WEB_IMAGE:rollback"
}

# Puts the checkout back on BRANCH at COMMIT, or on COMMIT detached when BRANCH is empty.
go_back() {
  if [[ -n $2 ]]; then
    git checkout --quiet "$2" && git reset --keep "$1"
  else
    git checkout --quiet --detach "$1"
  fi
}

# Moves to REF (default: the newest commit of the branch the checkout is on; a tag install has
# none) and restarts on it, on REF's published images when .env names a tag (--build: on images
# built here, for this run); when the stack does not get ready, goes back to the commit and the
# images that ran before. A REF that moves the image tag writes it to .env once the stack is ready.
update() {
  local branch ref before after tag=""
  if [[ ${1:-} == --build ]]; then
    export IMAGE_TAG=""
    shift
  fi
  branch=$(git symbolic-ref -q --short HEAD || true)
  ref=${1:-$branch}
  [[ -n $ref ]] || die "the checkout is on $(git describe --tags --always), not on a branch; name the tag or branch to move to: make prod-update REF=<ref>"
  if [[ -n $(image_tag) ]]; then
    [[ -z ${1:-} ]] || tag=$(image_tag_for "$ref" 0)
    keep_running_images
  fi
  [[ -z $tag ]] || export IMAGE_TAG=$tag
  before=$(git rev-parse HEAD)
  if ! checkout "$PWD" "" "$ref"; then
    go_back "$before" "$branch" || die "could not move to $ref, nor back to $before"
    die "could not move to $ref; the stack still runs $before"
  fi
  after=$(git rev-parse HEAD)
  if up && ready; then
    [[ -z $tag ]] || render_env .env .env "" "$tag"
    log "Updated $before -> $after; the stack is ready"
    return 0
  fi
  printf 'error: %s did not get ready; rolling back to %s\n' "$after" "$before" >&2
  go_back "$before" "$branch" || die "could not check out $before; the checkout has local changes"
  if [[ -n $(image_tag) ]]; then export IMAGE_TAG=rollback; fi
  if up --no-pull && ready; then
    die "update to $after failed; rolled back to $before, which is ready again"
  fi
  die "update to $after failed, and $before is not ready either; see make prod-logs"
}

persistence() { prod_compose exec -T stack-redis redis-cli INFO persistence | tr -d '\r'; }
field() { sed -n "s/^$1://p"; }

# BGSAVE writes the snapshot to a temporary file and renames it, so the copy is a whole one.
backup() {
  local out saves info deadline
  out=backups/quiz-$(date -u +%Y%m%dT%H%M%SZ).tar.gz
  [[ -z $1 ]] || out=$(from_caller "$1")
  [[ -f .env ]] || die "no .env in $PWD; run this in the install folder"
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  log "Snapshotting Redis"
  saves=$(persistence | field rdb_saves)
  # SCHEDULE: during an AOF rewrite Redis starts the save when the rewrite ends, instead of refusing
  # it. When a save already runs, Redis refuses this one and that save counts.
  prod_compose exec -T stack-redis redis-cli BGSAVE SCHEDULE >/dev/null || true
  deadline=$(($(date +%s) + 300))
  until info=$(persistence) &&
    [[ $(field rdb_bgsave_in_progress <<<"$info") == 0 && $(field rdb_saves <<<"$info") -gt $saves ]]; do
    (($(date +%s) < deadline)) || die "the Redis snapshot did not finish in 5 minutes"
    sleep 1
  done
  [[ $(field rdb_last_bgsave_status <<<"$info") == ok ]] || die "the Redis snapshot failed; see make prod-logs"
  mkdir "$tmp/redis"
  prod_compose cp stack-redis:/data/dump.rdb "$tmp/redis/dump.rdb"
  log "Copying the certificates"
  prod_compose cp caddy:/data "$tmp/caddy"
  cp -p .env "$tmp/.env"
  # A new file, so an older one's mode does not carry over.
  (umask 077 && tar -czf "$tmp/backup.tar.gz" -C "$tmp" .env redis caddy)
  mkdir -p "$(dirname "$out")"
  rm -f -- "$out"
  mv "$tmp/backup.tar.gz" "$out"
  chmod 600 "$out"
  log "Wrote $out. It holds .env's secrets and the TLS private keys: keep it private and off this VM."
}

# With AOF on, Redis starts from the AOF alone and would ignore a dump.rdb. So a Redis without AOF
# loads the snapshot in a folder of its own, writes it out as a new AOF, and stops; only then does
# that AOF replace the current data. A snapshot that does not load leaves the current data as is.
# shellcheck disable=SC2016 # the container's shell expands it
REDIS_RESTORE='set -eu
unset REDISCLI_AUTH
work=/data/.restore
rm -rf "$work" && mkdir "$work"
cp /backup/dump.rdb "$work/dump.rdb"
redis-server --loglevel warning --appendonly no --save "" --port 0 --unixsocket /tmp/restore.sock --dir "$work" &
pid=$!
cli() { redis-cli -s /tmp/restore.sock "$@"; }
fail() { echo "error: $1" >&2; kill "$pid" 2>/dev/null || true; rm -rf "$work"; exit 1; }
# Until the condition holds, while the server runs, for at most 10 minutes.
await() {
  tries=0
  until eval "$1"; do
    kill -0 "$pid" 2>/dev/null || fail "Redis stopped: $2"
    tries=$((tries + 1))
    [ "$tries" -lt 3000 ] || fail "Redis took over 10 minutes: $2"
    sleep 0.2
  done
}
await "cli PING >/dev/null 2>&1" "the snapshot did not load"
cli CONFIG SET appendonly yes >/dev/null
await "cli INFO persistence | grep -q ^aof_rewrite_in_progress:0 && cli INFO persistence | grep -q ^aof_rewrite_scheduled:0" "the AOF was not written"
cli INFO persistence | grep -q "^aof_last_bgrewrite_status:ok" || fail "the AOF was not written"
cli SHUTDOWN
wait
rm -rf /data/appendonlydir /data/dump.rdb
mv "$work/appendonlydir" /data/appendonlydir
rm -rf "$work"
chown -R redis:redis /data'

# Root in the service's own image, with only the capabilities a copy and a chown need.
restore_volume() {
  local service=$1 from=$2 script=$3
  prod_compose run --rm --no-deps --user 0 --cap-add CHOWN --cap-add DAC_OVERRIDE \
    --cap-add FOWNER -v "$from:/backup:ro" --entrypoint sh "$service" -c "$script"
}

restore() {
  local file current="" restored
  [[ -n $1 ]] || die "usage: ops.sh restore FILE"
  file=$(from_caller "$1")
  [[ -f $file ]] || die "no backup file $file"
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  tar -xzf "$file" -C "$tmp" .env redis/dump.rdb caddy || die "$file is not a backup from make prod-backup"
  # Without .env no stack runs from here, and compose would refuse to read its files.
  if [[ -f .env ]]; then
    current=$(env_value DOMAIN .env)
    log "Stopping the stack"
    prod_compose --profile '*' down
    cp -p .env .env.before-restore
  fi
  (umask 077 && cp "$tmp/.env" .env)
  # An <ip>.sslip.io name points at the old host's address: this host keeps its own DOMAIN.
  restored=$(env_value DOMAIN .env)
  if [[ $restored == *.sslip.io && -n $current && $restored != "$current" ]]; then
    log "Keeping DOMAIN=$current: the backup's $restored is the old host's address"
    render_env .env .env "$current"
  fi
  log "Restoring the Redis data"
  if ! restore_volume stack-redis "$tmp/redis" "$REDIS_RESTORE"; then
    [[ -n $current ]] || die "the Redis snapshot in $file did not load; the stack is not started"
    cp -p .env.before-restore .env
    up || true
    die "the Redis snapshot in $file did not load; the previous .env and data are back and the stack restarted"
  fi
  log "Restoring the certificates"
  restore_volume caddy "$tmp/caddy" 'rm -rf /data/caddy && cp -a /backup/. /data/ && chown -R 65532:65532 /data'
  up
  ready || die "restored, but https://$(env_value DOMAIN .env)/api/readyz is not ready; see make prod-logs"
  log "Restored $file; the previous .env is in .env.before-restore"
}

case ${1:-} in
  up) up ;;
  update) shift && update "$@" ;;
  backup) backup "${2:-}" ;;
  restore) restore "${2:-}" ;;
  compose) shift && prod_compose "$@" ;;
  *) die "usage: ops.sh up | update [--build] [REF] | backup [FILE] | restore FILE | compose ARGS..." ;;
esac
