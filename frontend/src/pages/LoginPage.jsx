import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Wifi } from "lucide-react";
import { useAuth } from "../context/AuthContext.jsx";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await login(username, password);
      if (data.must_change_password) navigate("/change-password");
      else navigate("/");
    } catch (err) {
      setError(err.response?.data?.detail || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <div className="w-12 h-12 rounded-xl bg-accent/15 flex items-center justify-center mb-3">
            <Wifi size={24} className="text-accent" />
          </div>
          <h1 className="text-xl font-semibold text-slate-100">MikroTik AI Manager</h1>
          <p className="text-sm text-muted mt-1">Sign in to continue</p>
        </div>

        <form onSubmit={onSubmit} className="card p-6 space-y-4">
          <div>
            <label className="label">Username</label>
            <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          </div>
          <div>
            <label className="label">Password</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && <div className="text-sm text-crit">{error}</div>}
          <button className="btn btn-primary w-full justify-center" disabled={loading}>
            {loading ? "Signing in..." : "Sign in"}
          </button>
          <p className="text-xs text-muted text-center pt-2">
            First time here? Default login is <code className="text-slate-300">admin / admin</code> - you'll be
            asked to set a new password immediately.
          </p>
        </form>
      </div>
    </div>
  );
}
