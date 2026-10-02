#!/usr/bin/env bash
# AI-ASSISTED: one-command install of the full stack behind HTTPS on a fresh Ubuntu 22.04 or 24.04
# VM (docs/operations.md, "Deploy to a VM"). Run as root:
#   curl -fsSL https://raw.githubusercontent.com/kobars/realtime-vocab-quiz/main/scripts/deploy/install.sh \
#     | sudo bash -s -- [--domain quiz.example.com] [--ref main]
# Safe to run again: it updates the checkout and keeps .env and its secrets. --help lists every
# option. scripts/deploy/ops.sh sources this file for its helpers; sourcing runs nothing.
set -euo pipefail

REPO_URL=https://github.com/kobars/realtime-vocab-quiz.git
INSTALL_DIR=/opt/realtime-vocab-quiz
# The VM's public IPv4: DigitalOcean's metadata service first, then a public echo service.
METADATA_URL=http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address
ECHO_URL=https://checkip.amazonaws.com
# How long to wait for https://$DOMAIN/api/readyz after the stack starts, in seconds.
READY_TIMEOUT=${READY_TIMEOUT:-180}
DRY_RUN=0

log() { printf '==> %s\n' "$*"; }
die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

# Runs a command that changes the system outside .env; --dry-run prints it instead.
run() {
  if [[ $DRY_RUN == 1 ]]; then
    printf 'dry run, skipped: %s\n' "$*"
  else
    "$@"
  fi
}

