#!/usr/bin/env bash
# AI-ASSISTED: the stack on Fly.io from a laptop (make fly-launch, fly-deploy, fly-demo, fly-status,
# fly-destroy; docs/operations.md, "Deploy to Fly.io"): three apps named after the FLY_APP prefix,
# <prefix>-redis, <prefix>-api (two Machines) and <prefix>-web (the only public one). flyctl must
# already be logged in (fly auth login): this script never reads or stores a Fly token.
# Runs on the Bash 3.2 that macOS ships.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=install.sh
. "$(dirname "$0")/install.sh"

# Every path below is relative to the repository root, the build context of both images.
cd "$(dirname "$0")/../.."
FLY_DIR=infra/fly
# The prefix, region, organization and both secrets: Fly secrets cannot be read back, and
# make fly-demo needs the admin token. Git and the image builds ignore it.
ENV_FILE=${FLY_ENV_FILE:-.env.fly}
IMAGES=ghcr.io/kobars/realtime-vocab-quiz
VOLUME=redis_data

usage() {
  cat <<'EOF'
Usage: fly.sh launch [--dry-run]
       fly.sh deploy [--build] [--tag TAG] [--dry-run]
       fly.sh demo | status [--dry-run]
       fly.sh destroy [--dry-run]
  launch     create the three apps, the Redis volume, the secrets (kept in .env.fly) and the web
             app's shared IPv4 and IPv6; safe to run again
  deploy     deploy Redis, then the two API Machines, then the web edge, each once healthy, and
             print the HTTPS URL
  demo       start a fresh 60-minute quiz with the admin token of .env.fly; print its player URL
  status     show the three apps' Machines and checks
  destroy    delete the three apps, with the Redis volume, after you type the prefix back
  --build    build the images from this checkout on Fly's remote builder instead of deploying
             the published ones
  --tag TAG  the published images' tag (default: main)
  --dry-run  run no flyctl command, not even the login check; print each one, as on a first run
Settings, from the environment or .env.fly: FLY_APP (the prefix; Fly app names are global),
FLY_REGION (default sin), FLY_ORG (default personal).
EOF
}

# FLY_APP, FLY_REGION and FLY_ORG: the environment, else .env.fly, else the defaults. The secrets
# belong to the prefix that .env.fly names, so another prefix is refused.
load_settings() {
  local saved=""
  [[ ! -f $ENV_FILE ]] || saved=$(env_value FLY_APP "$ENV_FILE")
  if [[ -n ${FLY_APP:-} && -n $saved && $FLY_APP != "$saved" ]]; then
    die "FLY_APP is $FLY_APP but $ENV_FILE holds the secrets of $saved; unset FLY_APP or move that file away"
  fi
  APP=${FLY_APP:-$saved}
  [[ -n $APP ]] || die "set FLY_APP, the prefix of the three app names (Fly app names are global), for example: make fly-launch FLY_APP=myquiz"
  [[ $APP =~ ^[a-z0-9][a-z0-9-]{0,40}$ ]] || die "FLY_APP '$APP' must be lower-case letters, digits and dashes (at most 41)"
  REGION=${FLY_REGION:-}
  ORG=${FLY_ORG:-}
  if [[ -f $ENV_FILE ]]; then
    REGION=${REGION:-$(env_value FLY_REGION "$ENV_FILE")}
    ORG=${ORG:-$(env_value FLY_ORG "$ENV_FILE")}
  fi
  REGION=${REGION:-sin}
  ORG=${ORG:-personal}
  WEB=$APP-web API=$APP-api REDIS=$APP-redis
}

need_flyctl() {
  [[ $DRY_RUN == 0 ]] || return 0
  command -v flyctl >/dev/null || die "flyctl is not installed: https://fly.io/docs/flyctl/install/"
  flyctl auth whoami >/dev/null 2>&1 || die "flyctl is not logged in; run fly auth login"
}

need_env_file() {
  [[ $DRY_RUN == 1 || -f $ENV_FILE ]] || die "no $ENV_FILE; run make fly-launch first"
}

