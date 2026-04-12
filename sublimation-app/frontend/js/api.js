import { state } from './state.js';

export const API = "";

export async function apiFetch(path, options = {}) {
  const res  = await fetch(API + path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

export async function ensureSession() {
  if (state.sessionId) return;
  const fd = new FormData();
  fd.append("reference_size", "M");
  const data = await apiFetch("/session", { method: "POST", body: fd });
  state.sessionId = data.session_id;
}
