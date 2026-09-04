# MikroTik AI Manager

A self-hosted web app + API for discovering, monitoring, and controlling MikroTik RouterOS CPEs/antennas that sit
behind one or more top-level management routers - built for wireless ISPs running many towers, each with its own
fleet of client antennas.

## What's in here

- **Hierarchy**: add multiple **management routers** (one per tower/site), each with its own **networks** and
  **CPEs** underneath it.
- **Two discovery modes, both available at once**:
  - *Indirect*: reads a management router's own neighbor/ARP/DHCP-lease/PPPoE tables to find the CPEs behind it -
    the only option for bridge-mode antennas with no IP anything outside could reach directly.
  - *Direct IP-range scan*: give it a CIDR or IP range plus credentials and it probes every address itself and
    adopts whatever answers - one antenna per IP, no dependency on the router's tables.
- **Reaching isolated/bridge-mode CPEs** three ways, chosen per device:
  - **SOCKS relay** through the management router's own built-in SOCKS proxy (one checkbox on the router, no
    firewall changes).
  - **VPN tunnel** dialed by the app straight into the management router's LAN - **PPTP**, **L2TP**, or
    **WireGuard** (with in-app keypair generation) - so the whole remote subnet becomes reachable at the OS level.
    For PPTP/L2TP you only enter the VPN username/password; the server address is taken automatically from the
    router's own host. Which private-network ranges become reachable once connected is a separate **routing
    table** per router ("Private network routes" on the router's detail page) - add as many CIDRs as you need
    (a management VLAN, a CPE range, a PPPoE pool, ...), each routed through that tunnel; edits apply live if the
    tunnel is already up, no reconnect needed.
  - **Direct**, for CPEs with their own routable IP (e.g. PPPoE clients with internet).
  - **MAC-Telnet**, by MAC address instead of IP - the same tool a technician runs from a laptop on the antenna's
    own segment. Discovery via a router's tables already captures every CPE's MAC; use it from a CPE's detail
    page to test reachability or run the connectivity test below when there's no usable IP yet. Only works when
    this app itself has layer-2 reachability to that CPE's segment (not over the internet or a routed VPN).
- **Client connectivity test**: on a CPE's detail page, runs the field-technician checklist (radio: sector,
  SNR, signal, V/H chain balance, uptime, BTS link time, firmware match against the tower, disconnect count,
  ethernet link speed; network: ping to the PPPoE gateway/8.8.8.8/a domain, and RouterOS's own bandwidth-test
  toward your internal speed-test server) automatically over IP or MAC-Telnet, with pass/fail coloring against
  the checklist's own thresholds. Whatever can't be automated - power-cycling the PoE injector, a TP-Link
  router's own speed test, the client PC's fast.com result - is left for you to paste in afterward; every run is
  saved with history.
