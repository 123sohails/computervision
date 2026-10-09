// Minimal API client + shared helpers.
const API = {
  async req(method, url, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const res = await fetch(url, opts);
    if (!res.ok) {
      let msg = res.statusText;
      try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) {}
      throw new Error(msg);
    }
    return res.status === 204 ? null : res.json();
  },
  get: (u) => API.req("GET", u),
  post: (u, b) => API.req("POST", u, b),
  put: (u, b) => API.req("PUT", u, b),
  del: (u) => API.req("DELETE", u),
};

const Bus = {
  handlers: {},
  on(evt, fn) { (this.handlers[evt] ||= []).push(fn); },
  emit(evt, data) { (this.handlers[evt] || []).forEach((fn) => fn(data)); },
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = (s) => {
  if (s == null) return "–";
  const m = Math.floor(s / 60), sec = s - m * 60;
  return m ? `${m}:${sec.toFixed(1).padStart(4, "0")}` : `${sec.toFixed(1)} s`;
};
const fmtBytes = (b) => (b > 1e9 ? (b / 1e9).toFixed(2) + " GB" : (b / 1e6).toFixed(1) + " MB");
const ZONE_COLORS = { QUEUE_ZONE: "#ffa600", OCCUPANCY_ZONE: "#2fa0ff", ENTRY_LINE: "#3cdc3c", EXIT_LINE: "#e63c3c", EXCLUSION_ZONE: "#909090" };
const ZONE_LABELS = { QUEUE_ZONE: "Queue", OCCUPANCY_ZONE: "Occupancy", ENTRY_LINE: "Entry line", EXIT_LINE: "Exit line", EXCLUSION_ZONE: "Exclusion" };

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 3500);
}

async function fillLocationSelect(select, { includeNone = false, selected } = {}) {
  const locs = await API.get("/api/locations");
  select.innerHTML = (includeNone ? '<option value="">(no location)</option>' : "") +
    locs.map((l) => `<option value="${esc(l.id)}">${esc(l.name)} (${l.zone_count} zones)</option>`).join("");
  if (selected && locs.some((l) => l.id === selected)) select.value = selected;
  return locs;
}
