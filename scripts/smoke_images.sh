#!/usr/bin/env bash
# AI-ASSISTED: runs each built image as a non-root user on a read-only root filesystem until it is healthy,
# then checks that the web image sends every header of web/security-headers.conf, and that the API
# image defaults to Redis, holds every Lua script of the repo and is ready on a real Redis.
# Usage: scripts/smoke_images.sh [tag]   (the tag of `make build`, default dev). Binds no host port.
set -euo pipefail

tag="${1:-dev}"
root="$(dirname "$0")/.."
snippet="$root/web/security-headers.conf"
lua_dir="api/src/quiz/adapters/redis/lua"

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

# check_ready <container>: /readyz answers 200, so the node reached Redis and loaded its scripts.
check_ready() {
  docker exec "$1" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2)"
  echo "$1: /readyz 200 on Redis"
}

# check_api_image <image>: the image defaults to STORE=redis, so a node started without it never
# keeps state of its own, and it holds the repo's Lua scripts: the loader lists the installed lua/
# folder, so a script missing from the image would fail only when first called.
check_api_image() {
  local image="$1" store expected actual
  store="$(docker run --rm --entrypoint python "$image" -c "from quiz.config import Settings; print(Settings().store)")"
  if [[ "$store" != redis ]]; then
    echo "$image defaults to STORE=$store, not redis" >&2
    return 1
  fi
  expected="$(git -C "$root" ls-files "$lua_dir/*.lua" | sed "s|^$lua_dir/||" | sort)"
  actual="$(docker run --rm --entrypoint python "$image" -c "from importlib.resources import files; lua = files('quiz.adapters.redis') / 'lua'; print(*sorted(str(p.relative_to(lua)) for p in lua.rglob('*.lua')), sep='\n')")"
  if [[ "$actual" != "$expected" ]]; then
    echo "API image Lua scripts differ from the repo (< repo, > image):" >&2
    diff <(echo "$expected") <(echo "$actual") >&2 || true
    return 1
  fi
  echo "$image: STORE=redis by default, $(wc -l <<<"$expected" | tr -d ' ') Lua scripts as in the repo"
}

# nginx writes its pid and temp files under /tmp.
smoke "elsaquiz-web:$tag" check_security_headers --tmpfs /tmp

check_api_image "elsaquiz-api:$tag"
# The API node on a Redis of its own, on a network of its own, both removed on every way out.
network="smoke-$$"
redis="smoke-redis-$$"
trap 'docker rm --force "$redis" >/dev/null 2>&1; docker network rm "$network" >/dev/null 2>&1' EXIT
docker network create "$network" >/dev/null
docker run --detach --name "$redis" --network "$network" redis:8-alpine >/dev/null
for _ in $(seq 15); do
  docker exec "$redis" redis-cli ping >/dev/null 2>&1 && break
  sleep 1
done
smoke "elsaquiz-api:$tag" check_ready --network "$network" -e "REDIS_URL=redis://$redis:6379/0"
