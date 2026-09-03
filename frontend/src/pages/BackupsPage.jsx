import React, { useEffect, useState } from "react";
import { Download, History, RotateCcw } from "lucide-react";
import api from "../api/client.js";

export default function BackupsPage() {
  const [backups, setBackups] = useState([]);
  const [routers, setRouters] = useState([]);
  const [cpes, setCpes] = useState([]);
  const [routerFilter, setRouterFilter] = useState("");
  const [cpeFilter, setCpeFilter] = useState("");
  const [msg, setMsg] = useState("");
  const [restoring, setRestoring] = useState(null);

  async function load() {
    const [b, r, c] = await Promise.all([
      api.get("/config-backups"),
      api.get("/management-routers"),
      api.get("/cpes"),
    ]);
    setBackups(b.data);
    setRouters(r.data);
    setCpes(c.data);
  }

  useEffect(() => { load(); }, []);

  const routerName = (id) => routers.find((r) => r.id === id)?.name || `#${id}`;
  const cpeName = (id) => cpes.find((c) => c.id === id)?.name || `#${id}`;

  async function backupRouter() {
    if (!routerFilter) return;
    setMsg("Pulling backup...");
    try {
      await api.post(`/config-backups/management-router/${routerFilter}`);
      setMsg("Backup saved.");
      await load();
    } catch (err) {
      setMsg(err.response?.data?.detail || "Backup failed");
    }
  }

  async function backupCpe() {
    if (!cpeFilter) return;
    setMsg("Pulling backup...");
    try {
      await api.post(`/config-backups/cpe/${cpeFilter}`);
      setMsg("Backup saved.");
      await load();
    } catch (err) {
      setMsg(err.response?.data?.detail || "Backup failed");
    }
  }

  function download(id, name) {
    window.open(`/api/config-backups/${id}/download`, "_blank");
  }

  async function restore(b) {
    if (!confirm(`Push this backup (from ${new Date(b.created_at).toLocaleString()}) back onto ${b.target_name} and load it? The device will reboot automatically to apply it.`)) return;
    setRestoring(b.id);
    setMsg(`Restoring ${b.target_name}...`);
    try {
      const res = await api.post(`/config-backups/${b.id}/restore`);
      setMsg(`Restore job #${res.data.id} started for ${b.target_name} - it uploads the backup via SFTP, tells RouterOS to load it, then waits for the device to reboot and come back online. Check Jobs for progress.`);
    } catch (err) {
      setMsg(err.response?.data?.detail || "Restore failed to start");
    } finally {
      setRestoring(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Config Backups</h1>
        <p className="text-sm text-muted mt-0.5">
          Timestamped copies of each device's full configuration, pulled via SFTP - works for bridge-mode CPEs
          through the same SOCKS relay/VPN path as everything else. Restore pushes one back onto its device and
          tells RouterOS to load it (the device reboots on its own to apply it). To have this happen
          automatically the moment a factory-reset or swapped-out CPE comes back online, turn on
          "auto restore on reconnect" on that CPE's detail page.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card p-4 flex items-end gap-3">
          <div className="flex-1">
            <label className="label">Back up a management router now</label>
            <select className="input" value={routerFilter} onChange={(e) => setRouterFilter(e.target.value)}>
              <option value="">Select router...</option>
              {routers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </div>
          <button className="btn btn-secondary" onClick={backupRouter} disabled={!routerFilter}><History size={14} /> Backup</button>
        </div>
        <div className="card p-4 flex items-end gap-3">
          <div className="flex-1">
            <label className="label">Back up a CPE now</label>
            <select className="input" value={cpeFilter} onChange={(e) => setCpeFilter(e.target.value)}>
              <option value="">Select CPE...</option>
              {cpes.filter((c) => c.connection_mode !== "unmanaged").map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <button className="btn btn-secondary" onClick={backupCpe} disabled={!cpeFilter}><History size={14} /> Backup</button>
        </div>
      </div>

      {msg && <div className="card p-3 text-sm text-slate-300">{msg}</div>}

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted border-b border-border">
              <th className="px-4 py-2 font-medium">Target</th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 font-medium">RouterOS</th>
              <th className="px-4 py-2 font-medium">Size</th>
              <th className="px-4 py-2 font-medium">Created</th>
              <th className="px-4 py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {backups.map((b) => (
              <tr key={b.id} className="border-b border-border last:border-0 hover:bg-panel2/40">
                <td className="px-4 py-2.5 text-slate-200">{b.target_name}</td>
                <td className="px-4 py-2.5 text-muted">{b.target_type === "cpe" ? "CPE" : "Management router"}</td>
                <td className="px-4 py-2.5 text-muted">{b.routeros_version || "-"}</td>
                <td className="px-4 py-2.5 text-muted">{b.size_bytes != null ? `${(b.size_bytes / 1024).toFixed(1)} KB` : "-"}</td>
                <td className="px-4 py-2.5 text-muted">{new Date(b.created_at).toLocaleString()}</td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2 justify-end">
                    <button className="btn btn-secondary !px-2" title="Download" onClick={() => download(b.id)}>
                      <Download size={13} />
                    </button>
                    <button className="btn btn-secondary !px-2" title="Restore to device" disabled={restoring === b.id} onClick={() => restore(b)}>
                      <RotateCcw size={13} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {backups.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-muted">No backups yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
