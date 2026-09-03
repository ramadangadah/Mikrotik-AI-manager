import React, { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Eye, RefreshCw, Sparkles } from "lucide-react";
import api from "../api/client.js";
import { SeverityBadge } from "../components/Badges.jsx";

export default function AlertsPage() {
  const [alerts, setAlerts] = useState([]);
  const [statusFilter, setStatusFilter] = useState("open");
  const [severityFilter, setSeverityFilter] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const params = {};
    if (statusFilter) params.status_filter = statusFilter;
    if (severityFilter) params.severity = severityFilter;
    const res = await api.get("/alerts", { params });
    setAlerts(res.data);
  }, [statusFilter, severityFilter]);

  useEffect(() => { load(); }, [load]);

  async function evaluateNow() {
    setBusy(true);
    try {
      await api.post("/alerts/evaluate-now", null, { params: { full: true } });
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function acknowledge(id) {
    await api.post(`/alerts/${id}/acknowledge`);
    await load();
  }

  async function resolve(id) {
    await api.post(`/alerts/${id}/resolve`);
    await load();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Alerts</h1>
          <p className="text-sm text-muted mt-0.5">
            Rule-based findings, ML anomaly detections, and trend predictions - "signal trending down, likely
            failure in ~N days" alerts are marked predictive.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={evaluateNow} disabled={busy}>
          <RefreshCw size={14} className={busy ? "animate-spin" : ""} />
          {busy ? "Evaluating..." : "Evaluate now"}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <select className="input w-44" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
          <option value="">Any status</option>
        </select>
        <select className="input w-40" value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
          <option value="">Any severity</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </select>
        <div className="text-sm text-muted ml-auto">{alerts.length} alerts</div>
      </div>

      <div className="space-y-2">
        {alerts.length === 0 && <div className="card p-8 text-center text-muted text-sm">No alerts match this filter.</div>}
        {alerts.map((a) => (
          <div key={a.id} className="card p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-slate-100">{a.title}</span>
                  <SeverityBadge severity={a.severity} />
                  <span className="text-xs text-muted px-2 py-0.5 rounded-full bg-panel2">{a.category}</span>
                  {a.is_prediction && (
                    <span className="inline-flex items-center gap-1 text-xs text-accent">
                      <Sparkles size={11} /> predictive{a.confidence != null ? ` · ${a.confidence}%` : ""}
                    </span>
                  )}
                </div>
                <p className="text-sm text-muted mt-1">{a.description}</p>
                {a.llm_explanation && (
                  <p className="text-sm text-slate-300 mt-2 pl-3 border-l-2 border-accent/40">{a.llm_explanation}</p>
                )}
                <div className="text-xs text-muted mt-2 flex items-center gap-3">
                  <span>{new Date(a.created_at).toLocaleString()}</span>
                  {a.cpe_id && <Link to={`/cpes/${a.cpe_id}`} className="text-accent">View device</Link>}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {a.status === "open" && (
                  <button className="btn btn-secondary !px-2" title="Acknowledge" onClick={() => acknowledge(a.id)}>
                    <Eye size={14} />
                  </button>
                )}
                {a.status !== "resolved" && (
                  <button className="btn btn-secondary !px-2" title="Resolve" onClick={() => resolve(a.id)}>
                    <CheckCircle2 size={14} />
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
