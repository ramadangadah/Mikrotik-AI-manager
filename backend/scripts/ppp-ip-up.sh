#!/bin/sh
# Installed as /etc/ppp/ip-up.d/99-app-tunnel by the Docker image.
# pppd calls every script in ip-up.d with:
#   $1=interface $2=tty $3=speed $4=local-IP $5=remote-IP $6=ipparam
#
# We use $6 (ipparam, set by vpn_service.py to a unique tag per management
# router) to find a small file telling us which LAN CIDR should be routed
# through this tunnel, add that route, and drop a marker file the app polls
# for to know the tunnel is up and which interface it landed on.
set -e

IFACE="$1"
IPPARAM="$6"
RUNDIR="/run/vpn-tunnels"
CIDR_FILE="$RUNDIR/$IPPARAM.cidr"
UP_FILE="$RUNDIR/$IPPARAM.up"

mkdir -p "$RUNDIR"

if [ -f "$CIDR_FILE" ]; then
  CIDR=$(cat "$CIDR_FILE")
  if [ -n "$CIDR" ]; then
    ip route replace "$CIDR" dev "$IFACE" 2>/tmp/ppp-ip-up-route-error.log || true
  fi
fi

echo "$IFACE" > "$UP_FILE"
exit 0
