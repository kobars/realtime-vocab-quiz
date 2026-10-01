#!/usr/bin/env bash
# AI-ASSISTED: runs each built image as a non-root user on a read-only root filesystem until it is healthy,
# then checks that the web image sends every header of web/security-headers.conf.
# Usage: scripts/smoke_images.sh [tag]   (the tag of `make build`, default dev). Binds no host port.
set -euo pipefail

tag="${1:-dev}"
snippet="$(dirname "$0")/../web/security-headers.conf"

# check_security_headers <container>: each `add_header Name "value"` line of the snippet comes
# back as `Name: value` on the SPA route and on a hashed asset, so no location drops the include.
check_security_headers() {
  local name="$1" asset path response header headers total
  if [[ ! -r "$snippet" ]]; then
    echo "cannot read $snippet" >&2
    return 1
  fi
  mapfile -t headers < <(sed -nE 's/^add_header ([^ ]+) "(.*)" always;$/\1: \2/p' "$snippet")
  total="$(grep -cE '^[[:space:]]*add_header' "$snippet" || true)"
  # A line in another form would go unchecked.
  if (( ${#headers[@]} == 0 || ${#headers[@]} < total )); then
    echo "$snippet: ${#headers[@]} of $total add_header lines read as add_header Name \"value\" always;" >&2
    return 1
  fi
  asset="$(docker exec "$name" find /usr/share/nginx/html/assets -type f -print -quit)"
  for path in / "/assets/${asset##*/}"; do
    response="$(docker exec "$name" curl -fsSI "http://127.0.0.1:8080$path" | tr -d '\r')"
    for header in "${headers[@]}"; do
      if ! grep -qxF "$header" <<<"$response"; then
        echo "$path lacks $header" >&2
        return 1
      fi
    done
  done
  echo "/ and $path send every security header"
}

# smoke <image> <check> [docker run options...]: uid not 0, then healthy within 60 s with
# --read-only, then `<check> <container>` passes.
# The body is a subshell, so its EXIT trap removes the container on every way out.
smoke() (
  image="$1"
  check="$2"
  shift 2
  uid="$(docker run --rm "$image" id -u)"
  if [[ "$uid" == 0 ]]; then
    echo "$image runs as root" >&2
    return 1
  fi
  name="smoke-${image%%:*}-$$"
  trap 'docker rm --force "$name" >/dev/null 2>&1' EXIT
  docker run --detach --name "$name" --read-only "$@" "$image" >/dev/null
  for _ in $(seq 30); do
    state="$(docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' "$name")"
    if [[ "$state" == "running healthy" ]]; then
      echo "$image: uid $uid, healthy on a read-only root filesystem"
      "$check" "$name"
      return
    fi
    [[ "$state" == "running starting" ]] || break
    sleep 2
  done
  echo "$image did not become healthy ($state)" >&2
  docker logs "$name" >&2
  return 1
)

smoke "elsaquiz-api:$tag" true
# nginx writes its pid and temp files under /tmp.
smoke "elsaquiz-web:$tag" check_security_headers --tmpfs /tmp
