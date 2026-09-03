import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Router, Trash2, Zap, X } from "lucide-react";
import api from "../api/client.js";
import { StatusBadge } from "../components/Badges.jsx";

const emptyForm = {
  name: "", host: "", port: 443, api_type: "rest", username: "admin", password: "",
  discovery_cidr: "", use_socks_relay: true, socks_port: 1080, verify_tls: false,
};

export default function RoutersPage() {
  const [routers, setRouters] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState({});
  const [error, setError] = useState("");

  async function load() {
    const res = await api.get("/management-routers");
    setRouters(res.data);
  }

  useEffect(() => { load(); }, []);

  async function createRouter(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post("/management-routers", { ...form, port: Number(form.port), socks_port: Number(form.socks_port) });
      setForm(emptyForm);
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create router");
    } finally {
      setBusy(false);
    }
  }

  async function testConnection(id) {
    setTestResult((s) => ({ ...s, [id]: { loading: true } }));
    try {
      const res = await api.post(`/management-routers/${id}/test-connection`);
      setTestResult((s) => ({ ...s, [id]: { ok: true, ...res.data } }));
      await load();
    } catch (err) {
      setTestResult((s) => ({ ...s, [id]: { ok: false, error: err.response?.data?.detail || "Failed" } }));
    }
  }

  async function remove(id) {
    if (!confirm("Delete this management router and everything under it?")) return;
    await api.delete(`/management-routers/${id}`);
    await load();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Management Routers</h1>
          <p className="text-sm text-muted mt-0.5">
            Each one is a top-level RouterOS device you log into directly; its networks and CPEs live underneath it.
            Add as many sites/towers as you need.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm((s) => !s)}>
          {showForm ? <X size={15} /> : <Plus size={15} />}
          {showForm ? "Cancel" : "Add router"}
        </button>
      </div>

      {showForm && (
        <form onSubmit={createRouter} className="card p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="label">Name</label>
            <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Main Tower" />
          </div>
          <div>
            <label className="label">Host / IP</label>
            <input className="input" required value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} placeholder="10.10.0.1" />
          </div>
          <div>
            <label className="label">Port</label>
            <input className="input" type="number" value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })} />
          </div>
          <div>
            <label className="label">API type</label>
            <select className="input" value={form.api_type} onChange={(e) => setForm({ ...form, api_type: e.target.value })}>
              <option value="rest">REST (RouterOS 7+, recommended)</option>
              <option value="api-ssl">Binary API over TLS (api-ssl)</option>
              <option value="api">Binary API, unencrypted (api)</option>
            </select>
          </div>
          <div>
            <label className="label">Username</label>
            <input className="input" required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          </div>
          <div>
            <label className="label">Password</label>
            <input className="input" type="password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </div>
          <div>
            <label className="label">Discovery CIDR (optional, enables periodic auto-discovery)</label>
            <input className="input" value={form.discovery_cidr} onChange={(e) => setForm({ ...form, discovery_cidr: e.target.value })} placeholder="10.10.0.0/24" />
          </div>
          <div className="flex items-end gap-4">
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input type="checkbox" checked={form.use_socks_relay} onChange={(e) => setForm({ ...form, use_socks_relay: e.target.checked })} />
              Use SOCKS relay for isolated CPEs
            </label>
            <div className="flex-1">
              <label className="label">SOCKS port</label>
              <input className="input" type="number" value={form.socks_port} onChange={(e) => setForm({ ...form, socks_port: e.target.value })} />
            </div>
          </div>
          {error && <div className="md:col-span-2 text-sm text-crit">{error}</div>}
          <div className="md:col-span-2 text-xs text-muted -mt-1">
            VPN (PPTP/L2TP/WireGuard) into this router's own LAN can be set up after creating it, from its detail page.
          </div>
          <div className="md:col-span-2">
            <button className="btn btn-primary" disabled={busy}>{busy ? "Creating..." : "Create management router"}</button>
          </div>
        </form>
      )}

      <div className="card divide-y divide-border">
        {routers.length === 0 && <div className="p-6 text-center text-muted text-sm">No management routers yet.</div>}
        {routers.map((r) => (
          <div key={r.id} className="p-4 flex items-center justify-between">
            <Link to={`/routers/${r.id}`} className="flex items-center gap-3 min-w-0">
              <div className="w-9 h-9 rounded-lg bg-panel2 flex items-center justify-center shrink-0">
                <Router size={16} className="text-muted" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-100">{r.name}</div>
                <div className="text-xs text-muted truncate">
                  {r.host}:{r.port} · {r.api_type} {r.identity ? `· ${r.identity}` : ""} {r.routeros_version ? `· RouterOS ${r.routeros_version}` : ""}
                </div>
              </div>
            </Link>
            <div className="flex items-center gap-3 shrink-0">
              {testResult[r.id]?.ok === true && <span className="text-xs text-accent2">Connected: {testResult[r.id].version}</span>}
              {testResult[r.id]?.ok === false && <span className="text-xs text-crit">{testResult[r.id].error}</span>}
              <StatusBadge status={r.status} />
              <button className="btn btn-secondary !px-2" title="Test connection" onClick={() => testConnection(r.id)}>
                <Zap size={14} />
              </button>
              <button className="btn btn-danger !px-2" title="Delete" onClick={() => remove(r.id)}>
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
