#!/usr/bin/env bash
# AI-ASSISTED: the public host on DigitalOcean, created from a laptop with doctl (make do-deploy)
# and deleted again (make do-destroy); docs/operations.md, "From a laptop". doctl must already be
# signed in (doctl auth init): this script never reads or stores a token.
# Usage: scripts/deploy/droplet.sh deploy [--domain NAME] [--region SLUG] [--size SLUG] [--dry-run]
#        scripts/deploy/droplet.sh destroy [--dry-run]
# --dry-run runs the lookups (doctl ... list) and prints each command that creates or deletes.
# Runs on the Bash 3.2 that macOS ships.
set -euo pipefail
# The install on a new Droplet takes about five minutes, plus the wait for a DNS record.
READY_TIMEOUT=${READY_TIMEOUT:-1200}
# shellcheck source-path=SCRIPTDIR source=install.sh
. "$(dirname "$0")/install.sh"

USER_DATA="$(dirname "$0")/../../infra/deploy/cloud-init.yaml"
# The tag of the Droplet and the name of the firewall: make do-destroy deletes only these.
TAG=realtime-vocab-quiz
DROPLET_IMAGE=ubuntu-24-04-x64
ANYWHERE=address:0.0.0.0/0,address:::/0
INBOUND="protocol:tcp,ports:22,$ANYWHERE protocol:tcp,ports:80,$ANYWHERE protocol:tcp,ports:443,$ANYWHERE"
OUTBOUND="protocol:tcp,ports:all,$ANYWHERE protocol:udp,ports:all,$ANYWHERE protocol:icmp,$ANYWHERE"

need_doctl() {
  command -v doctl >/dev/null || die "doctl is not installed: https://docs.digitalocean.com/reference/doctl/how-to/install/"
  doctl account get >/dev/null || die "doctl is not signed in; run doctl auth init"
}

firewall_id() {
  doctl compute firewall list --format ID,Name --no-header | awk -v name="$TAG" '$2 == name { print $1 }'
}