usage() {
  cat <<'EOF'
Usage: install.sh [--domain NAME] [--ref REF] [--ip ADDRESS] [--dns-wait SECONDS] [--dir PATH]
                  [--repo URL] [--dry-run]
  --domain NAME        host name whose DNS A record points at this VM (default: <ip>.sslip.io)
  --ref REF            branch or tag to deploy (default: main)
  --ip ADDRESS         this VM's public IPv4 (default: detected)
  --dns-wait SECONDS   wait up to this long for --domain to point at this VM (default: 0)
  --dir PATH           install folder (default: /opt/realtime-vocab-quiz)
  --repo URL           git URL to clone (default: the project's GitHub repository)
  --dry-run            run the checks and write .env, but print the commands that install
                       packages, clone, start the stack or wait for it
EOF
}

valid_ipv4() {
  local octet
  [[ $1 =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
  for octet in "${BASH_REMATCH[@]:1}"; do
    ((10#$octet <= 255)) || return 1
  done
}

public_ipv4() {
  local url ip
  for url in "$METADATA_URL" "$ECHO_URL"; do
    ip=$(curl -fsS --max-time 3 "$url" 2>/dev/null | tr -d '[:space:]') || continue
    if valid_ipv4 "$ip"; then
      printf '%s\n' "$ip"
      return 0
    fi
  done
  return 1
}

# The --domain value, else <ip>.sslip.io, which resolves to the address it names.
choose_domain() {
  if [[ -n $1 ]]; then printf '%s\n' "$1"; else printf '%s.sslip.io\n' "$2"; fi
}

check_root() {
  [[ $(id -u) == 0 ]] || die "run as root, for example: curl -fsSL <install.sh URL> | sudo bash -s --"
}

check_os() {
  local file=${1:-/etc/os-release} release
  [[ -r $file ]] || die "unsupported OS: no $file (Ubuntu 22.04 or 24.04 needed)"
  # shellcheck disable=SC1090 # os-release is plain shell assignments
  release=$(. "$file" && printf '%s %s' "${ID:-}" "${VERSION_ID:-}")
  case $release in
    "ubuntu 22.04" | "ubuntu 24.04") ;;
    *) die "unsupported OS: '$release' (Ubuntu 22.04 or 24.04 needed)" ;;
  esac
}

port_busy() {
  if command -v ss >/dev/null; then
    [[ -n $(ss -Htln "sport = :$1") ]]
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
  fi
}

# Caddy needs 80 (the ACME HTTP challenge) and 443. On a second run this stack's own Caddy holds them.
check_ports() {
  local port busy=""
  if command -v docker >/dev/null &&
    [[ -n $(docker ps -q --filter label=com.docker.compose.project=elsaquiz --filter label=com.docker.compose.service=caddy 2>/dev/null) ]]; then
    return 0
  fi
  for port in 80 443; do
    if port_busy "$port"; then busy="$busy $port"; fi
  done
  [[ -z $busy ]] || die "port(s)$busy already in use; stop the service that listens there (see: ss -tlnp), then run again"
}

# Every address the name's A records give, space-separated; empty when it does not resolve.
resolve_ipv4() {
  { getent ahostsv4 "$1" 2>/dev/null || true; } | awk '{print $1}' | sort -u | paste -s -d ' ' -
}

# Checked before Caddy asks Let's Encrypt for a certificate: each failed validation counts against
# its rate limits.
check_dns() {
  local domain=$1 ip=$2 wait=${3:-0} deadline addrs
  [[ $domain != "$ip.sslip.io" ]] || return 0
  deadline=$(($(date +%s) + wait))
  while :; do
    addrs=$(resolve_ipv4 "$domain")
    [[ $addrs != "$ip" ]] || return 0
    if (($(date +%s) >= deadline)); then
      die "$domain resolves to ${addrs:-nothing}, not to this VM ($ip). Point its A record at $ip (and remove any AAAA record), then run again; or pass --domain $ip.sslip.io"
    fi
    log "Waiting for $domain to point at $ip (it resolves to ${addrs:-nothing})"
    sleep 15
  done
}

install_packages() {
  local cmd missing=""
  # On a first boot, unattended-upgrades may hold the dpkg lock: every apt-get below, the Docker
  # script's included, waits for it instead of failing.
  APT_CONFIG=$(mktemp)
  echo 'DPkg::Lock::Timeout "600";' >"$APT_CONFIG"
  export APT_CONFIG
  for cmd in curl git make openssl; do
    command -v "$cmd" >/dev/null || missing="$missing $cmd"
  done
  if [[ -n $missing ]]; then
    log "Installing$missing"
    run apt-get update -q
    # shellcheck disable=SC2086 # one package per word
    run env DEBIAN_FRONTEND=noninteractive apt-get install -yq ca-certificates $missing
  fi
  if ! docker compose version >/dev/null 2>&1; then
    log "Installing Docker Engine and the Compose plugin"
    run sh -c 'curl -fsSL https://get.docker.com | sh'
  fi
  run systemctl enable --now docker
}

checkout() {
  local dir=$1 repo=$2 ref=$3
  if [[ -d $dir/.git ]]; then
    log "Updating $dir to $ref"
    run git -C "$dir" fetch --quiet --tags origin
    run git -C "$dir" checkout --quiet "$ref"
    if git -C "$dir" symbolic-ref -q HEAD >/dev/null; then
      run git -C "$dir" merge --quiet --ff-only "@{upstream}"
    fi
  elif [[ $DRY_RUN != 1 && -d $dir && -n $(ls -A "$dir") ]]; then
    die "$dir exists and is not a git checkout; move it away or pass --dir"
  else
    log "Cloning $repo ($ref) into $dir"
    run git clone --quiet --branch "$ref" "$repo" "$dir"
  fi
}

new_secret() { od -An -tx1 -N24 /dev/urandom | tr -d ' \n'; }

# The last value of KEY in an env file.
env_value() { sed -n "s/^$1=//p" "$2" | tail -n 1; }

# Writes the env file DEST from SRC: DOMAIN set to the domain when one is given, and each empty
# secret filled. A secret that has a value is never changed, so running it again keeps them.
render_env() {
  local src=$1 dest=$2 domain=$3 line
  (
    umask 077
    while IFS= read -r line || [[ -n $line ]]; do
      case $line in
        DOMAIN=*) [[ -z $domain ]] || line="DOMAIN=$domain" ;;
        ADMIN_TOKEN= | REDIS_PASSWORD=) line="$line$(new_secret)" ;;
      esac
      printf '%s\n' "$line"
    done <"$src" >"$dest.tmp"
    mv "$dest.tmp" "$dest"
  )
}

# Polls https://DOMAIN/api/readyz until it answers 200, for READY_TIMEOUT seconds. With TLS_ISSUER
# internal (Caddy's local CA) the certificate is not checked.
wait_ready() {
  local url="https://$1/api/readyz" insecure="" deadline
  [[ ${2:-} != internal ]] || insecure=1
  deadline=$(($(date +%s) + READY_TIMEOUT))
  until curl -fsS --max-time 5 ${insecure:+--insecure} "$url" >/dev/null 2>&1; do
    (($(date +%s) < deadline)) || return 1
    sleep 5
  done
}

main() {
  local domain="" ref=main ip="" dns_wait=0 dir=$INSTALL_DIR repo=$REPO_URL env_domain
  while (($#)); do
    case $1 in
      --domain | --ref | --ip | --dns-wait | --dir | --repo) [[ $# -ge 2 ]] || die "$1 needs a value" ;;
    esac
    case $1 in
      --domain) domain=$2 && shift ;;
      --ref) ref=$2 && shift ;;
      --ip) ip=$2 && shift ;;
      --dns-wait) dns_wait=$2 && shift ;;
      --dir) dir=$2 && shift ;;
      --repo) repo=$2 && shift ;;
      --dry-run) DRY_RUN=1 ;;
      -h | --help) usage && return 0 ;;
      *) usage >&2 && die "unknown option: $1" ;;
    esac
    shift
  done
  [[ -z $domain || $domain =~ ^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$ ]] || die "--domain '$domain' is not a host name"
  [[ $dns_wait =~ ^[0-9]+$ ]] || die "--dns-wait takes whole seconds, not '$dns_wait'"

  check_root
  check_os
  check_ports
  install_packages

  if [[ -n $ip ]]; then
    valid_ipv4 "$ip" || die "--ip '$ip' is not an IPv4 address"
  else
    ip=$(public_ipv4) || die "could not find this VM's public IPv4 address; pass --ip ADDRESS"
  fi

  checkout "$dir" "$repo" "$ref"
  # A first run writes .env from the example; a later one keeps it and changes DOMAIN only
  # when --domain is given.
  if [[ -f $dir/.env ]]; then
    log "Keeping $dir/.env and its secrets"
    render_env "$dir/.env" "$dir/.env" "$domain"
  elif [[ -f $dir/.env.prod.example ]]; then
    log "Writing $dir/.env with a new ADMIN_TOKEN and REDIS_PASSWORD"
    render_env "$dir/.env.prod.example" "$dir/.env" "$(choose_domain "$domain" "$ip")"
  else
    [[ $DRY_RUN == 1 ]] || die "$dir has no .env.prod.example; is --ref a revision of this project?"
    log "dry run: no checkout yet, so no .env"
  fi
  if [[ -f $dir/.env ]]; then
    env_domain=$(env_value DOMAIN "$dir/.env")
  else
    env_domain=$(choose_domain "$domain" "$ip")
  fi
  log "Domain: $env_domain"
  check_dns "$env_domain" "$ip" "$dns_wait"

  log "Building and starting the stack (a few minutes on a fresh VM)"
  run make -C "$dir" prod-up
  log "Waiting for https://$env_domain/api/readyz (up to ${READY_TIMEOUT}s)"
  if [[ $DRY_RUN == 1 ]]; then
    printf 'dry run, skipped: the wait\n'
  elif ! wait_ready "$env_domain" "$(env_value TLS_ISSUER "$dir/.env")"; then
    die "https://$env_domain/api/readyz did not answer within ${READY_TIMEOUT}s; see the logs: make -C $dir prod-logs"
  fi

  cat <<EOF

The quiz app is live at https://$env_domain/
Start a 60-minute quiz and print its player link:  make -C $dir prod-demo
The admin token is ADMIN_TOKEN in $dir/.env (readable by root only); keep it secret.
Update: make -C $dir prod-update    Back up: make -C $dir prod-backup
EOF
}

# Run unless sourced; piped into bash, BASH_SOURCE is empty. Piped, stdin is the rest of this
# script, so no command may read it.
if [[ -z ${BASH_SOURCE[0]:-} || ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@" </dev/null
fi
