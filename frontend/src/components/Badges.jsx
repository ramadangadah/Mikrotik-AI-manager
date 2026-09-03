import React from "react";

export function StatusBadge({ status }) {
  const cls = { online: "badge-online", offline: "badge-offline", degraded: "badge-degraded", unknown: "badge-unknown" }[status] || "badge-unknown";
  return <span className={`badge ${cls}`}>{status}</span>;
}

export function SeverityBadge({ severity }) {
  const cls = { info: "badge-info", warning: "badge-warning", critical: "badge-critical" }[severity] || "badge-info";
  return <span className={`badge ${cls}`}>{severity}</span>;
}
