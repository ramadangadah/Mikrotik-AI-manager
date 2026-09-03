import React, { useEffect, useState } from "react";
import { UploadCloud, Trash2, Rocket } from "lucide-react";
import api from "../api/client.js";

export default function FirmwarePage() {
  const [files, setFiles] = useState([]);
  const [cpes, setCpes] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [meta, setMeta] = useState({ version: "", architecture: "", notes: "" });
  const [pickedFile, setPickedFile] = useState(null);
  const [pushForm, setPushForm] = useState({ firmware_id: "", cpe_id: "", ssh_port: 22 });
  const [pushMsg, setPushMsg] = useState("");

  async function load() {
    const [f, c] = await Promise.all([api.get("/firmware"), api.get("/cpes")]);
    setFiles(f.data);
    setCpes(c.data);
  }

  useEffect(() => { load(); }, []);

  async function upload(e) {
    e.preventDefault();
    if (!pickedFile) return;
    setUploading(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", pickedFile);
      const params = new URLSearchParams();
      if (meta.version) params.set("version", meta.version);
      if (meta.architecture) params.set("architecture", meta.architecture);
      if (meta.notes) params.set("notes", meta.notes);
      await api.post(`/firmware/upload?${params.toString()}`, form, { headers: { "Content-Type": "multipart/form-data" } });
      setPickedFile(null);
      setMeta({ version: "", architecture: "", notes: "" });
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function remove(id) {
    if (!confirm("Delete this firmware file?")) return;
    await api.delete(`/firmware/${id}`);
    await load();
  }

  async function push(e) {
    e.preventDefault();
    if (!pushForm.firmware_id || !pushForm.cpe_id) return;
    setPushMsg("Starting push job...");
    try {
      const res = await api.post("/firmware/push", {
        cpe_id: Number(pushForm.cpe_id), firmware_id: Number(pushForm.firmware_id), ssh_port: Number(pushForm.ssh_port),
      });
      setPushMsg(`Job #${res.data.id} started (${res.data.status}). It uploads via SFTP - works for bridge-mode CPEs via SOCKS relay or VPN tunnel too - then reboots the device and waits for it to come back. Check Jobs / device detail for progress.`);
    } catch (err) {
      setPushMsg(err.response?.data?.detail || "Push failed to start");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Firmware</h1>
        <p className="text-sm text-muted mt-0.5">
          Upload RouterOS .npk packages here, then push them to any CPE - including bridge-mode antennas with no
          direct internet, reached the same way as any other management call (SOCKS relay or VPN tunnel).
        </p>
      </div>

      <form onSubmit={upload} className="card p-5 grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
        <div className="md:col-span-4">
          <label className="label">.npk file</label>
          <input
            className="input"
            type="file"
            accept=".npk"
            onChange={(e) => setPickedFile(e.target.files?.[0] || null)}
          />
        </div>
        <div>
          <label className="label">Version (optional)</label>
          <input className="input" value={meta.version} onChange={(e) => setMeta({ ...meta, version: e.target.value })} placeholder="7.16" />
        </div>
        <div>
          <label className="label">Architecture (optional)</label>
          <input className="input" value={meta.architecture} onChange={(e) => setMeta({ ...meta, architecture: e.target.value })} placeholder="arm, mipsbe..." />
        </div>
        <div className="md:col-span-2">
          <label className="label">Notes (optional)</label>
          <input className="input" value={meta.notes} onChange={(e) => setMeta({ ...meta, notes: e.target.value })} />
        </div>
        {error && <div className="md:col-span-4 text-sm text-crit">{error}</div>}
        <div className="md:col-span-4">
          <button className="btn btn-primary" disabled={uploading || !pickedFile}>
            <UploadCloud size={15} /> {uploading ? "Uploading..." : "Upload firmware"}
          </button>
        </div>
      </form>

      <div className="card divide-y divide-border">
        {files.length === 0 && <div className="p-6 text-center text-muted text-sm">No firmware files uploaded yet.</div>}
        {files.map((f) => (
          <div key={f.id} className="p-4 flex items-center justify-between">
            <div className="min-w-0">
              <div className="text-sm font-medium text-slate-100">{f.filename}</div>
              <div className="text-xs text-muted">
                {f.version ? `v${f.version} · ` : ""}{f.architecture ? `${f.architecture} · ` : ""}
                sha256 {f.sha256?.slice(0, 12)}... · uploaded {new Date(f.uploaded_at).toLocaleString()}
              </div>
              {f.notes && <div className="text-xs text-muted mt-0.5">{f.notes}</div>}
            </div>
            <button className="btn btn-danger !px-2" title="Delete" onClick={() => remove(f.id)}>
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      <div className="card p-5">
        <h2 className="font-medium text-slate-100 mb-3">Push to a device</h2>
        <form onSubmit={push} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <div>
            <label className="label">Firmware file</label>
            <select className="input" value={pushForm.firmware_id} onChange={(e) => setPushForm({ ...pushForm, firmware_id: e.target.value })}>
              <option value="">Select...</option>
              {files.map((f) => <option key={f.id} value={f.id}>{f.filename}</option>)}
            </select>
          </div>
          <div>
            <label className="label">CPE</label>
            <select className="input" value={pushForm.cpe_id} onChange={(e) => setPushForm({ ...pushForm, cpe_id: e.target.value })}>
              <option value="">Select...</option>
              {cpes.filter((c) => c.connection_mode !== "unmanaged").map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label">SSH port</label>
            <input className="input" type="number" value={pushForm.ssh_port} onChange={(e) => setPushForm({ ...pushForm, ssh_port: e.target.value })} />
          </div>
          <button className="btn btn-primary"><Rocket size={14} /> Push firmware</button>
        </form>
        {pushMsg && <div className="text-sm text-slate-300 mt-3">{pushMsg}</div>}
      </div>
    </div>
  );
}
