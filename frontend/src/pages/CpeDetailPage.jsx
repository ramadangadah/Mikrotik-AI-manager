import React, { useEffect, useState, useCallback } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import {
  ArrowLeft, Zap, Trash2, Save, Terminal, History, RotateCcw, Play, Radio, CheckCircle2, XCircle, MinusCircle,
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

function Verdict({ pass }) {
  if (pass === null || pass === undefined) return <MinusCircle size={14} className="text-muted inline" />;
  return pass ? <CheckCircle2 size={14} className="text-accent2 inline" /> : <XCircle size={14} className="text-crit inline" />;
}

function fmt(v, suffix = "") {
  return v === null || v === undefined ? "—" : `${v}${suffix}`;
}

function fmtSeconds(s) {
  if (s === null || s === undefined) return "—";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}

// Checklist row helper - label/value/badge on one line, matching the
// original paper form's two-column layout ("check · recorded value").
function Row({ label, value, verdict }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-panel2/60 text-sm">
      <span className="text-muted">{label}</span>
      <span className="flex items-center gap-2 text-slate-200">
        {verdict !== undefined && <Verdict pass={verdict} />}
        {value}
      </span>
    </div>
  );
}

function ConnectivityTestSection({ cpeId, mac }) {
  const [tests, setTests] = useState([]);
  const [latest, setLatest] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [manual, setManual] = useState({ rebooted: false, tplink_speedtest_notes: "", client_pc_speedtest_notes: "", notes: "" });

  const load = useCallback(async () => {
    const res = await api.get(`/cpes/${cpeId}/connectivity-tests`);
    setTests(res.data);
    if (res.data.length > 0) {
      const t = res.data[0];
      setLatest(t);
      setManual({
        rebooted: t.rebooted, tplink_speedtest_notes: t.tplink_speedtest_notes || "",
        client_pc_speedtest_notes: t.client_pc_speedtest_notes || "", notes: t.notes || "",
      });
    }
  }, [cpeId]);

  useEffect(() => { load(); }, [load]);

  async function run(method) {
    setBusy(true);
    setMsg(`Running checks via ${method === "mac_telnet" ? "MAC-Telnet" : "IP"}...`);
    try {
      const res = await api.post(`/cpes/${cpeId}/connectivity-tests`, { method });
      setMsg(res.data.run_error ? `Completed with an error: ${res.data.run_error}` : "Automated checks complete - fill in the manual items below.");
      await load();
    } catch (err) {
      setMsg(err.response?.data?.detail || "Test failed to run");
    } finally {
      setBusy(false);
    }
  }

  async function saveManual(e) {
    e.preventDefault();
    if (!latest) return;
    setBusy(true);
    try {
      const res = await api.patch(`/connectivity-tests/${latest.id}`, manual);
      setLatest(res.data);
      setMsg("Saved.");
    } catch (err) {
      setMsg(err.response?.data?.detail || "Failed to save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="font-medium text-slate-100 flex items-center gap-2"><Radio size={15} /> Client connectivity test</h2>
        <div className="flex items-center gap-2">
          <button className="btn btn-secondary" onClick={() => run("ip")} disabled={busy}>Run via IP</button>
          <button className="btn btn-secondary" onClick={() => run("mac_telnet")} disabled={busy || !mac} title={!mac ? "No MAC address on file" : ""}>
            Run via MAC-Telnet
          </button>
        </div>
      </div>
      <p className="text-xs text-muted -mt-2">
        Pulls what RouterOS can report automatically (radio checks + ping/bandwidth-test); anything it can't see -
        power-cycling the PoE injector, a TP-Link router's own speed test, the client PC's fast.com result - is
        below for you to fill in by hand. A "—" means this device/driver just didn't report that field.
      </p>
      {msg && <div className="text-xs text-muted">{msg}</div>}

      {latest && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8">
            <div>
              <h3 className="text-xs uppercase tracking-wide text-muted mb-1">Controlli sulla radio del cliente</h3>
              <Row label="Registered to sector" value={fmt(latest.sector_name)} verdict={latest.registered === null ? undefined : latest.registered} />
              <Row label="SNR > 20 dB" value={fmt(latest.snr_db, " dB")} verdict={latest.snr_db == null ? null : latest.snr_db > 20} />
              <Row label="Signal ≥ -75 dBm" value={fmt(latest.signal_dbm, " dBm")} verdict={latest.signal_dbm == null ? null : latest.signal_dbm > -75} />
              <Row label="V/H ratio < 6 dB" value={fmt(latest.vh_ratio_db, " dB")} verdict={latest.vh_ratio_db == null ? null : latest.vh_ratio_db < 6} />
              <Row label="CPE uptime" value={fmtSeconds(latest.cpe_uptime_seconds)} />
              <Row label="BTS link time" value={fmtSeconds(latest.bts_connection_seconds)} />
              <Row label="Firmware aligned to BTS" value={`${fmt(latest.cpe_firmware)} / ${fmt(latest.bts_firmware)}`} verdict={latest.firmware_aligned} />
              <Row label={`Disconnects (${latest.disconnect_window_days}d)`} value={fmt(latest.disconnect_count)} verdict={latest.disconnect_count == null ? null : latest.disconnect_count === 0} />
              <Row label="Ethernet link speed" value={fmt(latest.ethernet_link_speed)} />
            </div>
            <div>
              <h3 className="text-xs uppercase tracking-wide text-muted mb-1">Test di rete</h3>
              <Row label={`Ping gateway (${fmt(latest.ping_gateway_target)})`} value={fmt(latest.ping_gateway_result)} />
              <Row label="Ping 8.8.8.8" value={fmt(latest.ping_public_ip_result)} />
              <Row label={`Ping ${fmt(latest.ping_domain_target)}`} value={fmt(latest.ping_domain_result)} />
              <Row label="Bandwidth-test (internal)" value={fmt(latest.bandwidth_test_result)} />
              <p className="text-xs text-muted mt-2 whitespace-pre-wrap">{latest.bandwidth_test_result}</p>
            </div>
          </div>

          <form onSubmit={saveManual} className="space-y-3 pt-2 border-t border-panel2">
            <h3 className="text-xs uppercase tracking-wide text-muted">Manual entries</h3>
            <label className="flex items-center gap-2 text-sm text-slate-200">
              <input type="checkbox" checked={manual.rebooted} onChange={(e) => setManual({ ...manual, rebooted: e.target.checked })} />
              Router + PoE power-cycled (30s off/on)
            </label>
            <div>
              <label className="label">TP-Link router speed test result</label>
              <input className="input" value={manual.tplink_speedtest_notes} onChange={(e) => setManual({ ...manual, tplink_speedtest_notes: e.target.value })} />
            </div>
            <div>
              <label className="label">Client PC speed test (fast.com, cable-connected)</label>
              <input className="input" value={manual.client_pc_speedtest_notes} onChange={(e) => setManual({ ...manual, client_pc_speedtest_notes: e.target.value })} />
            </div>
            <div>
              <label className="label">Notes</label>
              <textarea className="input" rows={2} value={manual.notes} onChange={(e) => setManual({ ...manual, notes: e.target.value })} />
            </div>
            <button className="btn btn-primary" disabled={busy}><Save size={14} /> Save</button>
          </form>
        </>
      )}

      {!latest && <div className="text-sm text-muted">No test run yet - click "Run via IP" or "Run via MAC-Telnet" above.</div>}

      {tests.length > 1 && (
        <div className="pt-2 border-t border-panel2">
          <h3 className="text-xs uppercase tracking-wide text-muted mb-1">History</h3>
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {tests.map((t) => (
              <div key={t.id} className="text-xs text-muted flex items-center justify-between">
                <span>{new Date(t.created_at).toLocaleString()} · via {t.method}</span>
                <span>{t.run_error ? "error" : "ok"}</span>
              </div>
            ))}
          </div>
        </div>
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
    setTestResult({ loading: true, via: "IP" });
    try {
      const res = await api.post(`/cpes/${id}/test-connection`);
      setTestResult({ ...res.data, via: "IP" });
    } catch (err) {
      setTestResult({ ok: false, via: "IP", error: err.response?.data?.detail });
    }
  }

  async function testMacTelnet() {
    setTestResult({ loading: true, via: "MAC-Telnet" });
    try {
      const res = await api.post(`/cpes/${id}/test-mactelnet`);
      setTestResult({ ...res.data, via: "MAC-Telnet" });
    } catch (err) {
      setTestResult({ ok: false, via: "MAC-Telnet", error: err.response?.data?.detail });
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
            {cpe.host || "no IP"}{cpe.mac_address ? ` · ${cpe.mac_address}` : ""}:{cpe.port} · {cpe.connection_mode}
            {cpe.bridge_mode ? " · bridge mode" : ""}{cpe.pppoe_enabled ? " · pppoe" : ""}
            {cpe.routeros_version ? ` · RouterOS ${cpe.routeros_version}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn btn-secondary" onClick={testConnection} disabled={!cpe.host}>
            <Zap size={14} /> Test via IP
          </button>
          <button className="btn btn-secondary" onClick={testMacTelnet} disabled={!cpe.mac_address} title={!cpe.mac_address ? "No MAC address on file for this CPE" : "Requires layer-2 reachability to this CPE's segment"}>
            <Zap size={14} /> Test via MAC-Telnet
          </button>
          <button className="btn btn-secondary" onClick={() => setEditing((s) => !s)}>Edit</button>
          <button className="btn btn-danger !px-2" onClick={remove}><Trash2 size={14} /></button>
        </div>
      </div>

      {testResult && !testResult.loading && (
        <div className={`card p-3 text-sm ${testResult.ok ? "text-accent2" : "text-crit"}`}>
          {testResult.ok
            ? `Connected via ${testResult.via}: RouterOS ${testResult.version} (${testResult.board}${testResult.identity ? `, ${testResult.identity}` : ""})`
            : `${testResult.via}: ${testResult.error}`}
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

      <ConnectivityTestSection cpeId={id} mac={cpe.mac_address} />

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