# Sets one app's secrets from NAME=VALUE lines on stdin, staged for its next deploy: a value never
# appears on a command line or in the output.
import_secrets() {
  local app=$1 names=$2
  if [[ $DRY_RUN == 1 ]]; then
    cat >/dev/null
    printf 'dry run, skipped: flyctl secrets import --app %s --stage   (stdin: %s)\n' "$app" "$names"
  else
    flyctl secrets import --app "$app" --stage >/dev/null
  fi
}

# Each lookup is read whole before it is used, so a failed flyctl call stops the script instead of
# reading as "nothing there". On a dry run, nothing exists.
lookup() { if [[ $DRY_RUN == 1 ]]; then printf '\n'; else "$@"; fi; }

launch() {
  local apps app volumes ips admin_token redis_password
  load_settings
  need_flyctl
  if [[ -f $ENV_FILE ]]; then
    admin_token=$(env_value ADMIN_TOKEN "$ENV_FILE")
    redis_password=$(env_value REDIS_PASSWORD "$ENV_FILE")
    [[ -n $admin_token && -n $redis_password ]] || die "$ENV_FILE lacks ADMIN_TOKEN or REDIS_PASSWORD"
    [[ $DRY_RUN == 1 ]] || chmod 600 "$ENV_FILE"
  else
    admin_token=$(openssl rand -hex 24)
    redis_password=$(openssl rand -hex 24)
    if [[ $DRY_RUN == 1 ]]; then
      printf 'dry run, skipped: write %s (mode 600) with a new ADMIN_TOKEN and REDIS_PASSWORD\n' "$ENV_FILE"
    else
      (
        umask 077
        printf 'FLY_APP=%s\nFLY_REGION=%s\nFLY_ORG=%s\nADMIN_TOKEN=%s\nREDIS_PASSWORD=%s\n' \
          "$APP" "$REGION" "$ORG" "$admin_token" "$redis_password" >"$ENV_FILE"
      )
      log "Wrote $ENV_FILE (mode 600): the secrets of $APP; keep it private"
    fi
  fi

  apps=$(lookup flyctl apps list --org "$ORG" --quiet)
  for app in "$REDIS" "$API" "$WEB"; do
    grep -qx "$app" <<<"$apps" || run flyctl apps create "$app" --org "$ORG"
  done
  volumes=$(lookup flyctl volumes list --app "$REDIS" --json)
  grep -Eiq "\"name\": *\"$VOLUME\"" <<<"$volumes" ||
    run flyctl volumes create "$VOLUME" --app "$REDIS" --region "$REGION" --size 1 --yes
  # Redis has no address but its .internal name; the API only a private Flycast one.
  ips=$(lookup flyctl ips list --app "$API" --json)
  grep -Eiq '"type": *"private_v6"' <<<"$ips" || run flyctl ips allocate-v6 --private --app "$API"
  ips=$(lookup flyctl ips list --app "$WEB" --json)
  grep -Eiq '"type": *"(shared_v4|v4)"' <<<"$ips" || run flyctl ips allocate-v4 --shared --app "$WEB" --yes
  grep -Eiq '"type": *"v6"' <<<"$ips" || run flyctl ips allocate-v6 --app "$WEB"

  # The URL's password is hex, so it needs no escaping.
  printf 'REDIS_PASSWORD=%s\n' "$redis_password" | import_secrets "$REDIS" REDIS_PASSWORD
  printf 'ADMIN_TOKEN=%s\nREDIS_URL=redis://:%s@%s.internal:6379/0\n' "$admin_token" "$redis_password" "$REDIS" |
    import_secrets "$API" "ADMIN_TOKEN, REDIS_URL"
  log "Launched $REDIS, $API and $WEB in $REGION; next: make fly-deploy"
}