- **Monitoring & prediction**: CPU/memory/signal/CCQ/ping polled on a schedule, stored as time series, and turned
  into alerts three ways layered together - fixed-threshold rules, linear-regression trend prediction ("signal
  trending down, ~3 days to failure"), and IsolationForest anomaly detection over metric history - with an
  optional LLM (OpenAI or Anthropic, your own key) adding a plain-language explanation on top of the rule-based
  finding. None of the three replace each other; they all feed the same alert feed.
- **AI Assistant** (`/assistant`): a chat page that can search/inspect your fleet on its own (devices, alerts,
  routers, networks) and, if you ask it to change or run something, always stops and **proposes** an exact
  RouterOS script + target device(s) for you to review and confirm - it is never given a tool that executes
  directly. Confirming runs it through the same audited endpoint (`POST /api/scripts/run`) a human action would
  use, including on a single CPE, a list of CPEs, a whole network, everything under a router, or every monitored
  CPE (bulk runs need an explicit `confirm: true`, both from the API and via the UI's confirm button).
- **Firmware push**: upload a `.npk`, push it to any CPE - including bridge-mode ones with no direct internet,
  via SFTP over the same SOCKS relay/VPN path used for everything else - then it reboots the device and waits for
  it to come back, reporting the new version.
- **Config backup & restore**: pull a timestamped `/system/backup` off any router or CPE via SFTP at any time.
  Restore pushes a chosen backup back onto its device and tells RouterOS to load it (the device reboots on its
  own to apply it). Turn on **auto-restore on reconnect** on a CPE's detail page and this happens automatically
  the moment that CPE is seen coming back online after being offline - handy for a factory-reset or physically
  swapped antenna in the field coming back up as itself again, with no one having to notice and click restore.
- **PPPoE credential backup**: a read-only, encrypted-at-rest mirror of a router's PPP secrets (username/password/
  profile), synced on demand, exportable as CSV - so you're never locked out of your customer credential list if
  a router's config is ever lost.
- **Security**: username/password login, JWT sessions, default `admin`/`admin` account that forces a password
  change on first login, admin/operator/technician roles, and as many additional accounts as you want. Every
  device credential, PPPoE secret, and VPN password is encrypted at rest (Fernet/AES). Every write action is
  audit-logged.
- **Dashboard**: live counts across routers/CPEs/alerts, per-router breakdown, recent alerts - built as a single
  React SPA served by the same container on one port.

## Architecture

```
frontend/   React (Vite) + Tailwind - builds to backend/static, served by FastAPI itself (one container, one port)
backend/
  app/
    api/routes/   FastAPI routers (auth, management-routers, networks, cpes, discovery, alerts, firmware,
                  config-backups, pppoe, jobs, scripts, assistant, settings, users, dashboard, connectivity-tests)
    core/         config, DB session, JWT/password hashing, Fernet encryption, scheduler
    models/       SQLAlchemy models (SQLite by default; point DATABASE_URL at Postgres to scale further)
    services/     RouterOS client (REST + binary API, both SOCKS-relayable), MAC-Telnet client, discovery,
                  polling, prediction/ML, firmware push, config backup/restore, PPPoE sync, VPN tunnel lifecycle,
                  the client connectivity test, AI assistant/tools
    ml/           trend regression + IsolationForest anomaly detection
  scripts/        ppp-ip-up.sh / ppp-ip-down.sh - installed into the image so PPTP/L2TP tunnels get their routes
Dockerfile          multi-stage: builds the frontend, then a slim Python 3.11 runtime with the VPN packages
docker-compose.yml  one service, a named volume for all persistent data, NET_ADMIN + /dev/ppp for the VPN feature
```

Everything - REST API, binary API fallback for older RouterOS, SOCKS relaying, SFTP transfers, and the VPN
tunnels - funnels through one connector (`app/services/routeros_client.py` + `device_connect.py`), so every
feature (polling, firmware push, backup/restore, script execution) reaches a CPE the same way regardless of
which of the three connectivity modes that device is configured for.

## Testing performed before delivery

This was built and tested in a sandboxed environment with no access to a real MikroTik device or to your Oracle
Cloud instance, so testing here means: a hand-built mock RouterOS REST server (with TLS), a mock SOCKS5 relay, and
a mock SFTP server, all exercised through the real, running application over real HTTP - not just code review.
Verified working end-to-end this way: login and forced first-password-change, creating routers/networks/CPEs,
both discovery modes (including MAC-address capture from neighbor/ARP/DHCP/PPPoE tables), polling with real
threshold-crossing alerts firing and clearing, firmware push (upload, SFTP transfer with integrity check, reboot,
recovery poll), config backup pull, **config restore both on-demand and automatically on reconnect** (including
the audit trail and the CPE's `last_restore_job_id` updating), PPPoE secret sync/export, ad-hoc RouterOS script
execution (single CPE and confirmed bulk, with the unconfirmed-bulk guard), and the AI Assistant's tool-calling
loop for both OpenAI- and Anthropic-shaped responses (read-only tool dispatch against the real DB, and the
propose-then-confirm flow) using mocked LLM responses, since no API key was available in this environment. The
full React frontend was built and driven through a real headless browser against the live backend - every page,
the VPN configuration UI, running a script and restoring a backup from the CPE detail page, and the AI
Assistant's "not configured" state all rendered and worked with zero console errors.

Also verified this same way, in a later round: the private-network routing table (add/list/delete a CIDR against
a router, including the multi-CIDR PPTP/L2TP hook-script logic exercised directly with a stubbed `ip` command),
the simplified PPTP/L2TP VPN form (server address auto-derived from the router's host), and the full client
connectivity test - radio-field extraction (SNR/V-H-ratio/registration status/sector) and ping/bandwidth-test
result parsing were unit-tested directly against realistic RouterOS output text, disconnect-count and
firmware-alignment logic were verified against real DB rows, and the whole flow (run test, view results with
pass/fail coloring, fill in the manual fields, save) was driven through a real headless browser with zero console
errors. MAC-Telnet's failure path was verified against the real `mactelnet` client (installed and exercised in
this environment) reaching a non-existent device - it times out and reports a clear error rather than hanging;
reaching a **real** CPE over MAC-Telnet could not be tested here since that needs an actual device to talk to.

**What could not be tested here**: an actual `docker build` - this environment's network policy blocks container
registry access (Docker Hub), so the image itself has never been built or run. The Dockerfile was checked
carefully by hand and its structure validated with a parser, `docker compose config` validates the compose file
cleanly, and every piece it depends on (the exact pinned Python packages, the frontend build output path, the
system VPN packages) was verified independently in this same environment - but the first real build is on your
server. If `docker compose up -d --build` hits any error, send it back and it'll get fixed.

## Installing on your Oracle Cloud instance

1. **Get the code onto the instance.** Either push this project to your own GitHub repo and clone it there, or
   `scp`/copy the folder directly - see "What to put in your GitHub repo" below either way.

   ```bash
   git clone https://github.com/<you>/<your-repo>.git mikrotik-ai-manager
   cd mikrotik-ai-manager
   ```

2. **Create your `.env`** from the template and fill in real values:

   ```bash
   cp .env.example .env
   nano .env   # set SECRET_KEY at minimum - see the comments in the file
   ```

   Generate a `SECRET_KEY` with `openssl rand -base64 32`. If you leave it unset, one is generated randomly on
   every container start, which logs everyone out on every restart/redeploy - fine for a quick test, not for
   real use.

3. **Build and start it:**

   ```bash
   docker compose up -d --build
   ```

   First boot creates the SQLite database and a default `admin` account with password `admin`, and generates the
   credential-encryption key if you didn't set `ENCRYPTION_KEY` - both land in the `mikrotik_data` Docker volume,
   which is what persists across restarts/redeploys. **Back this volume up** (`docker run --rm -v
   mikrotik-ai-manager_mikrotik_data:/data -v $(pwd):/backup alpine tar czf /backup/mikrotik-data-backup.tgz
   /data` is a quick way) - losing it means losing every stored device credential, not just data.

4. **Open the port.** Two separate firewalls both need this on Oracle Cloud - missing either one leaves the app
   unreachable from outside:

   - **The instance's own OS firewall** (Oracle's Ubuntu/Oracle Linux images ship `iptables`/`firewalld` rules
     that block everything but SSH by default):
     ```bash
     # Ubuntu (iptables):
     sudo iptables -I INPUT -p tcp --dport 8008 -j ACCEPT
     sudo netfilter-persistent save   # or: sudo apt install iptables-persistent, then save

     # Oracle Linux (firewalld):
     sudo firewall-cmd --permanent --add-port=8008/tcp
     sudo firewall-cmd --reload
     ```
   - **The Oracle Cloud Security List / Network Security Group** for the VCN your instance is in (Console:
     *Networking → Virtual Cloud Networks → (your VCN) → Security Lists* or *Network Security Groups*): add an
     **Ingress Rule** - Source CIDR `0.0.0.0/0` (or your own IP range if you want it private), IP Protocol TCP,
     Destination Port Range `8008`.

   If you'd rather not expose 8008 directly, put a reverse proxy (Caddy/nginx/Cloudflare Tunnel) in front with
   TLS and only open 443 in both firewalls instead - the app doesn't care either way, it just needs to be
   reached on the port `PORT` in `.env` (8008 by default).

5. **Log in** at `http://<your-instance-ip>:8008` with `admin` / `admin` and set a real password immediately -
   the app forces this before letting you do anything else.

6. **Add your first management router** (Management Routers → Add router), point it at one of your towers, then
   run a discovery scan or an IP-range scan from its detail page to pull in its CPEs.

### If you don't use the VPN tunnel feature

The `cap_add: NET_ADMIN` and `devices: /dev/ppp` lines in `docker-compose.yml` are only needed for the PPTP/L2TP/
WireGuard VPN tunnel feature. SOCKS relay and direct/IP-range-scanned CPEs work fully without them - if you know
you won't use VPN tunnels, you can delete both lines for a slightly more locked-down container. If you do use
PPTP or L2TP, the host kernel needs the `ppp_generic` module loaded (`sudo modprobe ppp_generic` - most cloud
Ubuntu/Oracle Linux images have this already); WireGuard doesn't need this.

### MAC-Telnet reachability

The Dockerfile installs the `mactelnet` client (apt package `mactelnet-client`) so CPEs can be reached by MAC
address instead of IP. Two things worth knowing: the package name/availability can drift between base-image
releases, so that install step is deliberately non-fatal - if it's missing on your build, everything else in the
app still works, only MAC-Telnet won't be available until you install it by hand in the container. More
importantly, MAC-Telnet is a **layer-2** protocol - it only works when this app has broadcast-domain reachability
to a CPE's own network segment (e.g. the app runs on the same LAN/backhaul ring as your towers, or a tower
bridges that segment to the app over something like EoIP). It will not work over the public internet, through
the SOCKS relay, or across the PPTP/L2TP/WireGuard tunnels this app dials (those are all routed layer-3 tunnels,
not layer-2 bridges) - for those situations, use IP-based reachability instead.

