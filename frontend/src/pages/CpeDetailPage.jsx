import React, { useEffect, useState, useCallback } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import {
  ArrowLeft, Zap, Trash2, Save, Terminal, History, RotateCcw, Play,
} from "lucide-react";
import api from "../api/client.js";
import { StatusBadge, SeverityBadge } from "../components/Badges.jsx";

const CHARTS = [
  { key: "cpu_percent", label: "CPU %", color: "#3ba7ff" },
  { key: "memory_percent", label: "Memory %", color: "#22c55e" },
  { key: "signal_dbm", label: "Signal (dBm)", color: "#f5a524" },
  { key: "ping_latency_ms", label: "Ping (ms)", color: "#f5424a" },
];

function MetricChart({ cpeId, metricType, label, color }) {
  const [data, setData] = useState([]);

  useEffect(() => {
    api.get(`/cpes/${cpeId}/metrics`, { params: { metric_type: metricType, hours: 24 } }).then((res) => {
      setData(res.data.map((d) => ({ t: new Date(d.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), v: d.value })));
    });
  }, [cpeId, metricType]);

  return (
    <div className="card p-4">
      <div className="text-sm font-medium text-slate-200 mb-2">{label}</div>
      {data.length === 0 ? (
        <div className="text-xs text-muted h-40 flex items-center justify-center">No data yet (last 24h)</div>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#232c3a" />
            <XAxis dataKey="t" stroke="#7c8aa0" fontSize={10} tickLine={false} />
            <YAxis stroke="#7c8aa0" fontSize={10} tickLine={false} width={36} />
            <Tooltip contentStyle={{ background: "#121821", border: "1px solid #232c3a", borderRadius: 8, fontSize: 12 }} />
            <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.75} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

export default function CpeDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [cpe, setCpe] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [backups, setBackups] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState("");
  const [testResult, setTestResult] = useState(null);
  const [scriptSource, setScriptSource] = useState(':log info "hello from app"');
  const [scriptBusy, setScriptBusy] = useState(false);

  const load = useCallback(async () => {
    const [c, a, b, j] = await Promise.all([
      api.get(`/cpes/${id}`),
      api.get("/alerts", { params: { cpe_id: id, limit: 20 } }),
      api.get("/config-backups"),
      api.get("/jobs", { params: { limit: 100 } }),
    ]);
    setCpe(c.data);
    setForm({
      name: c.data.name, host: c.data.host || "", port: c.data.port, username: c.data.username || "",
      password: "", connection_mode: c.data.connection_mode, role: c.data.role || "", monitored: c.data.monitored,
      auto_restore_on_reconnect: c.data.auto_restore_on_reconnect,
    });
    setAlerts(a.data);
    setBackups(b.data.filter((bk) => bk.target_type === "cpe" && bk.target_id === Number(id)));
    setJobs(j.data.filter((jb) => jb.target_type === "cpe" && jb.target_id === Number(id)));
  }, [id]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  async function save(e) {
    e.preventDefault();
    const payload = { ...form, port: Number(form.port) };
    if (!payload.password) delete payload.password;
    await api.patch(`/cpes/${id}`, payload);
    setEditing(false);
    await load();
  }

  async function testConnection() {
    setTestResult({ loading: true });
    try {
      const res = await api.post(`/cpes/${id}/test-connection`);
      setTestResult(res.data);
    } catch (err) {
      setTestResult({ ok: false, error: err.response?.data?.detail });
    }
  }

  async function remove() {
    if (!confirm(`Delete CPE "${cpe.name}"?`)) return;
    await api.delete(`/cpes/${id}`);
    navigate(`/cpes`);
  }

  async function backupNow() {
    setMsg("Pulling backup...");
    try {
      await api.post(`/config-backups/cpe/${id}`);
      setMsg("Backup saved.");
      await load();
    } catch (err) {
      setMsg(err.response?.data?.detail || "Backup failed");
    }
  }

  async function restoreLatest() {
    if (backups.length === 0) return;
    const latest = backups[0];
    if (!confirm(`Restore the backup from ${new Date(latest.created_at).toLocaleString()}? The device will reboot to apply it.`)) return;
    setMsg("Starting restore...");
    try {
      const res = await api.post(`/config-backups/${latest.id}/restore`);
      setMsg(`Restore job #${res.data.id} started.`);
      await load();
    } catch (err) {
      setMsg(err.response?.data?.detail || "Restore failed to start");
    }
  }

  async function runScript(e) {
    e.preventDefault();
    setScriptBusy(true);
    try {
      const res = await api.post("/scripts/run", { source: scriptSource, cpe_id: Number(id) });
      setMsg(`Script job #${res.data[0].id} started.`);
      await load();
    } catch (err) {
      setMsg(err.response?.data?.detail || "Script failed to start");
    } finally {
      setScriptBusy(false);
    }
  }

  if (!cpe || !form) return <div className="text-muted">Loading...</div>;

  return (
    <div className="space-y-6">
      <Link to="/cpes" className="inline-flex items-center gap-1 text-sm text-muted hover:text-slate-200">
        <ArrowLeft size={14} /> All CPEs
      </Link>

      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-slate-100">{cpe.name}</h1>
            <StatusBadge status={cpe.status} />
          </div>
          <p className="text-sm text-muted mt-0.5">
            {cpe.host || cpe.mac_address || "no address"}:{cpe.port} · {cpe.connection_mode}
            {cpe.bridge_mode ? " · bridge mode" : ""}{cpe.pppoe_enabled ? " · pppoe" : ""}
            {cpe.routeros_version ? ` · RouterOS ${cpe.routeros_version}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn btn-secondary" onClick={testConnection}><Zap size={14} /> Test</button>
          <button className="btn btn-secondary" onClick={() => setEditing((s) => !s)}>Edit</button>
          <button className="btn btn-danger !px-2" onClick={remove}><Trash2 size={14} /></button>
        </div>
      </div>

      {testResult && !testResult.loading && (
        <div className={`card p-3 text-sm ${testResult.ok ? "text-accent2" : "text-crit"}`}>
          {testResult.ok ? `Connected: RouterOS ${testResult.version} (${testResult.board})` : testResult.error}
        </div>
      )}
      {msg && <div className="card p-3 text-sm text-slate-300">{msg}</div>}

      {editing && (
        <form onSubmit={save} className="card p-5 grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="label">Name</label>
            <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div>
            <label className="label">Host / IP</label>
            <input className="input" value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} />
          </div>
          <div>
            <label className="label">Port</label>
            <input className="input" type="number" value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })} />
          </div>
          <div>
            <label className="label">Connection mode</label>
            <select className="input" value={form.connection_mode} onChange={(e) => setForm({ ...form, connection_mode: e.target.value })}>
              <option value="direct">Direct</option>
              <option value="socks_relay">Via SOCKS relay</option>
              <option value="vpn_tunnel">Via VPN tunnel (router's LAN)</option>
              <option value="unmanaged">Unmanaged (discovered only)</option>
            </select>
          </div>
          <div>
            <label className="label">Username</label>
            <input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          </div>
          <div>
            <label className="label">Password (leave blank to keep current)</label>
            <input className="input" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </div>
          <div>
            <label className="label">Role</label>
            <input className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} placeholder="antenna, router, ap..." />
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300 self-end">
            <input type="checkbox" checked={form.monitored} onChange={(e) => setForm({ ...form, monitored: e.target.checked })} />
            Monitored (polled on schedule)
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300 self-end">
            <input type="checkbox" checked={form.auto_restore_on_reconnect} onChange={(e) => setForm({ ...form, auto_restore_on_reconnect: e.target.checked })} />
            Auto-restore last config when this CPE reconnects after being offline
          </label>
          <div className="md:col-span-3">
            <button className="btn btn-primary"><Save size={14} /> Save changes</button>
          </div>
        </form>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {CHARTS.map((c) => <MetricChart key={c.key} cpeId={id} metricType={c.key} label={c.label} color={c.color} />)}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card p-5">
          <h2 className="font-medium text-slate-100 mb-3 flex items-center gap-2"><Terminal size={15} /> Run a script</h2>
          <p className="text-xs text-muted mb-3">
            Runs on this CPE as a throwaway RouterOS script, then reports back any log output. The AI Assistant
            uses this same endpoint for anything it proposes.
          </p>
          <form onSubmit={runScript} className="space-y-3">
            <textarea className="input font-mono text-xs" rows={4} value={scriptSource} onChange={(e) => setScriptSource(e.target.value)} />
            <button className="btn btn-primary" disabled={scriptBusy}><Play size={14} /> {scriptBusy ? "Running..." : "Run on this CPE"}</button>
          </form>
        </div>

        <div className="card p-5">
          <h2 className="font-medium text-slate-100 mb-3 flex items-center gap-2"><History size={15} /> Config backup</h2>
          <div className="flex items-center gap-2 mb-3">
            <button className="btn btn-secondary" onClick={backupNow}>Backup now</button>
            <button className="btn btn-secondary" onClick={restoreLatest} disabled={backups.length === 0}>
              <RotateCcw size={14} /> Restore latest
            </button>
          </div>
          <div className="space-y-1.5 max-h-40 overflow-y-auto">
            {backups.length === 0 && <div className="text-xs text-muted">No backups yet.</div>}
            {backups.map((b) => (
              <div key={b.id} className="text-xs text-muted flex items-center justify-between">
                <span>{new Date(b.created_at).toLocaleString()}</span>
                <a className="text-accent" href={`/api/config-backups/${b.id}/download`} target="_blank" rel="noreferrer">download</a>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card p-5">
          <h2 className="font-medium text-slate-100 mb-3">Recent alerts</h2>
          <div className="space-y-2">
            {alerts.length === 0 && <div className="text-sm text-muted">No alerts for this device.</div>}
            {alerts.map((a) => (
              <div key={a.id} className="px-3 py-2 rounded-lg bg-panel2/50">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-200">{a.title}</span>
                  <SeverityBadge severity={a.severity} />
                </div>
                <p className="text-xs text-muted mt-0.5">{a.description}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="card p-5">
          <h2 className="font-medium text-slate-100 mb-3">Recent jobs</h2>
          <div className="space-y-2">
            {jobs.length === 0 && <div className="text-sm text-muted">No jobs for this device yet.</div>}
            {jobs.map((j) => (
              <div key={j.id} className="px-3 py-2 rounded-lg bg-panel2/50">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-200">{j.job_type} · #{j.id}</span>
                  <span className={`badge ${j.status === "success" ? "badge-online" : j.status === "failed" ? "badge-offline" : "badge-unknown"}`}>{j.status}</span>
                </div>
                {j.log && <p className="text-xs text-muted mt-1 whitespace-pre-wrap line-clamp-3">{j.log}</p>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
