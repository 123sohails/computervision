// Dashboard: job status polling, time-synced KPIs, charts, events, artifacts.
const Dashboard = (() => {
  let job = null, metrics = [], pollTimer = null, charts = {};
  const video = () => $("#job-video");

  const playhead = {
    id: "playhead",
    afterDatasetsDraw(chart) {
      const t = video()?.currentTime;
      if (t == null || !metrics.length) return;
      const x = chart.scales.x.getPixelForValue(t);
      const { top, bottom } = chart.chartArea;
      const ctx = chart.ctx;
      ctx.save(); ctx.strokeStyle = "rgba(255,255,255,.6)"; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke(); ctx.restore();
    },
  };

  function makeChart(canvas, datasets, yTitle) {
    return new Chart(canvas, {
      type: "line",
      data: { datasets },
      options: {
        animation: false, responsive: true, maintainAspectRatio: false, parsing: false, normalized: true,
        interaction: { mode: "nearest", axis: "x", intersect: false },
        scales: {
          x: { type: "linear", title: { display: true, text: "video time (s)", color: "#8a96ad" }, ticks: { color: "#8a96ad" }, grid: { color: "#232c40" } },
          y: { beginAtZero: true, title: { display: true, text: yTitle, color: "#8a96ad" }, ticks: { color: "#8a96ad", precision: 0 }, grid: { color: "#232c40" } },
        },
        plugins: { legend: { labels: { color: "#e6ebf5", boxWidth: 12 } }, decimation: { enabled: true, algorithm: "lttb" } },
        elements: { point: { radius: 0 }, line: { borderWidth: 2, tension: 0.2 } },
        onClick: (e, _els, chart) => {
          const t = chart.scales.x.getValueForPixel(e.x);
          if (t != null && video()) video().currentTime = Math.max(0, t);
        },
      },
      plugins: [playhead],
    });
  }

  function series(key, fn) {
    return metrics.filter((m) => fn(m) != null).map((m) => ({ x: m.timestamp, y: fn(m) }));
  }

  function smooth(points, win) {
    const out = [];
    let sum = 0, q = [];
    for (const p of points) {
      q.push(p); sum += p.y;
      while (q.length && p.x - q[0].x > win) sum -= q.shift().y;
      out.push({ x: p.x, y: +(sum / q.length).toFixed(2) });
    }
    return out;
  }

  function renderCharts() {
    Object.values(charts).forEach((c) => c.destroy());
    charts = {};
    const win = job.rules_snapshot?.smoothing_seconds || 3;
    const ds = [
      { label: "People in view", data: series("p", (m) => m.active_people), borderColor: "#c9d3e6", backgroundColor: "#c9d3e6" },
      { label: `People (rolling ${win}s)`, data: smooth(series("p", (m) => m.active_people), win), borderColor: "#7f8aa3", borderDash: [5, 4], backgroundColor: "#7f8aa3" },
    ];
    if (metrics.some((m) => m.queue_count != null))
      ds.push({ label: "Queue count", data: series("q", (m) => m.queue_count), borderColor: "#ffa600", backgroundColor: "#ffa600" });
    const occZones = (job.zones_snapshot || []).filter((z) => z.zone_type === "OCCUPANCY_ZONE");
    if (occZones.length)
      ds.push({ label: "Occupancy zone count", data: series("o", (m) => m.occupancy_count), borderColor: "#2fa0ff", backgroundColor: "#2fa0ff" });
    charts.counts = makeChart($("#chart-counts"), ds, "people");

    const hasFlow = metrics.some((m) => m.entries != null);
    charts.flow = makeChart($("#chart-flow"), hasFlow ? [
      { label: "Entries", data: series("e", (m) => m.entries), borderColor: "#3cdc3c", backgroundColor: "#3cdc3c", stepped: true },
      { label: "Exits", data: series("x", (m) => m.exits), borderColor: "#e63c3c", backgroundColor: "#e63c3c", stepped: true },
    ] : [], "count");
    $("#chart-flow").parentElement.title = hasFlow ? "" : "No entry/exit line configured";
  }

  function metricAt(t) {
    if (!metrics.length) return null;
    let lo = 0, hi = metrics.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (metrics[mid].timestamp <= t) lo = mid; else hi = mid - 1; }
    return metrics[lo];
  }

  function setKpi(id, value, sub, cls) {
    const el = $(`#kpi-${id}`);
    el.textContent = value; el.className = "value" + (cls ? " " + cls : "");
    $(`#kpi-${id}-sub`).textContent = sub || "";
  }

  function updateKpis() {
    const m = metricAt(video().currentTime || 0);
    if (!m) return;
    const s = job.summary || {};
    setKpi("people", m.active_people, `peak ${s.people?.peak ?? "–"} at ${fmtTime(s.people?.peak_time)}`);
    if (m.queue_count != null) {
      const trends = Object.values(m.zones).map((z) => z.trend).filter((v) => v != null);
      const trend = trends.length ? trends.reduce((a, b) => a + b, 0) : null;
      const win = Object.values(m.zones).find((z) => z.trend_window_s)?.trend_window_s;
      setKpi("queue", m.queue_count, trend == null ? "trend: collecting history" : `${trend >= 0 ? "+" : ""}${trend.toFixed(1)} people over ${win}s`);
    } else setKpi("queue", "n/a", "no queue zone configured");
    if (m.occupancy_pct != null) {
      const cap = (job.zones_snapshot || []).filter((z) => z.zone_type === "OCCUPANCY_ZONE").reduce((a, z) => a + (z.capacity || 0), 0);
      setKpi("occ", `${m.occupancy_count} / ${cap}`, `${m.occupancy_pct.toFixed(0)}% of configured capacity`);
    } else setKpi("occ", m.occupancy_count, (job.zones_snapshot || []).some((z) => z.zone_type === "OCCUPANCY_ZONE") ? "no capacity configured" : "whole frame (no occupancy zone)");
    if (m.entries != null) setKpi("flow", `${m.entries} / ${m.exits}`, `net flow ${m.entries - m.exits >= 0 ? "+" : ""}${m.entries - m.exits}`);
    else setKpi("flow", "n/a", "no entry/exit line configured");
    const reasons = activeEvents(m.timestamp);
    setKpi("status", m.congestion_status, reasons[0] ? reasons[0].event_type.replaceAll("_", " ").toLowerCase() + " · " + reasons[0].zone_name : "", "status-" + m.congestion_status);
    Object.values(charts).forEach((c) => c.draw());
  }

  let events = [];
  const activeEvents = (t) => events.filter((e) => e.start_time <= t && (e.end_time == null || e.end_time >= t));

  function renderEvents() {
    const tb = $("#events-table tbody");
    tb.innerHTML = events.length ? events.map((e) => `
      <tr class="clickable" data-t="${e.start_time}">
        <td>${fmtTime(e.start_time)}${e.end_time != null ? " – " + fmtTime(e.end_time) : ""}</td>
        <td><span class="badge ${e.severity}">${esc(e.event_type.replaceAll("_", " "))}</span></td>
        <td>${esc(e.zone_name)}</td><td>${esc(e.reason)}</td></tr>`).join("")
      : `<tr><td colspan="4" class="muted">No congestion events under the configured rules.</td></tr>`;
    $$("tr.clickable", tb).forEach((tr) => tr.onclick = () => { video().currentTime = +tr.dataset.t; video().play(); });
  }

  function renderZoneSummary() {
    const s = job.summary || {};
    const rows = [];
    const dwell = (d) => d?.fully_observed?.median != null ? `${d.fully_observed.median}s (n=${d.fully_observed.count})`
      : d?.observed?.count ? `${d.observed.median}s observed only` : "–";
    for (const q of Object.values(s.queues || {}))
      rows.push(`<tr><td><span class="swatch" style="background:${ZONE_COLORS.QUEUE_ZONE};display:inline-block"></span> ${esc(q.name)}</td><td>${q.peak} at ${fmtTime(q.peak_time)}</td><td>${q.mean}</td><td>${dwell(q.dwell)}</td><td>${q.time_alerting_s}s</td></tr>`);
    for (const o of Object.values(s.occupancy || {}))
      rows.push(`<tr><td><span class="swatch" style="background:${ZONE_COLORS.OCCUPANCY_ZONE};display:inline-block"></span> ${esc(o.name)}</td><td>${o.peak}${o.capacity ? ` / ${o.capacity} (${o.peak_utilisation_pct}%)` : ""}</td><td>${o.mean}</td><td>${dwell(o.dwell)}</td><td>${o.time_alerting_s}s</td></tr>`);
    for (const l of Object.values(s.lines || {}))
      rows.push(`<tr><td><span class="swatch" style="background:${ZONE_COLORS[l.type]};display:inline-block"></span> ${esc(l.name)}</td><td colspan="4">${l.entries} entries · ${l.exits} exits</td></tr>`);
    $("#zones-table tbody").innerHTML = rows.join("") || `<tr><td colspan="5" class="muted">No zones were configured for this run. Add zones in the Zones tab and re-run.</td></tr>`;

    const st = job.stats || {}, v = job.video || {}, p = job.params || {};
    const items = [
      ["Video", `${v.width}×${v.height} ${v.orientation}, ${v.fps} fps, ${fmtTime(v.duration)}`],
      ["Frames processed", `${st.frames_processed ?? "–"} (every ${p.frame_stride} frame${p.frame_stride > 1 ? "s" : ""}, ${s.effective_fps ?? "–"} fps)`],
      ["Detector", `${st.detector ?? "–"} @ ${p.imgsz}px, conf ≥ ${p.conf_threshold}`],
      ["Processing speed", st.processing_fps ? `${st.processing_fps} frames/s · ${st.detector_ms_per_frame} ms detection · ${st.realtime_factor}× real time` : "–"],
      ["Wall time", st.wall_time_s ? `${st.wall_time_s}s` : "–"],
      ["Distinct track IDs", s.people ? `${s.people.unique_track_ids} (upper bound on people)` : "–"],
    ];
    $("#run-stats").innerHTML = items.map(([k, val]) => `<dt>${k}</dt><dd>${esc(val)}</dd>`).join("");
  }

  async function loadResults() {
    const id = job.id;
    [metrics, events] = await Promise.all([API.get(`/api/jobs/${id}/metrics`), API.get(`/api/jobs/${id}/events`)]);
    const bust = `?v=${job.finished_at}`;
    video().src = `/api/jobs/${id}/video${bust}`;
    $("#img-heatmap").src = `/api/jobs/${id}/heatmap.png${bust}`;
    $("#img-trails").src = `/api/jobs/${id}/trails.png${bust}`;
    $("#dl-video").href = `/api/jobs/${id}/video?download=true`;
    $("#dl-csv").href = `/api/jobs/${id}/report.csv`;
    $("#dl-json").href = `/api/jobs/${id}/report.json`;
    $("#dl-det").href = `/api/jobs/${id}/detections.csv`;
    renderCharts(); renderEvents(); renderZoneSummary(); updateKpis();
  }

  function renderStatus() {
    const v = job.video || {};
    $("#job-status").innerHTML = `<span class="badge ${job.status}">${job.status}</span> ${esc(v.filename || "")} · ${esc(job.location_name || "no location")}`;
    $("#video-meta").textContent = v.width ? `${v.width}×${v.height} · ${fmtTime(v.duration)}` : "";
    const prog = $("#job-progress");
    const running = job.status === "queued" || job.status === "processing";
    prog.classList.toggle("hidden", !running);
    if (running) {
      $(".bar", prog).style.width = `${(job.progress * 100).toFixed(0)}%`;
      $("span", prog).textContent = job.status === "queued" ? "Queued…" : `Processing ${(job.progress * 100).toFixed(0)}%`;
    }
    $("#job-error").classList.toggle("hidden", job.status !== "failed");
    $("#job-error").textContent = job.error ? `Processing failed: ${job.error}` : "";
    const warns = v.warnings || [];
    $("#job-warnings").classList.toggle("hidden", !warns.length);
    $("#job-warnings").innerHTML = warns.map(esc).join("<br>");
    $$("#job-view .kpis, #job-view .grid-2, #job-view .hint").forEach((el) => el.classList.toggle("hidden", job.status !== "completed"));
  }

  async function select(id) {
    clearTimeout(pollTimer);
    if (!id) return;
    job = await API.get(`/api/jobs/${id}`);
    $("#job-view").classList.remove("hidden");
    renderStatus();
    if (job.status === "completed") await loadResults();
    else if (job.status === "queued" || job.status === "processing") pollTimer = setTimeout(() => poll(id), 1000);
  }

  async function poll(id) {
    if (!job || job.id !== id) return;
    job = await API.get(`/api/jobs/${id}`);
    renderStatus();
    if (job.status === "completed") { await loadResults(); await refreshList(id); toast("Analysis completed"); }
    else if (job.status === "failed") await refreshList(id);
    else pollTimer = setTimeout(() => poll(id), 1000);
  }

  async function refreshList(selectId) {
    const jobs = await API.get("/api/jobs");
    const sel = $("#job-select");
    sel.innerHTML = jobs.map((j) => `<option value="${j.id}">${esc(j.filename)} · ${esc(j.location_name || "no location")} · ${new Date(j.created_at * 1000).toLocaleString()} [${j.status}]</option>`).join("");
    $("#job-empty").classList.toggle("hidden", jobs.length > 0);
    $("#job-view").classList.toggle("hidden", jobs.length === 0);
    const target = selectId || (job && jobs.some((j) => j.id === job.id) ? job.id : jobs[0]?.id);
    if (target) { sel.value = target; if (!job || job.id !== target || selectId) await select(target); }
  }

  function init() {
    $("#job-select").onchange = (e) => select(e.target.value);
    $("#job-refresh").onclick = () => refreshList();
    ["timeupdate", "seeked", "loadeddata"].forEach((ev) => video().addEventListener(ev, updateKpis));
    $("#job-reprocess").onclick = async () => {
      try {
        const j = await API.post(`/api/videos/${job.video_id}/jobs`, job.params);
        toast("New analysis queued");
        await refreshList(j.id);
      } catch (e) { toast(e.message, true); }
    };
    Bus.on("job-created", (id) => refreshList(id));
  }

  return { init, refreshList };
})();
