import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import api from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";

export default function ChangePasswordPage() {
  const { token, completePasswordChange, logout } = useAuth();
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (!token) {
    navigate("/login");
    return null;
  }

  async function onSubmit(e) {
    e.preventDefault();
    setError("");
    if (newPassword.length < 8) return setError("New password must be at least 8 characters.");
    if (newPassword !== confirm) return setError("Passwords do not match.");

    setLoading(true);
    try {
      await api.post("/auth/change-password", { current_password: currentPassword, new_password: newPassword });
      completePasswordChange();
      navigate("/");
    } catch (err) {
      setError(err.response?.data?.detail || "Could not change password");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <div className="w-12 h-12 rounded-xl bg-warn/15 flex items-center justify-center mb-3">
            <ShieldAlert size={24} className="text-warn" />
          </div>
          <h1 className="text-xl font-semibold text-slate-100">Set a new password</h1>
          <p className="text-sm text-muted mt-1 text-center">
            You're using a default or reset password. Choose a new one before continuing.
          </p>
        </div>

        <form onSubmit={onSubmit} className="card p-6 space-y-4">
          <div>
            <label className="label">Current password</label>
            <input className="input" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} autoFocus />
          </div>
          <div>
            <label className="label">New password</label>
            <input className="input" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
          </div>
          <div>
            <label className="label">Confirm new password</label>
            <input className="input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </div>
          {error && <div className="text-sm text-crit">{error}</div>}
          <button className="btn btn-primary w-full justify-center" disabled={loading}>
            {loading ? "Updating..." : "Update password"}
          </button>
          <button type="button" className="btn btn-ghost w-full justify-center" onClick={() => { logout(); navigate("/login"); }}>
            Cancel and log out
          </button>
        </form>
      </div>
    </div>
  );
}