deploy() {
  local build=0 tag=main common api_image web_image
  while (($#)); do
    case $1 in
      --build) build=1 ;;
      --tag)
        [[ $# -ge 2 && -n $2 ]] || die "--tag needs a value"
        tag=$2 && shift
        ;;
      *) die "unknown option: $1" ;;
    esac
    shift
  done
  load_settings
  need_flyctl
  need_env_file
  # The published images, or the Dockerfiles built on Fly's remote builder.
  if [[ $build == 1 ]]; then
    api_image=(--dockerfile api/Dockerfile --remote-only)
    web_image=(--dockerfile web/Dockerfile --remote-only)
  else
    api_image=(--image "$IMAGES-api:$tag")
    web_image=(--image "$IMAGES-web:$tag")
  fi
  common=(--primary-region "$REGION" --ha=false --wait-timeout 5m --yes)

  log "Deploying $REDIS"
  run flyctl deploy . --config "$FLY_DIR/redis.toml" --app "$REDIS" "${common[@]}" --no-public-ips
  log "Deploying $API (two Machines)"
  run flyctl deploy . --config "$FLY_DIR/api.toml" --app "$API" "${common[@]}" --no-public-ips \
    "${api_image[@]}" --env "ALLOWED_ORIGINS=https://$WEB.fly.dev"
  run flyctl scale count 2 --app "$API" --region "$REGION" --yes
  log "Deploying $WEB"
  run flyctl deploy . --config "$FLY_DIR/web.toml" --app "$WEB" "${common[@]}" \
    "${web_image[@]}" --env "QUIZ_API_HOST=$API.flycast"

  log "Waiting for https://$WEB.fly.dev/api/readyz (up to ${READY_TIMEOUT}s)"
  if [[ $DRY_RUN == 1 ]]; then
    printf 'dry run, skipped: the wait\n'
  elif ! wait_ready "$WEB.fly.dev"; then
    die "https://$WEB.fly.dev/api/readyz did not answer within ${READY_TIMEOUT}s; see: make fly-status, flyctl logs --app $API"
  fi
  log "The quiz app is live at https://$WEB.fly.dev/; a 60-minute quiz: make fly-demo"
}

demo() {
  local token
  load_settings
  need_env_file
  token=$(env_value ADMIN_TOKEN "$ENV_FILE" 2>/dev/null || true)
  # The token goes in the environment, never on the command line; seed.py's hint names the local stack.
  ADMIN_TOKEN=$token run uv run --project api --locked python scripts/seed.py \
    --api-url "https://$WEB.fly.dev/api" --public-url "https://$WEB.fly.dev" | grep -v '^End it:'
}

status() {
  local app
  load_settings
  need_flyctl
  for app in "$WEB" "$API" "$REDIS"; do
    run flyctl status --app "$app"
  done
  printf '\nhttps://%s.fly.dev/\n' "$WEB"
}

destroy() {
  local apps app found="" answer
  load_settings
  need_flyctl
  apps=$(lookup flyctl apps list --org "$ORG" --quiet)
  for app in "$WEB" "$API" "$REDIS"; do
    if [[ $DRY_RUN == 1 ]] || grep -qx "$app" <<<"$apps"; then found+=" $app"; fi
  done
  [[ -n $found ]] || {
    log "Nothing to delete: no app $WEB, $API or $REDIS in $ORG"
    return 0
  }
  printf 'To delete, with their Machines, the Redis volume and its quiz data, and the addresses:\n'
  for app in $found; do printf '  %s\n' "$app"; done
  if [[ $DRY_RUN == 0 ]]; then
    read -r -p "Type the prefix ($APP) to delete them: " answer || true
    [[ $answer == "$APP" ]] || die "nothing deleted"
  fi
  for app in $found; do run flyctl apps destroy "$app" --yes; done
  [[ $DRY_RUN == 1 ]] || log "Deleted. $ENV_FILE stays: make fly-launch reuses its secrets; delete it when done"
}

main() {
  local cmd=${1:-} args=()
  [[ $# == 0 ]] || shift
  while (($#)); do
    case $1 in
      --dry-run) DRY_RUN=1 ;;
      -h | --help) cmd=help ;;
      *) args+=("$1") ;;
    esac
    shift
  done
  case $cmd in
    launch | demo | status | destroy)
      [[ ${#args[@]} == 0 ]] || die "unknown option: ${args[0]}"
      "$cmd"
      ;;
    deploy) deploy ${args[@]+"${args[@]}"} ;;
    help | -h | --help) usage ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
