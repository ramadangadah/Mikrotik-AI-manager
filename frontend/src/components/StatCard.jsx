import React from "react";

export default function StatCard({ label, value, sub, icon: Icon, tone = "default" }) {
  const toneClass = {
    default: "text-slate-100",
    good: "text-accent2",
    warn: "text-warn",
    crit: "text-crit",
  }[tone];

  return (
    <div className="card p-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs text-muted font-medium">{label}</div>
          <div className={`text-2xl font-semibold mt-1 ${toneClass}`}>{value}</div>
          {sub && <div className="text-xs text-muted mt-1">{sub}</div>}
        </div>
        {Icon && (
          <div className="w-9 h-9 rounded-lg bg-panel2 flex items-center justify-center">
            <Icon size={18} className="text-muted" />
          </div>
        )}
      </div>
    </div>
  );
}
