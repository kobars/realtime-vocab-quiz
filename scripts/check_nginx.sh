#!/usr/bin/env bash
# AI-ASSISTED: nginx -t on the web image's site config and on every tracked nginx.conf under infra/,
# also with the public host's real-ip template rendered as compose.prod.yaml does.
# Usage: scripts/check_nginx.sh [tag]   (the tag of `make build`, default dev). Binds no host port.
set -euo pipefail

image="elsaquiz-web:${1:-dev}"

docker run --rm --read-only --tmpfs /tmp "$image" nginx -t

confs="$(git ls-files 'infra/*nginx.conf')"
if [[ -z "$confs" ]]; then
  echo "infra/ has no nginx.conf yet; skipped"
  exit 0
fi

# The test runs outside the compose network: an upstream named by a compose service must resolve.
services="$(docker compose --profile '*' config --services)" # stops here when compose fails
hosts=()
while IFS= read -r service; do
  hosts+=("--add-host=$service:127.0.0.1")
done <<<"$services"

while IFS= read -r conf; do
  echo "nginx -t: $conf"
  docker run --rm --tmpfs /tmp "${hosts[@]}" -v "$PWD/$conf:/etc/nginx/nginx.conf:ro" "$image" nginx -t </dev/null
done <<<"$confs"

# On a public host (compose.prod.yaml), the image's entrypoint renders this template into
# /tmp/edge/, which nginx.conf includes: test the config with it rendered, and that it was included.
template="$(git ls-files 'infra/nginx/real-ip.conf.template')"
[[ -n "$template" ]] || exit 0
while IFS= read -r conf; do
  echo "nginx -t with $template: $conf"
  docker run --rm --tmpfs /tmp "${hosts[@]}" -e NGINX_ENVSUBST_OUTPUT_DIR=/tmp -e EDGE_SUBNET=10.89.79.0/24 \
    -v "$PWD/$conf:/etc/nginx/nginx.conf:ro" \
    -v "$PWD/$template:/etc/nginx/templates/edge/real-ip.conf.template:ro" \
    "$image" nginx -T </dev/null | grep -Fx 'set_real_ip_from 10.89.79.0/24;' >/dev/null
done <<<"$confs"
