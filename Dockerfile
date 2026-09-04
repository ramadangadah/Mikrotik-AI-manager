# ---- Stage 1: build the React frontend -------------------------------
# vite.config.js's build.outDir is "../backend/static" (relative to
# frontend/), so this stage mirrors the repo's frontend/ + backend/ layout
# under /src rather than building into an arbitrary path - that keeps this
# Dockerfile in lockstep with `npm run build` run locally in frontend/,
# with nothing to keep in sync by hand.
FROM node:20-slim AS frontend-build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY frontend ./frontend
RUN mkdir -p backend && cd frontend && npm run build

# ---- Stage 2: Python runtime -------------------------------------------
FROM python:3.11-slim AS runtime

# System packages:
#   ppp, pptp-linux, xl2tpd, wireguard-tools - the VPN tunnel types
#     (vpn_service.py shells out to pppd/pptp/xl2tpd/wg/wg-quick).
#   iproute2 - `ip route` used by the ppp ip-up/ip-down hook scripts below
#     and by wg-quick to add the tunnel's routes.
# Kept to just these + curl (container healthcheck) - this is meant to run
# light on a small VM, not as a general-purpose networking box.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ppp \
        pptp-linux \
        xl2tpd \
        wireguard-tools \
        iproute2 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# mactelnet-client - the `mactelnet` CLI, used by mactelnet_service.py to
# reach a CPE by MAC address (layer 2) instead of IP, e.g. for a bridge-mode
# antenna with no usable IP yet. Confirmed present in Ubuntu 24.04's
# universe repo; Debian (this image's base) has carried the same source
# package for years too, but package names/availability can drift between
# base-image releases - this is deliberately non-fatal to the rest of the
# build (`|| true`) so a missing/renamed package here never breaks the app
# itself, it just means the MAC-Telnet path (IP-based reachability is
# unaffected either way) won't be available until it's installed by hand.
RUN apt-get update && apt-get install -y --no-install-recommends mactelnet-client \
    && rm -rf /var/lib/apt/lists/* \
    || echo "WARNING: mactelnet-client package not found for this base image - MAC-Telnet CPE access will be unavailable. Install it manually (or check the exact package name for your distro) if you need it."

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY --from=frontend-build /src/backend/static ./static

# pppd runs every executable script in these directories on link up/down;
# see scripts/ppp-ip-up.sh and ppp-ip-down.sh for what they do (add/remove
# the route for a management router's LAN CIDR through the new tunnel
# interface, and drop a marker file vpn_service.py polls for tunnel status).
RUN mkdir -p /etc/ppp/ip-up.d /etc/ppp/ip-down.d /run/vpn-tunnels /etc/wireguard \
    && cp scripts/ppp-ip-up.sh /etc/ppp/ip-up.d/99-app-tunnel \
    && cp scripts/ppp-ip-down.sh /etc/ppp/ip-down.d/99-app-tunnel \
    && chmod +x /etc/ppp/ip-up.d/99-app-tunnel /etc/ppp/ip-down.d/99-app-tunnel

# Persisted at runtime via a volume - see docker-compose.yml. Created here
# too so the app still boots fine if someone runs the image without one
# (ephemeral data, but never a crash-on-missing-directory).
RUN mkdir -p /app/data

EXPOSE 8008

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8008/api/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008"]
