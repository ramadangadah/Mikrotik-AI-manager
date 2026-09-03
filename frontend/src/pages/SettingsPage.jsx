import React, { useEffect, useState } from "react";
import { Save } from "lucide-react";
import api from "../api/client.js";

export default function SettingsPage() {
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  async function load() {
    const res = await api.get("/settings");
    setForm({ ...res.data, llm_api_key: "", notify_telegram_bot_token: "" });
  }

  useEffect(() => { load(); }, []);

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setMsg("");
    try {
      const payload = { ...form };
      // Don't overwrite a stored secret with an empty string if the field was left blank.
      if (!payload.llm_api_key) delete payload.llm_api_key;
      if (!payload.notify_telegram_bot_token) delete payload.notify_telegram_bot_token;
      await api.put("/settings", payload);
      setMsg("Settings saved.");
      await load();
    } catch (err) {
      setMsg(err.response?.data?.detail || "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  if (!form) return <div className="text-muted">Loading...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Settings</h1>
        <p className="text-sm text-muted mt-0.5">
          LLM provider (used for both alert explanations and the AI Assistant chat), ML anomaly detection, and
          outbound notifications. Changes apply immediately - no restart needed.
        </p>
      </div>

      <form onSubmit={save} className="space-y-6">
        <div className="card p-5 space-y-4">
          <h2 className="font-medium text-slate-100">AI / LLM</h2>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={form.enable_llm_explanations} onChange={(e) => setForm({ ...form, enable_llm_explanations: e.target.checked })} />
            Add LLM-generated plain-language explanations to rule-based/ML alerts
          </label>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="label">Provider</label>
              <select className="input" value={form.llm_provider} onChange={(e) => setForm({ ...form, llm_provider: e.target.value })}>
                <option value="none">None (disabled)</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </div>
            <div>
              <label className="label">Model</label>
              <input className="input" value={form.llm_model} onChange={(e) => setForm({ ...form, llm_model: e.target.value })} placeholder="gpt-4o-mini / claude-3-5-sonnet-latest" />
            </div>
            <div>
              <label className="label">API key {form.llm_api_key === "" && <span className="text-muted">(leave blank to keep current)</span>}</label>
              <input className="input" type="password" value={form.llm_api_key} onChange={(e) => setForm({ ...form, llm_api_key: e.target.value })} placeholder="sk-..." />
            </div>
          </div>
          <p className="text-xs text-muted">
            This same key powers the AI Assistant page - ask it to look things up or propose a script to run on
            one or more CPEs. It never executes anything on its own; you always confirm first.
          </p>
        </div>

        <div className="card p-5 space-y-3">
          <h2 className="font-medium text-slate-100">Machine learning</h2>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={form.enable_ml_anomaly_detection} onChange={(e) => setForm({ ...form, enable_ml_anomaly_detection: e.target.checked })} />
            Enable historical anomaly detection (IsolationForest over metric history) alongside rule-based/trend alerts
          </label>
        </div>

        <div className="card p-5 space-y-4">
          <h2 className="font-medium text-slate-100">Notifications</h2>
          <div>
            <label className="label">Webhook URL (optional)</label>
            <input className="input" value={form.notify_webhook_url || ""} onChange={(e) => setForm({ ...form, notify_webhook_url: e.target.value })} placeholder="https://..." />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="label">Telegram bot token {form.notify_telegram_bot_token === "" && <span className="text-muted">(leave blank to keep current)</span>}</label>
              <input className="input" type="password" value={form.notify_telegram_bot_token} onChange={(e) => setForm({ ...form, notify_telegram_bot_token: e.target.value })} />
            </div>
            <div>
              <label className="label">Telegram chat id</label>
              <input className="input" value={form.notify_telegram_chat_id || ""} onChange={(e) => setForm({ ...form, notify_telegram_chat_id: e.target.value })} />
            </div>
          </div>
        </div>

        {msg && <div className="text-sm text-slate-300">{msg}</div>}
        <button className="btn btn-primary" disabled={saving}><Save size={15} /> {saving ? "Saving..." : "Save settings"}</button>
      </form>
    </div>
  );
}
