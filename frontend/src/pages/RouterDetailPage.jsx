import React, { useEffect, useState, useCallback } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Plus, Search, ScanLine, KeyRound, Archive, CheckSquare, Square, Shield, Plug, PlugZap, Copy } from "lucide-react";
import api from "../api/client.js";
import { StatusBadge } from "../components/Badges.jsx";

function VpnSection({ router, onChange }) {
  const [form, setForm] = useState({
    vpn_type: router.vpn_type, vpn_username: router.vpn_username || "",
    vpn_password: "",
    wg_peer_public_key: router.wg_peer_public_key || "", wg_preshared_key: "",
    wg_endpoint_port: router.wg_endpoint_port, wg_local_address: router.wg_local_address || "", wg_keepalive: router.wg_keepalive,
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function saveConfig(e) {
    e.preventDefault();
    setBusy(true);
    setMsg("");
    try {
      const payload = { ...form, wg_endpoint_port: Number(form.wg_endpoint_port), wg_keepalive: Number(form.wg_keepalive) };
      if (!payload.vpn_password) delete payload.vpn_password;
      if (!payload.wg_preshared_key) delete payload.wg_preshared_key;
      const res = await api.patch(`/management-routers/${router.id}`, payload);
      onChange(res.data);
      setMsg("VPN config saved.");
    } catch (err) {
      setMsg(err.response?.data?.detail || "Failed to save VPN config");
    } finally {
      setBusy(false);
    }
  }

  async function generateKeys() {
    setBusy(true);
    setMsg("");
    try {
      const res = await api.post(`/management-routers/${router.id}/vpn/generate-wireguard-keys`);
      onChange(res.data);
      setMsg("Keypair generated - copy the public key below into this router's WireGuard peer config.");
    } catch (err) {
      setMsg(err.response?.data?.detail || "Failed to generate keys");
    } finally {
      setBusy(false);
    }
  }

  async function connect() {
    setBusy(true);
    setMsg("Connecting...");
    try {
      const res = await api.post(`/management-routers/${router.id}/vpn/connect`);
      onChange(res.data);
      setMsg(`Status: ${res.data.vpn_status}${res.data.vpn_interface ? ` (${res.data.vpn_interface})` : ""}`);
    } catch (err) {
      setMsg(err.response?.data?.detail || "Connect failed");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setMsg("Disconnecting...");
    try {
      const res = await api.post(`/management-routers/${router.id}/vpn/disconnect`);
      onChange(res.data);
      setMsg("Disconnected.");
    } catch (err) {
      setMsg(err.response?.data?.detail || "Disconnect failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-medium text-slate-100 flex items-center gap-2">
          <Shield size={15} /> VPN tunnel into this router's LAN
        </h2>
        <div className="flex items-center gap-2">
          <span className={`badge ${router.vpn_status === "connected" ? "badge-online" : router.vpn_status === "error" ? "badge-offline" : "badge-unknown"}`}>
            {router.vpn_status}{router.vpn_interface ? ` · ${router.vpn_interface}` : ""}
          </span>
          {router.vpn_status === "connected" ? (
            <button className="btn btn-secondary" onClick={disconnect} disabled={busy}><Plug size={14} /> Disconnect</button>
          ) : (
            <button className="btn btn-secondary" onClick={connect} disabled={busy || form.vpn_type === "none"}><PlugZap size={14} /> Connect</button>
          )}
        </div>
      </div>
      <p className="text-xs text-muted -mt-2">
        Dials PPTP, L2TP, or WireGuard from the app straight into this router's own LAN, so its whole subnet
        becomes reachable at the OS level - useful when isolated CPEs need reaching some other way than the
        router's SOCKS proxy.
      </p>
      {router.vpn_last_error && <div className="text-xs text-crit">{router.vpn_last_error}</div>}

      <form onSubmit={saveConfig} className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="label">VPN type</label>
          <select className="input" value={form.vpn_type} onChange={(e) => setForm({ ...form, vpn_type: e.target.value })}>
            <option value="none">None</option>
            <option value="pptp">PPTP</option>
            <option value="l2tp">L2TP</option>
            <option value="wireguard">WireGuard</option>
          </select>
        </div>

        {(form.vpn_type === "pptp" || form.vpn_type === "l2tp") && (
          <>
            <div className="md:col-span-3 text-xs text-muted -mt-1">
              Connects to this router's own address ({router.host}) as the PPTP/L2TP server - just enter the
              VPN username/password configured on the router's PPP secrets and hit Connect. Which private
              networks become reachable once connected is set below, under "Private network routes".
            </div>
            <div>
              <label className="label">VPN username</label>
              <input className="input" value={form.vpn_username} onChange={(e) => setForm({ ...form, vpn_username: e.target.value })} />
            </div>
            <div>
              <label className="label">VPN password {router.vpn_username && <span className="text-muted">(blank = keep current)</span>}</label>
              <input className="input" type="password" value={form.vpn_password} onChange={(e) => setForm({ ...form, vpn_password: e.target.value })} />
            </div>
          </>
        )}

        {form.vpn_type === "wireguard" && (
          <>
            <div className="md:col-span-3 text-xs text-muted -mt-1">
              Which private networks become reachable once connected is set below, under "Private network routes".
            </div>
            <div>
              <label className="label">Endpoint port</label>
              <input className="input" type="number" value={form.wg_endpoint_port} onChange={(e) => setForm({ ...form, wg_endpoint_port: e.target.value })} />
            </div>
            <div>
              <label className="label">This app's tunnel address</label>
              <input className="input" value={form.wg_local_address} onChange={(e) => setForm({ ...form, wg_local_address: e.target.value })} placeholder="10.99.0.2/24" />
            </div>
            <div>
              <label className="label">Router's WireGuard public key (peer)</label>
              <input className="input" value={form.wg_peer_public_key} onChange={(e) => setForm({ ...form, wg_peer_public_key: e.target.value })} />
            </div>
            <div>
              <label className="label">Preshared key (optional)</label>
              <input className="input" type="password" value={form.wg_preshared_key} onChange={(e) => setForm({ ...form, wg_preshared_key: e.target.value })} />
            </div>
            <div>
              <label className="label">Keepalive (seconds)</label>
              <input className="input" type="number" value={form.wg_keepalive} onChange={(e) => setForm({ ...form, wg_keepalive: e.target.value })} />
            </div>
            <div className="md:col-span-3 flex items-center gap-3">
              <button type="button" className="btn btn-secondary" onClick={generateKeys} disabled={busy}>Generate this app's keypair</button>
              {router.wg_public_key && (
                <div className="flex items-center gap-2 text-xs text-muted">
                  <span>App public key (paste into the router's WireGuard peer): </span>
                  <code className="text-slate-300 bg-panel2 px-2 py-0.5 rounded">{router.wg_public_key}</code>
                  <button type="button" className="text-accent" onClick={() => navigator.clipboard.writeText(router.wg_public_key)} title="Copy">
                    <Copy size={12} />
                  </button>
                </div>
              )}
            </div>
          </>
        )}

        {msg && <div className="md:col-span-3 text-xs text-muted">{msg}</div>}
        {form.vpn_type !== "none" && (
          <div className="md:col-span-3">
            <button className="btn btn-primary" disabled={busy}>Save VPN config</button>
          </div>
        )}
      </form>
    </div>
  );
}

function RoutesSection({ router }) {
  const [routes, setRoutes] = useState([]);
  const [form, setForm] = useState({ cidr: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    const res = await api.get(`/management-routers/${router.id}/routes`);
    setRoutes(res.data);
  }, [router.id]);

  useEffect(() => { load(); }, [load]);

  async function addRoute(e) {
    e.preventDefault();
    if (!form.cidr.trim()) return;
    setBusy(true);
    setMsg("");
    try {
      await api.post(`/management-routers/${router.id}/routes`, form);
      setForm({ cidr: "", description: "" });
      await load();
      if (router.vpn_status === "connected") setMsg("Route added and applied to the live tunnel.");
    } catch (err) {
      setMsg(err.response?.data?.detail || "Failed to add route");
    } finally {
      setBusy(false);
    }
  }

  async function removeRoute(routeId) {
    setBusy(true);
    setMsg("");
    try {
      await api.delete(`/management-routers/${router.id}/routes/${routeId}`);
      await load();
    } catch (err) {
      setMsg(err.response?.data?.detail || "Failed to remove route");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-5 space-y-4">
      <h2 className="font-medium text-slate-100">Private network routes</h2>
      <p className="text-xs text-muted -mt-2">
        Private-network ranges reachable through this router's tunnel, and what each one is for. Every CIDR
        listed here is routed through the VPN tunnel above once it's connected - add one row per subnet (a
        management VLAN, a CPE range, a PPPoE pool, etc). Changes apply immediately if the tunnel is already up.
      </p>

      {routes.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted border-b border-panel2">
              <th className="py-1.5 pr-3">CIDR</th>
              <th className="py-1.5 pr-3">Description</th>
              <th className="py-1.5 w-10"></th>
            </tr>
          </thead>
          <tbody>
            {routes.map((r) => (
              <tr key={r.id} className="border-b border-panel2/60">
                <td className="py-1.5 pr-3 font-mono text-slate-200">{r.cidr}</td>
                <td className="py-1.5 pr-3 text-muted">{r.description || "—"}</td>
                <td className="py-1.5">
                  <button className="text-crit" disabled={busy} onClick={() => removeRoute(r.id)} title="Remove">
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <form onSubmit={addRoute} className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div>
          <label className="label">CIDR</label>
          <input className="input" placeholder="10.20.30.0/24" value={form.cidr}
            onChange={(e) => setForm({ ...form, cidr: e.target.value })} />
        </div>
        <div className="md:col-span-2">
          <label className="label">Description (optional)</label>
          <input className="input" placeholder="Tower management VLAN" value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </div>
        <div className="flex items-end">
          <button className="btn btn-secondary w-full" disabled={busy}><Plus size={14} /> Add route</button>
        </div>
      </form>
      {msg && <div className="text-xs text-muted">{msg}</div>}
    </div>
  );
}

export default function RouterDetailPage() {
  const { id } = useParams();
  const [router, setRouter] = useState(null);
  const [networks, setNetworks] = useState([]);
  const [cpes, setCpes] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [busyMsg, setBusyMsg] = useState("");
  const [showNetForm, setShowNetForm] = useState(false);
  const [netForm, setNetForm] = useState({ name: "", cidr: "" });
  const [showScanForm, setShowScanForm] = useState(false);
  const [scanForm, setScanForm] = useState({
    ip_range: "", username: "admin", password: "", port: 443, api_type: "rest", use_relay: false,
  });
  const [showAdoptForm, setShowAdoptForm] = useState(false);
  const [adoptForm, setAdoptForm] = useState({ username: "admin", password: "", connection_mode: "socks_relay" });

  const load = useCallback(async () => {
    const [r, n, c] = await Promise.all([
      api.get(`/management-routers/${id}`),
      api.get("/networks", { params: { management_router_id: id } }),
      api.get("/cpes", { params: { management_router_id: id } }),
    ]);
    setRouter(r.data);
    setNetworks(n.data);
    setCpes(c.data);
  }, [id]);

  useEffect(() => { load(); }, [load]);

  async function createNetwork(e) {
    e.preventDefault();
    await api.post("/networks", { management_router_id: Number(id), name: netForm.name, cidr: netForm.cidr || null });
    setNetForm({ name: "", cidr: "" });
    setShowNetForm(false);
    await load();
  }

  async function runDiscoveryScan() {
    setBusyMsg("Scanning via neighbor/ARP/DHCP/PPPoE tables...");
    try {
      const res = await api.post(`/discovery/${id}/scan`, {});
      setBusyMsg(`Found ${res.data.scanned} devices (${res.data.created} new, ${res.data.updated} updated).`);
      await load();
    } catch (err) {
      setBusyMsg(err.response?.data?.detail || "Discovery failed");
    }
  }

  async function runIpRangeScan(e) {
    e.preventDefault();
    setBusyMsg("Probing IP range directly...");
    try {
      const res = await api.post(`/discovery/${id}/ip-range-scan`, {
        ...scanForm, port: Number(scanForm.port),
      });
      setBusyMsg(`Scanned ${res.data.addresses_scanned} addresses, ${res.data.responded} responded (${res.data.created} new, ${res.data.updated} updated).`);
      setShowScanForm(false);
      await load();
    } catch (err) {
      setBusyMsg(err.response?.data?.detail || "Scan failed");
    }
  }

  async function bulkAdopt(e) {
    e.preventDefault();
    if (selected.size === 0) return;
    await api.post("/cpes/bulk-adopt", { cpe_ids: [...selected], ...adoptForm });
    setSelected(new Set());
    setShowAdoptForm(false);
    await load();
  }

  async function syncPppoe() {
    setBusyMsg("Syncing PPPoE secrets...");
    try {
      const res = await api.post(`/pppoe/sync/${id}`);
      setBusyMsg(`Synced ${res.data.total_on_router} secrets (${res.data.created} new, ${res.data.updated} updated).`);
    } catch (err) {
      setBusyMsg(err.response?.data?.detail || "Sync failed");
    }
  }

  async function backupNow() {
    setBusyMsg("Pulling config backup...");
    try {
      await api.post(`/config-backups/management-router/${id}`);
      setBusyMsg("Backup saved.");
    } catch (err) {
      setBusyMsg(err.response?.data?.detail || "Backup failed");
    }
  }

  function toggleSelect(cpeId) {
    setSelected((s) => {
      const next = new Set(s);
      next.has(cpeId) ? next.delete(cpeId) : next.add(cpeId);
      return next;
    });
  }

  if (!router) return <div className="text-muted">Loading...</div>;

  const cpesByNetwork = networks.map((n) => ({ network: n, items: cpes.filter((c) => c.network_id === n.id) }));

  return (
    <div className="space-y-6">
      <Link to="/routers" className="inline-flex items-center gap-1 text-sm text-muted hover:text-slate-200">
        <ArrowLeft size={14} /> Management routers
      </Link>

      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-slate-100">{router.name}</h1>
            <StatusBadge status={router.status} />
          </div>
          <p className="text-sm text-muted mt-0.5">
            {router.host}:{router.port} · {router.identity || "unknown identity"} · RouterOS {router.routeros_version || "?"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn btn-secondary" onClick={runDiscoveryScan}>
            <Search size={14} /> Discover via router tables
          </button>
          <button className="btn btn-secondary" onClick={() => setShowScanForm((s) => !s)}>
            <ScanLine size={14} /> Scan IP range directly
          </button>
          <button className="btn btn-secondary" onClick={syncPppoe}>
            <KeyRound size={14} /> Sync PPPoE
          </button>
          <button className="btn btn-secondary" onClick={backupNow}>
            <Archive size={14} /> Backup now
          </button>
        </div>
      </div>

      {busyMsg && <div className="card p-3 text-sm text-slate-300">{busyMsg}</div>}

      <VpnSection router={router} onChange={setRouter} />
      <RoutesSection router={router} />

      {showScanForm && (
        <form onSubmit={runIpRangeScan} className="card p-5 grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-3 text-sm text-muted -mt-1 mb-1">
            Tries these credentials against every address in the range and adopts whatever answers - one antenna per
            IP, no dependency on this router's own tables.
          </div>
          <div>
            <label className="label">IP range</label>
            <input className="input" required placeholder="10.10.0.0/24 or 10.10.0.1-10.10.0.50"
              value={scanForm.ip_range} onChange={(e) => setScanForm({ ...scanForm, ip_range: e.target.value })} />
          </div>
          <div>
            <label className="label">Username</label>
            <input className="input" required value={scanForm.username} onChange={(e) => setScanForm({ ...scanForm, username: e.target.value })} />
          </div>
          <div>
            <label className="label">Password</label>
            <input className="input" type="password" required value={scanForm.password} onChange={(e) => setScanForm({ ...scanForm, password: e.target.value })} />
          </div>
          <div>
            <label className="label">Port</label>
            <input className="input" type="number" value={scanForm.port} onChange={(e) => setScanForm({ ...scanForm, port: e.target.value })} />
          </div>
          <div>
            <label className="label">API type</label>
            <select className="input" value={scanForm.api_type} onChange={(e) => setScanForm({ ...scanForm, api_type: e.target.value })}>
              <option value="rest">REST</option>
              <option value="api-ssl">Binary API (TLS)</option>
              <option value="api">Binary API</option>
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300 self-end">
            <input type="checkbox" checked={scanForm.use_relay} onChange={(e) => setScanForm({ ...scanForm, use_relay: e.target.checked })} />
            Reach via this router's SOCKS relay instead of directly
          </label>
          <div className="md:col-span-3">
            <button className="btn btn-primary">Scan & adopt</button>
          </div>
        </form>
      )}

      {networks.length === 0 ? (
        <div className="card p-6 text-center text-muted text-sm">
          No networks yet. Run a discovery scan above, or{" "}
          <button className="text-accent" onClick={() => setShowNetForm(true)}>create one manually</button>.
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <h2 className="font-medium text-slate-100">Networks & CPEs</h2>
        <div className="flex items-center gap-2">
          {selected.size > 0 && (
            <button className="btn btn-secondary" onClick={() => setShowAdoptForm((s) => !s)}>
              Adopt {selected.size} selected
            </button>
          )}
          <button className="btn btn-secondary" onClick={() => setShowNetForm((s) => !s)}>
            <Plus size={14} /> Network
          </button>
        </div>
      </div>

      {showNetForm && (
        <form onSubmit={createNetwork} className="card p-4 flex gap-3 items-end">
          <div className="flex-1">
            <label className="label">Name</label>
            <input className="input" required value={netForm.name} onChange={(e) => setNetForm({ ...netForm, name: e.target.value })} />
          </div>
          <div className="flex-1">
            <label className="label">CIDR (optional)</label>
            <input className="input" value={netForm.cidr} onChange={(e) => setNetForm({ ...netForm, cidr: e.target.value })} placeholder="10.10.1.0/24" />
          </div>
          <button className="btn btn-primary">Create</button>
        </form>
      )}

      {showAdoptForm && (
        <form onSubmit={bulkAdopt} className="card p-4 grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <div>
            <label className="label">Username</label>
            <input className="input" required value={adoptForm.username} onChange={(e) => setAdoptForm({ ...adoptForm, username: e.target.value })} />
          </div>
          <div>
            <label className="label">Password</label>
            <input className="input" type="password" required value={adoptForm.password} onChange={(e) => setAdoptForm({ ...adoptForm, password: e.target.value })} />
          </div>
          <div>
            <label className="label">Connection mode</label>
            <select className="input" value={adoptForm.connection_mode} onChange={(e) => setAdoptForm({ ...adoptForm, connection_mode: e.target.value })}>
              <option value="socks_relay">Via SOCKS relay (isolated/bridge-mode)</option>
              <option value="direct">Direct</option>
              <option value="vpn_tunnel">Via VPN tunnel (router's LAN)</option>
            </select>
          </div>
          <button className="btn btn-primary">Apply to {selected.size} CPE(s)</button>
        </form>
      )}

      {cpesByNetwork.map(({ network, items }) => (
        <div key={network.id} className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-border bg-panel2/40 flex items-center justify-between">
            <div className="text-sm font-medium text-slate-200">{network.name}</div>
            <div className="text-xs text-muted">{items.length} CPEs {network.cidr ? `· ${network.cidr}` : ""}</div>
          </div>
          <div className="divide-y divide-border">
            {items.length === 0 && <div className="p-4 text-sm text-muted">No CPEs in this network yet.</div>}
            {items.map((c) => (
              <div key={c.id} className="px-4 py-2.5 flex items-center justify-between hover:bg-panel2/30">
                <div className="flex items-center gap-3 min-w-0">
                  <button onClick={() => toggleSelect(c.id)} className="text-muted shrink-0">
                    {selected.has(c.id) ? <CheckSquare size={16} className="text-accent" /> : <Square size={16} />}
                  </button>
                  <Link to={`/cpes/${c.id}`} className="min-w-0">
                    <div className="text-sm text-slate-200 truncate">{c.name}</div>
                    <div className="text-xs text-muted truncate">
                      {c.host || c.mac_address || "no address"} · {c.connection_mode}
                      {c.bridge_mode ? " · bridge" : ""}{c.pppoe_enabled ? " · pppoe" : ""}
                    </div>
                  </Link>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted shrink-0">
                  {c.last_signal_dbm != null && <span>{c.last_signal_dbm} dBm</span>}
                  {c.last_cpu_percent != null && <span>{c.last_cpu_percent}% CPU</span>}
                  <StatusBadge status={c.status} />
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
