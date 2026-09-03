import React, { useEffect, useState } from "react";
import { Download, KeyRound, RefreshCw } from "lucide-react";
import api from "../api/client.js";

export default function PppoePage() {
  const [secrets, setSecrets] = useState([]);
  const [routers, setRouters] = useState([]);
  const [routerFilter, setRouterFilter] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState("");

  async function load() {
    const [s, r] = await Promise.all([
      api.get("/pppoe/secrets", { params: routerFilter ? { source_router_id: routerFilter } : {} }),
      api.get("/management-routers"),
    ]);
    setSecrets(s.data);
    setRouters(r.data);
  }

  useEffect(() => { load(); }, [routerFilter]);

  async function syncNow() {
    if (!routerFilter) { setMsg("Pick a management router to sync from first."); return; }
    setSyncing(true);
    setMsg("Syncing secrets from router...");
    try {
      const res = await api.post(`/pppoe/sync/${routerFilter}`);
      setMsg(`Synced ${res.data.total_on_router} secrets on the router (${res.data.created} new, ${res.data.updated} updated, ${res.data.skipped_masked} skipped - masked by RouterOS, needs a full/admin API user to read).`);
      await load();
    } catch (err) {
      setMsg(err.response?.data?.detail || "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  async function exportCsv() {
    const params = routerFilter ? { source_router_id: routerFilter } : {};
    const res = await api.get("/pppoe/export", { params, responseType: "blob" });
    const url = URL.createObjectURL(new Blob([res.data], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "pppoe_secrets_backup.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">PPPoE Credential Backup</h1>
        <p className="text-sm text-muted mt-0.5">
          A read-only, encrypted-at-rest mirror of every PPPoE username/password on a management router's PPP
          secrets table - so you're never locked out of your customer credential list if that router's config is
          ever lost. The router itself always stays the source of truth; sync pulls the latest.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <select className="input w-64" value={routerFilter} onChange={(e) => setRouterFilter(e.target.value)}>
          <option value="">All management routers</option>
          {routers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <button className="btn btn-secondary" onClick={syncNow} disabled={syncing}>
          <RefreshCw size={14} className={syncing ? "animate-spin" : ""} /> {syncing ? "Syncing..." : "Sync from router"}
        </button>
        <button className="btn btn-secondary" onClick={exportCsv}>
          <Download size={14} /> Export CSV (plaintext passwords)
        </button>
        <div className="text-sm text-muted ml-auto">{secrets.length} secrets</div>
      </div>

      {msg && <div className="card p-3 text-sm text-slate-300">{msg}</div>}

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted border-b border-border">
              <th className="px-4 py-2 font-medium">Username</th>
              <th className="px-4 py-2 font-medium">Profile</th>
              <th className="px-4 py-2 font-medium">Service</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Comment</th>
            </tr>
          </thead>
          <tbody>
            {secrets.map((s) => (
              <tr key={s.id} className="border-b border-border last:border-0 hover:bg-panel2/40">
                <td className="px-4 py-2.5 text-slate-200 flex items-center gap-2">
                  <KeyRound size={13} className="text-muted" /> {s.username}
                </td>
                <td className="px-4 py-2.5 text-muted">{s.profile || "-"}</td>
                <td className="px-4 py-2.5 text-muted">{s.service || "-"}</td>
                <td className="px-4 py-2.5">
                  <span className={`badge ${s.disabled ? "badge-offline" : "badge-online"}`}>{s.disabled ? "disabled" : "enabled"}</span>
                </td>
                <td className="px-4 py-2.5 text-muted">{s.comment || "-"}</td>
              </tr>
            ))}
            {secrets.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-muted">No secrets synced yet. Pick a router and click "Sync from router".</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
