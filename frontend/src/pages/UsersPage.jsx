import React, { useEffect, useState } from "react";
import { Plus, Trash2, X, KeyRound } from "lucide-react";
import api from "../api/client.js";
import { useAuth } from "../context/AuthContext.jsx";

const emptyForm = { username: "", password: "", role: "technician", force_password_change: true };

export default function UsersPage() {
  const { username: me } = useAuth();
  const [users, setUsers] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [resetTarget, setResetTarget] = useState(null);
  const [resetPassword, setResetPassword] = useState("");

  async function load() {
    const res = await api.get("/users");
    setUsers(res.data);
  }

  useEffect(() => { load(); }, []);

  async function createUser(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post("/users", form);
      setForm(emptyForm);
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create user");
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(u) {
    await api.patch(`/users/${u.id}`, { is_active: !u.is_active });
    await load();
  }

  async function changeRole(u, role) {
    await api.patch(`/users/${u.id}`, { role });
    await load();
  }

  async function resetPasswordFor(u) {
    if (!resetPassword || resetPassword.length < 8) return;
    await api.patch(`/users/${u.id}`, { new_password: resetPassword });
    setResetTarget(null);
    setResetPassword("");
    await load();
  }

  async function remove(u) {
    if (!confirm(`Delete user "${u.username}"?`)) return;
    await api.delete(`/users/${u.id}`);
    await load();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Users</h1>
          <p className="text-sm text-muted mt-0.5">Admin, operator, and technician accounts. Admin-only page.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm((s) => !s)}>
          {showForm ? <X size={15} /> : <Plus size={15} />} {showForm ? "Cancel" : "Add user"}
        </button>
      </div>

      {showForm && (
        <form onSubmit={createUser} className="card p-5 grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
          <div>
            <label className="label">Username</label>
            <input className="input" required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          </div>
          <div>
            <label className="label">Temporary password</label>
            <input className="input" type="password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </div>
          <div>
            <label className="label">Role</label>
            <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="admin">Admin</option>
              <option value="operator">Operator</option>
              <option value="technician">Technician</option>
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={form.force_password_change} onChange={(e) => setForm({ ...form, force_password_change: e.target.checked })} />
            Force password change on first login
          </label>
          {error && <div className="md:col-span-4 text-sm text-crit">{error}</div>}
          <div className="md:col-span-4">
            <button className="btn btn-primary" disabled={busy}>{busy ? "Creating..." : "Create user"}</button>
          </div>
        </form>
      )}

      <div className="card divide-y divide-border">
        {users.map((u) => (
          <div key={u.id} className="p-4 flex items-center justify-between flex-wrap gap-3">
            <div className="min-w-0">
              <div className="text-sm font-medium text-slate-100 flex items-center gap-2">
                {u.username}
                {u.username === me && <span className="text-xs text-muted">(you)</span>}
                {!u.is_active && <span className="badge badge-offline">disabled</span>}
                {u.must_change_password && <span className="badge badge-degraded">must change password</span>}
              </div>
              <div className="text-xs text-muted">created by {u.created_by || "system"}</div>
            </div>
            <div className="flex items-center gap-2">
              <select className="input w-36 !py-1" value={u.role} onChange={(e) => changeRole(u, e.target.value)}>
                <option value="admin">Admin</option>
                <option value="operator">Operator</option>
                <option value="technician">Technician</option>
              </select>
              <button className="btn btn-secondary" onClick={() => toggleActive(u)}>{u.is_active ? "Disable" : "Enable"}</button>
              <button className="btn btn-secondary !px-2" title="Reset password" onClick={() => { setResetTarget(u.id); setResetPassword(""); }}>
                <KeyRound size={14} />
              </button>
              {u.username !== me && (
                <button className="btn btn-danger !px-2" title="Delete" onClick={() => remove(u)}>
                  <Trash2 size={14} />
                </button>
              )}
            </div>
            {resetTarget === u.id && (
              <div className="w-full flex items-center gap-2 pt-2">
                <input className="input flex-1" type="password" placeholder="New temporary password (min 8 chars)"
                  value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} />
                <button className="btn btn-primary" onClick={() => resetPasswordFor(u)}>Set password</button>
                <button className="btn btn-ghost" onClick={() => setResetTarget(null)}>Cancel</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
