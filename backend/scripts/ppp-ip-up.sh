#!/bin/sh
# Installed as /etc/ppp/ip-up.d/99-app-tunnel by the Docker image.
# pppd calls every script in ip-up.d with:
#   $1=interface $2=tty $3=speed $4=local-IP $5=remote-IP $6=ipparam
#
# We use $6 (ipparam, set by vpn_service.py to a unique tag per management
# router) to find a small file listing which private-network CIDRs (one per
# line - the router's "Private network routes" table) should be routed
# through this tunnel, add a route for each, and drop a marker file the app
# polls for to know the tunnel is up and which interface it landed on.
set -e

IFACE="$1"
IPPARAM="$6"
RUNDIR="/run/vpn-tunnels"
CIDR_FILE="$RUNDIR/$IPPARAM.cidr"
UP_FILE="$RUNDIR/$IPPARAM.up"

mkdir -p "$RUNDIR"

if [ -f "$CIDR_FILE" ]; then
  while IFS= read -r CIDR || [ -n "$CIDR" ]; do
    [ -n "$CIDR" ] || continue
    ip route replace "$CIDR" dev "$IFACE" 2>>/tmp/ppp-ip-up-route-error.log || true
  done < "$CIDR_FILE"
fi

echo "$IFACE" > "$UP_FILE"
exit 0
