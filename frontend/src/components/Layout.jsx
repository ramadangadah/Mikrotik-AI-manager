import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Router, Radio, Bell, UploadCloud, KeyRound,
  Archive, Users, Settings, LogOut, Wifi, Bot,
} from "lucide-react";
import { useAuth } from "../context/AuthContext.jsx";

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/routers", label: "Management Routers", icon: Router },
  { to: "/cpes", label: "All CPEs", icon: Radio },
  { to: "/alerts", label: "Alerts", icon: Bell },
  { to: "/assistant", label: "AI Assistant", icon: Bot },
  { to: "/firmware", label: "Firmware", icon: UploadCloud },
  { to: "/pppoe", label: "PPPoE Backup", icon: KeyRound },
  { to: "/backups", label: "Config Backups", icon: Archive },
];

const adminItems = [
  { to: "/users", label: "Users", icon: Users },
  { to: "/settings", label: "Settings", icon: Settings },
];

export default function Layout() {
  const { username, role, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex bg-bg">
      <aside className="w-64 shrink-0 border-r border-border bg-panel flex flex-col">
        <div className="px-5 py-5 flex items-center gap-2 border-b border-border">
          <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center">
            <Wifi size={18} className="text-accent" />
          </div>
          <div>
            <div className="font-semibold text-slate-100 leading-tight">MikroTik AI</div>
            <div className="text-xs text-muted leading-tight">Manager</div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive ? "bg-accent/15 text-accent" : "text-slate-300 hover:bg-panel2"
                }`
              }
            >
              <item.icon size={17} />
              {item.label}
            </NavLink>
          ))}

          {role === "admin" && (
            <>
              <div className="pt-4 pb-1 px-3 text-xs uppercase tracking-wide text-muted">Admin</div>
              {adminItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                      isActive ? "bg-accent/15 text-accent" : "text-slate-300 hover:bg-panel2"
                    }`
                  }
                >
                  <item.icon size={17} />
                  {item.label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        <div className="p-3 border-t border-border">
          <div className="flex items-center justify-between px-2 py-2">
            <div>
              <div className="text-sm font-medium text-slate-200">{username}</div>
              <div className="text-xs text-muted capitalize">{role}</div>
            </div>
            <button
              className="btn btn-ghost !px-2"
              title="Log out"
              onClick={() => {
                logout();
                navigate("/login");
              }}
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <main className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-7xl mx-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
