import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import api from "../api/client.js";
import { StatusBadge } from "../components/Badges.jsx";

export default function CpesPage() {
  const [cpes, setCpes] = useState([]);
  const [routers, setRouters] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [routerFilter, setRouterFilter] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.get("/management-routers").then((r) => setRouters(r.data));
  }, []);

  useEffect(() => {
    const params = {};
    if (statusFilter) params.status_filter = statusFilter;
    if (routerFilter) params.management_router_id = routerFilter;
    api.get("/cpes", { params }).then((r) => setCpes(r.data));
  }, [statusFilter, routerFilter]);

  const filtered = cpes.filter((c) =>
    !query || c.name.toLowerCase().includes(query.toLowerCase()) || (c.host || "").includes(query)
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">All CPEs</h1>
        <p className="text-sm text-muted mt-0.5">Every antenna / client router across all management routers.</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className="input !pl-8 w-64" placeholder="Search name or IP..." value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <select className="input w-48" value={routerFilter} onChange={(e) => setRouterFilter(e.target.value)}>
          <option value="">All management routers</option>
          {routers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <select className="input w-40" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">Any status</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="unknown">Unknown</option>
          <option value="degraded">Degraded</option>
        </select>
        <div className="text-sm text-muted ml-auto">{filtered.length} CPEs</div>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted border-b border-border">
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Address</th>
              <th className="px-4 py-2 font-medium">Mode</th>
              <th className="px-4 py-2 font-medium">CPU</th>
              <th className="px-4 py-2 font-medium">Mem</th>
              <th className="px-4 py-2 font-medium">Signal</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr key={c.id} className="border-b border-border last:border-0 hover:bg-panel2/40">
                <td className="px-4 py-2.5">
                  <Link to={`/cpes/${c.id}`} className="text-slate-200 hover:text-accent">{c.name}</Link>
                </td>
                <td className="px-4 py-2.5 text-muted">{c.host || c.mac_address || "-"}</td>
                <td className="px-4 py-2.5 text-muted">{c.connection_mode}</td>
                <td className="px-4 py-2.5 text-muted">{c.last_cpu_percent != null ? `${c.last_cpu_percent}%` : "-"}</td>
                <td className="px-4 py-2.5 text-muted">{c.last_memory_percent != null ? `${c.last_memory_percent}%` : "-"}</td>
                <td className="px-4 py-2.5 text-muted">{c.last_signal_dbm != null ? `${c.last_signal_dbm} dBm` : "-"}</td>
                <td className="px-4 py-2.5"><StatusBadge status={c.status} /></td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-muted">No CPEs match.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