# The longest zone on DigitalOcean that NAME is or ends in; empty when there is none.
dns_zone() {
  local name=$1 zone found=""
  [[ $name == *.* ]] || return 0
  while read -r zone; do
    if [[ $name == "$zone" || $name == *".$zone" ]] && ((${#zone} > ${#found})); then found=$zone; fi
  done < <(doctl compute domain list --format Domain --no-header)
  printf '%s\n' "$found"
}

# The record's name inside its zone: @ for the zone itself.
record_name() {
  if [[ $1 == "$2" ]]; then printf '@\n'; else printf '%s\n' "${1%."$2"}"; fi
}

deploy() {
  local domain="" region=sgp1 size=s-2vcpu-4gb name keys zone ip host
  while (($#)); do
    case $1 in
      --domain | --region | --size) [[ $# -ge 2 ]] || die "$1 needs a value" ;;
    esac
    case $1 in
      --domain) domain=$2 && shift ;;
      --region) region=$2 && shift ;;
      --size) size=$2 && shift ;;
      --dry-run) DRY_RUN=1 ;;
      *) die "unknown option: $1" ;;
    esac
    shift
  done
  [[ -z $domain || $domain =~ ^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$ ]] || die "DOMAIN '$domain' is not a host name"
  need_doctl
  name=${domain:-$TAG}
  [[ -z $(doctl compute droplet list --tag-name "$TAG" --format Name --no-header) ]] ||
    die "a Droplet tagged $TAG exists already; make do-destroy deletes it"
  keys=$(doctl compute ssh-key list --format ID --no-header | paste -s -d , -)
  [[ -n $keys ]] || die "the DigitalOcean account has no SSH key; add yours: doctl compute ssh-key import laptop --public-key-file ~/.ssh/id_ed25519.pub"

  # The cloud-init user data with DOMAIN filled in (empty: <ip>.sslip.io); global for the trap.
  user_data=$(mktemp)
  trap 'rm -f "$user_data"' EXIT
  sed "s/^\( *\)DOMAIN=\$/\1DOMAIN=$domain/" "$USER_DATA" >"$user_data"

  if [[ -z $(firewall_id) ]]; then
    log "Creating the firewall $TAG: inbound TCP 22, 80 and 443 only, for Droplets tagged $TAG"
    run doctl compute firewall create --name "$TAG" --tag-names "$TAG" \
      --inbound-rules "$INBOUND" --outbound-rules "$OUTBOUND"
  fi
  # With SSH keys, the Droplet has no root password.
  local create=(doctl compute droplet create "$name" --image "$DROPLET_IMAGE" --region "$region"
    --size "$size" --ssh-keys "$keys" --tag-names "$TAG" --user-data-file "$user_data"
    --wait --format PublicIPv4 --no-header)
  log "Creating the Droplet $name ($size, $region)"
  if [[ $DRY_RUN == 1 ]]; then
    run "${create[@]}"
    ip="<droplet-ip>"
  else
    ip=$("${create[@]}")
    valid_ipv4 "$ip" || die "doctl did not print the Droplet's IPv4 address: '$ip'"
  fi

  zone=$(dns_zone "$domain")
  if [[ -n $zone ]]; then
    log "Pointing $domain at $ip"
    run doctl compute domain records create "$zone" --record-type A \
      --record-name "$(record_name "$domain" "$zone")" --record-data "$ip" --record-ttl 300
  elif [[ -n $domain ]]; then
    log "$domain is not a DigitalOcean domain: point its A record at $ip now; the install waits 30 minutes for it"
  fi

  host=${domain:-$ip.sslip.io}
  log "Waiting for https://$host/api/readyz while the Droplet installs the stack (up to ${READY_TIMEOUT}s)"
  if [[ $DRY_RUN == 1 ]]; then
    printf 'dry run, skipped: the wait\n'
  elif ! wait_ready "$host"; then
    die "https://$host/api/readyz did not answer within ${READY_TIMEOUT}s; see the install log: ssh root@$ip tail -n 50 /var/log/quiz-install.log"
  fi
  log "The quiz app is live at https://$host/; starting a 60-minute quiz"
  run ssh -o StrictHostKeyChecking=accept-new "root@$ip" make -C "$INSTALL_DIR" prod-demo ||
    die "could not start a quiz; try: ssh root@$ip make -C $INSTALL_DIR prod-demo"
  printf '\nAnother quiz: ssh root@%s make -C %s prod-demo    Delete it all: make do-destroy\n' "$ip" "$INSTALL_DIR"
}

destroy() {
  local plan="" id name ip zone record kind a b rest answer
  case ${1:-} in
    "") ;;
    --dry-run) DRY_RUN=1 ;;
    *) die "unknown option: $1" ;;
  esac
  need_doctl
  # One line per resource: its kind, the arguments that delete it, and what it is.
  while read -r id name ip; do
    [[ -n $id ]] || continue
    zone=$(dns_zone "$name")
    if [[ -n $zone ]]; then
      record=$(record_name "$name" "$zone")
      while read -r a b; do
        plan+="record $zone $a DNS A record $name -> $b"$'\n'
      done < <(doctl compute domain records list "$zone" --format ID,Type,Name,Data --no-header |
        awk -v name="$record" -v ip="$ip" '$2 == "A" && $3 == name && $4 == ip { print $1, $4 }')
    fi
    plan+="droplet $id - Droplet $name ($ip)"$'\n'
  done < <(doctl compute droplet list --tag-name "$TAG" --format ID,Name,PublicIPv4 --no-header)
  id=$(firewall_id)
  [[ -z $id ]] || plan+="firewall $id - firewall $TAG"$'\n'
  [[ -n $plan ]] || {
    log "Nothing to delete: no Droplet tagged $TAG and no firewall named $TAG"
    return 0
  }

  printf 'To delete:\n'
  while read -r kind a b rest; do printf '  %s\n' "$rest"; done <<<"${plan%$'\n'}"
  if [[ $DRY_RUN != 1 ]]; then
    read -r -p "Delete them, with the Droplet's quiz data? Type yes: " answer || true
    [[ $answer == yes ]] || die "nothing deleted"
  fi
  while read -r kind a b rest <&3; do
    case $kind in
      record) run doctl compute domain records delete "$a" "$b" --force ;;
      droplet) run doctl compute droplet delete "$a" --force ;;
      firewall) run doctl compute firewall delete "$a" --force ;;
    esac
  done 3<<<"${plan%$'\n'}"
}

case ${1:-} in
  deploy) shift && deploy "$@" ;;
  destroy) shift && destroy "$@" ;;
  *) die "usage: droplet.sh deploy [--domain NAME] [--region SLUG] [--size SLUG] [--dry-run] | destroy [--dry-run]" ;;
esac
