import React, { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { Router, Radio, Bell, ShieldCheck, RefreshCw, Cable, Wifi as WifiIcon } from "lucide-react";
import api from "../api/client.js";
import StatCard from "../components/StatCard.jsx";
import { StatusBadge, SeverityBadge } from "../components/Badges.jsx";

export default function DashboardPage() {
  const [summary, setSummary] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [s, a] = await Promise.all([
      api.get("/dashboard/summary"),
      api.get("/alerts", { params: { limit: 6 } }),
    ]);
    setSummary(s.data);
    setAlerts(a.data);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  async function pollNow() {
    setPolling(true);
    setError("");
    try {
      await api.post("/dashboard/poll-now");
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Poll failed");
    } finally {
      setPolling(false);
    }
  }

  if (!summary) return <div className="text-muted">Loading...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Dashboard</h1>
          <p className="text-sm text-muted mt-0.5">Live overview across all management routers and CPEs.</p>
        </div>
        <button className="btn btn-secondary" onClick={pollNow} disabled={polling}>
          <RefreshCw size={15} className={polling ? "animate-spin" : ""} />
          {polling ? "Polling..." : "Poll now"}
        </button>
      </div>

      {error && <div className="card p-3 text-sm text-crit border-crit/30">{error}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Management Routers"
          value={`${summary.management_routers.online}/${summary.management_routers.total}`}
          sub="online / total"
          icon={Router}
        />
        <StatCard
          label="CPEs Online"
          value={`${summary.cpes.online}/${summary.cpes.total}`}
          sub={`${summary.cpes.offline} offline · ${summary.cpes.unmanaged} unmanaged`}
          icon={Radio}
          tone={summary.cpes.offline > 0 ? "warn" : "good"}
        />
        <StatCard
          label="Open Alerts"
          value={summary.alerts.open}
          sub={`${summary.alerts.critical} critical · ${summary.alerts.predictive} predictive`}
          icon={Bell}
          tone={summary.alerts.critical > 0 ? "crit" : summary.alerts.open > 0 ? "warn" : "good"}
        />
        <StatCard
          label="PPPoE / Bridge"
          value={`${summary.cpes.pppoe} / ${summary.cpes.bridge_mode}`}
          sub="PPPoE-connected / bridge-mode"
          icon={Cable}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card p-4">
          <h2 className="font-medium text-slate-100 mb-3">Management routers</h2>
          <div className="space-y-2">
            {summary.routers_overview.length === 0 && (
              <p className="text-sm text-muted">
                No management routers yet. <Link to="/routers" className="text-accent">Add one</Link> to get started.
              </p>
            )}
            {summary.routers_overview.map((r) => (
              <Link
                key={r.id}
                to={`/routers/${r.id}`}
                className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-panel2 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Router size={15} className="text-muted" />
                  <span className="text-sm text-slate-200">{r.name}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted">{r.cpe_count} CPEs</span>
                  <StatusBadge status={r.status} />
                </div>
              </Link>
            ))}
          </div>
        </div>

        <div className="card p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-medium text-slate-100">Recent alerts</h2>
            <Link to="/alerts" className="text-xs text-accent">View all</Link>
          </div>
          <div className="space-y-2">
            {alerts.length === 0 && (
              <p className="text-sm text-muted flex items-center gap-2">
                <ShieldCheck size={15} className="text-accent2" /> No alerts. Everything looks healthy.
              </p>
            )}
            {alerts.map((a) => (
              <div key={a.id} className="px-3 py-2 rounded-lg bg-panel2/50">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-200">{a.title}</span>
                  <SeverityBadge severity={a.severity} />
                </div>
                <p className="text-xs text-muted mt-0.5 line-clamp-2">{a.description}</p>
                {a.is_prediction && (
                  <span className="inline-flex items-center gap-1 text-xs text-accent mt-1">
                    <WifiIcon size={11} /> predicted{a.confidence ? ` · ${a.confidence}% confidence` : ""}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
