#!/bin/sh
# Installed as /etc/ppp/ip-down.d/99-app-tunnel by the Docker image.
# Mirrors ppp-ip-up.sh: removes the route we added and the "tunnel is up"
# marker file so the app notices the link dropped.
set -e

IFACE="$1"
IPPARAM="$6"
RUNDIR="/run/vpn-tunnels"
CIDR_FILE="$RUNDIR/$IPPARAM.cidr"
UP_FILE="$RUNDIR/$IPPARAM.up"

if [ -f "$CIDR_FILE" ]; then
  CIDR=$(cat "$CIDR_FILE")
  if [ -n "$CIDR" ]; then
    ip route del "$CIDR" dev "$IFACE" 2>/dev/null || true
  fi
fi

rm -f "$UP_FILE"
exit 0