### Switching from SQLite to Postgres later

Set `DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname` in `.env`, add a `psycopg[binary]` line to
`backend/requirements.txt`, and rebuild. SQLite comfortably handles thousands of devices on a small VM - only
switch if you outgrow it.

## What to put in your GitHub repo

Commit everything except what's in `.gitignore` (already set up for you): that excludes `.env` itself (secrets),
`backend/data/` (the SQLite DB, encryption key, firmware files, backups - all runtime state, not code),
`backend/static/` (the frontend build output - regenerated by the Docker build), and the usual
`node_modules/`/`__pycache__/`/venv noise.

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<you>/<your-repo>.git
git push -u origin main
```

Then on your Oracle Cloud instance, `git clone` that repo, add your own `.env` (never commit it - it's already
gitignored), and `docker compose up -d --build`. To deploy an update later: push to GitHub, then on the instance
`git pull && docker compose up -d --build` - your data stays in the `mikrotik_data` volume across rebuilds.

## Everyday use notes

- **AI features** (LLM alert explanations + the Assistant chat page) are optional and off until you set an LLM
  provider and API key on the Settings page (admin-only) - everything else works without one.
- **Auto-restore on reconnect** is per-CPE (its detail page, or `PATCH /api/cpes/{id}` with
  `auto_restore_on_reconnect: true`) and needs at least one backup already taken for that CPE - it restores the
  most recent one.
- **Running scripts on many devices at once** (via the API directly, or the AI Assistant's proposals) requires
  `confirm: true` once the resolved target list is more than one device - a safety guard against an accidental
  fleet-wide command.
- Default poll interval is 60 seconds with a concurrency cap of 25 simultaneous device connections
  (`POLL_INTERVAL_FAST_SECONDS` / `POLL_CONCURRENCY` in Settings/env) - tuned to stay light on a small VM even
  with thousands of devices; raise the concurrency if your instance has the headroom and you want faster sweeps.

## Suggested next additions (not built - just ideas)

- Push notifications to a mobile device (webhook + Telegram are already wired up in Settings; a native push
  channel would be a small addition on top of the same `notify_alert` call).
- Per-network or per-router alert thresholds instead of global ones.
- A map view (lat/long per CPE) for towers with many antennas spread over a wide area.
