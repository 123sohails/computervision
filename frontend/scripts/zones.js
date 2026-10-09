// Zones tab: polygon / line editor on a reference frame. Points are stored relative (0..1).
const Zones = (() => {
  let locationId = null, zones = [], videos = [];
  let edit = null;      // { id|null, zone_type, points: [[x,y]], closed }
  let drag = null;      // index of point being dragged
  const HANDLE = 7;
  const canvas = () => $("#editor-canvas");
  const img = () => $("#editor-img");
  const form = () => $("#zone-form");
  const isLine = (t) => t === "ENTRY_LINE" || t === "EXIT_LINE";

  function newEdit() {
    edit = { id: null, zone_type: form().zone_type.value, points: [], closed: false };
    form().reset(); form().zone_type.value = edit.zone_type;
    $("#zone-form-title").textContent = "New zone";
    $("#zone-delete").classList.add("hidden");
    msg("");
    syncFormVisibility(); renderList(); draw();
  }

  function selectZone(z) {
    edit = { id: z.id, zone_type: z.zone_type, points: z.points.map((p) => [...p]), closed: true };
    const f = form();
    f.zone_type.value = z.zone_type; f.name.value = z.name;
    f.capacity.value = z.capacity ?? "";
    f.queue_threshold.value = z.settings.queue_threshold ?? "";
    f.occupancy_pct_threshold.value = z.settings.occupancy_pct_threshold ?? "";
    f.bidirectional.checked = z.settings.bidirectional ?? true;
    $("#zone-form-title").textContent = `Edit: ${z.name}`;
    $("#zone-delete").classList.remove("hidden");
    msg("");
    syncFormVisibility(); renderList(); draw();
  }

  function msg(text, cls = "") { const m = $("#zone-msg"); m.textContent = text; m.className = "msg " + cls; }

  function syncFormVisibility() {
    const t = form().zone_type.value;
    $$("#zone-form [class*='only-']").forEach((el) => el.classList.toggle("hidden", !el.classList.contains(`only-${t}`)));
  }

  function renderList() {
    $("#zone-list").innerHTML = zones.map((z) => `
      <li data-id="${esc(z.id)}" class="${edit?.id === z.id ? "active" : ""}">
        <span class="swatch" style="background:${ZONE_COLORS[z.zone_type]}"></span>
        <span><b>${esc(z.name)}</b><br><span class="muted">${ZONE_LABELS[z.zone_type]}${z.capacity ? ` · capacity ${z.capacity}` : ""}</span></span>
      </li>`).join("") || `<li class="muted">No zones yet.</li>`;
    $$("#zone-list li[data-id]").forEach((li) => li.onclick = () => selectZone(zones.find((z) => z.id === li.dataset.id)));
  }

  // ---- canvas ----
  function size() {
    const c = canvas(), r = img().getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    c.width = Math.max(1, r.width * dpr); c.height = Math.max(1, r.height * dpr);
    return { w: c.width, h: c.height, dpr };
  }

  function shape(ctx, pts, type, closed, w, h, highlight) {
    if (!pts.length) return;
    const color = ZONE_COLORS[type];
    const abs = pts.map(([x, y]) => [x * w, y * h]);
    ctx.lineWidth = (highlight ? 3 : 2) * (window.devicePixelRatio || 1);
    ctx.strokeStyle = color; ctx.fillStyle = color + "33";
    ctx.beginPath(); abs.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    if (!isLine(type) && closed) { ctx.closePath(); ctx.fill(); }
    ctx.stroke();
    if (isLine(type) && abs.length === 2) {
      const [[x1, y1], [x2, y2]] = abs, dx = x2 - x1, dy = y2 - y1, L = Math.hypot(dx, dy) || 1;
      const nx = -dy / L, ny = dx / L, mx = (x1 + x2) / 2, my = (y1 + y2) / 2, len = Math.max(30, 0.06 * w);
      const tx = mx + nx * len, ty = my + ny * len;
      ctx.beginPath(); ctx.moveTo(mx, my); ctx.lineTo(tx, ty); ctx.stroke();
      const a = Math.atan2(ty - my, tx - mx), s = 10 * (window.devicePixelRatio || 1);
      ctx.beginPath(); ctx.moveTo(tx, ty);
      ctx.lineTo(tx - s * Math.cos(a - 0.5), ty - s * Math.sin(a - 0.5));
      ctx.lineTo(tx - s * Math.cos(a + 0.5), ty - s * Math.sin(a + 0.5)); ctx.closePath();
      ctx.fillStyle = color; ctx.fill();
      ctx.font = `${12 * (window.devicePixelRatio || 1)}px sans-serif`;
      ctx.fillText(type === "ENTRY_LINE" ? "entry →" : "exit →", tx + 4, ty);
    }
    if (highlight) {
      abs.forEach(([x, y], i) => {
        ctx.beginPath(); ctx.arc(x, y, HANDLE * (window.devicePixelRatio || 1), 0, Math.PI * 2);
        ctx.fillStyle = i === 0 && !closed ? "#fff" : color; ctx.fill();
        ctx.strokeStyle = "#000"; ctx.lineWidth = 1; ctx.stroke();
      });
    }
  }

  function draw() {
    if (!img().complete || !img().naturalWidth) return;
    const { w, h } = size();
    const ctx = canvas().getContext("2d");
    ctx.clearRect(0, 0, w, h);
    for (const z of zones) if (!edit || z.id !== edit.id) shape(ctx, z.points, z.zone_type, true, w, h, false);
    if (edit) shape(ctx, edit.points, edit.zone_type, edit.closed || isLine(edit.zone_type), w, h, true);
  }

  function rel(e) {
    const r = canvas().getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
  }

  function hitPoint(p) {
    const r = canvas().getBoundingClientRect();
    return (edit?.points || []).findIndex(([x, y]) => Math.hypot((x - p[0]) * r.width, (y - p[1]) * r.height) <= HANDLE + 3);
  }

  function onDown(e) {
    if (!edit) newEdit();
    const p = rel(e), hit = hitPoint(p);
    if (hit === 0 && !edit.closed && !isLine(edit.zone_type) && edit.points.length >= 3) { edit.closed = true; draw(); return; }
    if (hit >= 0) { drag = hit; return; }
    const full = isLine(edit.zone_type) ? edit.points.length >= 2 : edit.closed;
    if (full) return msg("Shape complete. Drag points to adjust, or Clear points to redraw.");
    edit.points.push(p);
    if (isLine(edit.zone_type) && edit.points.length === 2) edit.closed = true;
    draw();
  }

  function onMove(e) {
    if (drag == null) return;
    edit.points[drag] = rel(e); draw();
  }

  // ---- data ----
  async function loadZones() {
    zones = locationId ? await API.get(`/api/zones?location_id=${encodeURIComponent(locationId)}`) : [];
    renderList(); draw();
  }

  async function loadVideos(preferId) {
    videos = await API.get("/api/videos");
    videos.sort((a, b) => (b.location_id === locationId) - (a.location_id === locationId));
    const sel = $("#zones-video");
    sel.innerHTML = videos.map((v) => `<option value="${v.id}">${v.location_id === locationId ? "" : "(other location) "}${esc(v.filename)} · ${v.width}×${v.height}</option>`).join("");
    if (preferId && videos.some((v) => v.id === preferId)) sel.value = preferId;
    setVideo(sel.value);
  }

  function setVideo(id) {
    const v = videos.find((x) => x.id === id);
    $("#editor-empty").classList.toggle("hidden", !!v);
    img().classList.toggle("hidden", !v);
    if (!v) { canvas().getContext("2d").clearRect(0, 0, canvas().width, canvas().height); return; }
    const slider = $("#zones-time");
    slider.max = Math.max(0, (v.duration || 0) - 0.1).toFixed(1);
    slider.value = Math.min(+slider.value, +slider.max);
    loadFrame();
  }

  function loadFrame() {
    const id = $("#zones-video").value;
    if (!id) return;
    const t = +$("#zones-time").value;
    $("#zones-time-label").textContent = `${t.toFixed(1)} s`;
    img().src = `/api/videos/${id}/frame?t=${t}`;
  }

  async function save(e) {
    e.preventDefault();
    if (!locationId) return msg("Select a location first.", "error");
    const f = form(), type = f.zone_type.value;
    if (!edit) return msg("Draw the zone on the frame first.", "error");
    const need = isLine(type) ? 2 : 3;
    if (edit.points.length < need || (!isLine(type) && !edit.closed && edit.points.length < 3))
      return msg(isLine(type) ? "A line needs 2 points." : "A polygon needs at least 3 points.", "error");
    const settings = {};
    if (type === "QUEUE_ZONE" && f.queue_threshold.value) settings.queue_threshold = +f.queue_threshold.value;
    if (type === "OCCUPANCY_ZONE" && f.occupancy_pct_threshold.value) settings.occupancy_pct_threshold = +f.occupancy_pct_threshold.value;
    if (isLine(type)) settings.bidirectional = f.bidirectional.checked;
    const id = edit.id || `${locationId}-${f.name.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 30)}-${Math.random().toString(36).slice(2, 6)}`;
    const body = {
      location_id: locationId, name: f.name.value, zone_type: type,
      points: edit.points.map(([x, y]) => [+x.toFixed(4), +y.toFixed(4)]),
      capacity: type === "OCCUPANCY_ZONE" && f.capacity.value ? +f.capacity.value : null, settings,
    };
    try {
      const z = await API.put(`/api/zones/${encodeURIComponent(id)}`, body);
      await loadZones(); selectZone(z); msg("Saved. Re-run analysis to apply.", "ok");
      Bus.emit("locations-changed");
    } catch (err) { msg(err.message, "error"); }
  }

  async function refresh() {
    const locs = await fillLocationSelect($("#zones-location"), { selected: locationId });
    locationId = $("#zones-location").value || locs[0]?.id || null;
    await loadZones(); await loadVideos($("#zones-video").value);
    if (!edit) newEdit();
  }

  function init() {
    const c = canvas();
    c.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", () => (drag = null));
    img().addEventListener("load", draw);
    window.addEventListener("resize", draw);
    window.addEventListener("keydown", (e) => {
      if (!$("#tab-zones").classList.contains("active") || !edit || e.target.tagName === "INPUT") return;
      if (e.key === "Enter" && !isLine(edit.zone_type) && edit.points.length >= 3) { edit.closed = true; draw(); }
      if (e.key === "Escape") { edit.points = []; edit.closed = false; draw(); }
    });
    form().zone_type.onchange = () => {
      const t = form().zone_type.value;
      if (edit && isLine(t) !== isLine(edit.zone_type)) { edit.points = []; edit.closed = false; }
      if (edit) edit.zone_type = t;
      syncFormVisibility(); draw();
    };
    form().onsubmit = save;
    $("#zone-new").onclick = newEdit;
    $("#zone-clear").onclick = () => { if (edit) { edit.points = []; edit.closed = false; draw(); } };
    $("#zone-reverse").onclick = () => { if (edit?.points.length === 2) { edit.points.reverse(); draw(); } };
    $("#zone-delete").onclick = async () => {
      if (!edit?.id || !confirm("Delete this zone?")) return;
      await API.del(`/api/zones/${encodeURIComponent(edit.id)}`); await loadZones(); newEdit(); Bus.emit("locations-changed");
    };
    $("#zones-location").onchange = async (e) => { locationId = e.target.value; await loadZones(); await loadVideos(); newEdit(); };
    $("#zones-video").onchange = (e) => setVideo(e.target.value);
    $("#zones-time").oninput = () => { clearTimeout(loadFrame._t); loadFrame._t = setTimeout(loadFrame, 150); };
    Bus.on("tab-shown", (t) => t === "zones" && setTimeout(draw, 0));
    Bus.on("videos-changed", () => loadVideos($("#zones-video").value));
    Bus.on("locations-changed", () => fillLocationSelect($("#zones-location"), { selected: locationId }));
    Bus.on("edit-zones", async ({ videoId, locationId: loc }) => {
      if (loc) { locationId = loc; $("#zones-location").value = loc; await loadZones(); }
      await loadVideos(videoId); newEdit();
    });
    syncFormVisibility();
  }

  return { init, refresh };
})();
