import React, { useEffect, useRef, useState } from "react";
import { Bot, Send, ShieldAlert, User, CheckCircle2, XCircle } from "lucide-react";
import api from "../api/client.js";

function describeTarget(action) {
  if (action.cpe_id != null) return `CPE #${action.cpe_id}`;
  if (action.cpe_ids?.length) return `${action.cpe_ids.length} CPEs (ids ${action.cpe_ids.join(", ")})`;
  if (action.management_router_id != null) return `management router #${action.management_router_id} (not its CPEs)`;
  if (action.network_id != null) return `every monitored CPE in network #${action.network_id}`;
  if (action.all_cpes_under_router_id != null) return `every monitored CPE under management router #${action.all_cpes_under_router_id}`;
  if (action.all_monitored_cpes) return "every monitored CPE in the system";
  return "an unspecified target";
}

function ProposedActionCard({ action, onDone }) {
  const [state, setState] = useState("pending"); // pending | running | done | error | dismissed
  const [result, setResult] = useState(null);

  async function confirm() {
    setState("running");
    try {
      // action carries `explanation` from the tool call - strip it, the
      // rest matches POST /api/scripts/run's body exactly.
      const { explanation, ...body } = action;
      const res = await api.post("/scripts/run", { ...body, confirm: true });
      setResult(res.data);
      setState("done");
      onDone?.();
    } catch (err) {
      setResult({ error: err.response?.data?.detail || "Failed to start" });
      setState("error");
    }
  }

  return (
    <div className="border border-warn/30 bg-warn/5 rounded-lg p-4 mt-2 space-y-3">
      <div className="flex items-center gap-2 text-warn text-sm font-medium">
        <ShieldAlert size={15} /> Proposed action - nothing has run yet
      </div>
      <div className="text-sm text-slate-200">
        Run on <span className="font-medium">{describeTarget(action)}</span>:
      </div>
      <pre className="bg-panel2 rounded-lg p-3 text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap">{action.source}</pre>

      {state === "pending" && (
        <div className="flex items-center gap-2">
          <button className="btn btn-primary" onClick={confirm}>Confirm and run</button>
          <button className="btn btn-ghost" onClick={() => setState("dismissed")}>Dismiss</button>
        </div>
      )}
      {state === "running" && <div className="text-sm text-muted">Starting job(s)...</div>}
      {state === "done" && (
        <div className="text-sm text-accent2 flex items-center gap-2">
          <CheckCircle2 size={14} /> Started {result.length} job(s) - check the Jobs list on each device for progress.
        </div>
      )}
      {state === "error" && (
        <div className="text-sm text-crit flex items-center gap-2">
          <XCircle size={14} /> {result.error}
        </div>
      )}
      {state === "dismissed" && <div className="text-sm text-muted">Dismissed - nothing ran.</div>}
    </div>
  );
}

export default function AssistantPage() {
  const [messages, setMessages] = useState([]); // {role, content, proposed_action?}
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setError("");
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    try {
      const res = await api.post("/assistant/chat", { message: text, history });
      setMessages((m) => [...m, { role: "assistant", content: res.data.reply, proposed_action: res.data.proposed_action }]);
    } catch (err) {
      setError(err.response?.data?.detail || "The assistant is unavailable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-4.5rem)]">
      <div className="mb-4">
        <h1 className="text-xl font-semibold text-slate-100 flex items-center gap-2">
          <Bot size={20} className="text-accent" /> AI Assistant
        </h1>
        <p className="text-sm text-muted mt-0.5">
          Ask about devices, alerts, or networks - it can search the fleet and pull up detail on its own. To run
          something on a device, it proposes an exact RouterOS script and target for you to confirm; it never
          executes on its own.
        </p>
      </div>

      <div className="card flex-1 min-h-0 flex flex-col">
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {messages.length === 0 && (
            <div className="text-sm text-muted">
              Try: "which antennas are offline right now", "any critical alerts today", or "log a test line on
              antenna-14".
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
              {m.role === "assistant" && (
                <div className="w-7 h-7 rounded-lg bg-accent/15 flex items-center justify-center shrink-0">
                  <Bot size={14} className="text-accent" />
                </div>
              )}
              <div className={`max-w-2xl ${m.role === "user" ? "order-1" : ""}`}>
                <div className={`rounded-lg px-3 py-2 text-sm ${m.role === "user" ? "bg-accent text-white" : "bg-panel2 text-slate-200"}`}>
                  {m.content}
                </div>
                {m.proposed_action && (
                  <ProposedActionCard action={m.proposed_action} onDone={() => {}} />
                )}
              </div>
              {m.role === "user" && (
                <div className="w-7 h-7 rounded-lg bg-panel2 flex items-center justify-center shrink-0">
                  <User size={14} className="text-muted" />
                </div>
              )}
            </div>
          ))}
          {busy && <div className="text-sm text-muted">Thinking...</div>}
          {error && <div className="text-sm text-crit">{error}</div>}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={send} className="border-t border-border p-3 flex items-center gap-2">
          <input
            className="input flex-1"
            placeholder="Ask about your fleet, or ask it to do something..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
          />
          <button className="btn btn-primary" disabled={busy || !input.trim()}>
            <Send size={15} />
          </button>
        </form>
      </div>
    </div>
  );
}
