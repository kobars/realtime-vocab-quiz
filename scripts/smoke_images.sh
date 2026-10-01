#!/usr/bin/env bash
# AI-ASSISTED: runs each built image as a non-root user on a read-only root filesystem until it is healthy.
# Usage: scripts/smoke_images.sh [tag]   (the tag of `make build`, default dev). Binds no host port.
set -euo pipefail

tag="${1:-dev}"

# smoke <image> [docker run options...]: uid not 0, then healthy within 60 s with --read-only.
smoke() {
  local image="$1" name uid state
  shift
  uid="$(docker run --rm "$image" id -u)"
  if [[ "$uid" == 0 ]]; then
    echo "$image runs as root" >&2
    return 1
  fi
  name="smoke-${image%%:*}-$$"
  docker run --detach --name "$name" --read-only "$@" "$image" >/dev/null
  for _ in $(seq 30); do
    state="$(docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' "$name")"
    if [[ "$state" == "running healthy" ]]; then
      docker rm --force "$name" >/dev/null
      echo "$image: uid $uid, healthy on a read-only root filesystem"
      return 0
    fi
    [[ "$state" == "running starting" ]] || break
    sleep 2
  done
  echo "$image did not become healthy ($state)" >&2
  docker logs "$name" >&2
  docker rm --force "$name" >/dev/null
  return 1
}

smoke "elsaquiz-api:$tag"
# nginx writes its pid and temp files under /tmp.
smoke "elsaquiz-web:$tag" --tmpfs /tmp
