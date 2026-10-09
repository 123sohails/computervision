// Upload tab: file selection, XHR upload with progress, video list.
const Upload = (() => {
  async function refreshVideos() {
    const [videos, locs] = await Promise.all([API.get("/api/videos"), API.get("/api/locations")]);
    const names = Object.fromEntries(locs.map((l) => [l.id, l.name]));
    $("#videos-table tbody").innerHTML = videos.map((v) => `
      <tr><td title="${esc(v.filename)}">${esc(v.filename)}<br><span class="muted">${fmtBytes(v.size_bytes)}</span></td>
      <td>${esc(names[v.location_id] || "–")}</td>
      <td>${v.width}×${v.height} ${esc(v.orientation)}<br><span class="muted">${v.fps} fps · ${esc(v.codec)}</span></td>
      <td>${fmtTime(v.duration)}</td>
      <td class="row"><button data-act="zones" data-id="${v.id}" data-loc="${esc(v.location_id || "")}">Zones</button>
        <button data-act="run" data-id="${v.id}">Analyse</button>
        <button data-act="del" data-id="${v.id}" class="danger">✕</button></td></tr>`).join("")
      || `<tr><td colspan="5" class="muted">No videos uploaded yet.</td></tr>`;
    $$("#videos-table button").forEach((b) => b.onclick = () => act(b.dataset));
  }

  async function act({ act, id, loc }) {
    try {
      if (act === "run") {
        const j = await API.post(`/api/videos/${id}/jobs`, {});
        toast("Analysis queued"); App.show("dashboard"); Bus.emit("job-created", j.id);
      } else if (act === "zones") {
        App.show("zones"); Bus.emit("edit-zones", { videoId: id, locationId: loc });
      } else if (act === "del" && confirm("Delete this video and all its analysis results?")) {
        await API.del(`/api/videos/${id}`); refreshVideos(); Dashboard.refreshList();
      }
    } catch (e) { toast(e.message, true); }
  }

  function upload(form) {
    const data = new FormData(form);
    data.set("auto_process", form.auto_process.checked ? "true" : "false");
    for (const k of ["frame_stride", "conf_threshold", "imgsz"]) if (!data.get(k)) data.delete(k);
    const prog = $("#upload-progress"), bar = $(".bar", prog), label = $("span", prog);
    prog.classList.remove("hidden");
    $("#upload-result").innerHTML = "";
    const btn = $("button[type=submit]", form); btn.disabled = true;
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/videos");
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const p = (100 * e.loaded) / e.total;
      bar.style.width = p + "%"; label.textContent = p < 100 ? `Uploading ${p.toFixed(0)}%` : "Validating video…";
    };
    xhr.onload = () => {
      btn.disabled = false; prog.classList.add("hidden");
      let body = {}; try { body = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status >= 300) {
        $("#upload-result").innerHTML = `<div class="alert error">${esc(body.detail || xhr.statusText)}</div>`;
        return;
      }
      const v = body.video;
      $("#upload-result").innerHTML = `<div class="alert ${v.warnings.length ? "warn" : ""}">
        Uploaded <b>${esc(v.filename)}</b>: ${v.width}×${v.height} ${v.orientation}, ${v.fps} fps, ${fmtTime(v.duration)}, ${v.frame_count} frames.
        ${v.warnings.map((w) => `<br>⚠ ${esc(w)}`).join("")}
        <div class="row">${body.job ? `<button id="go-dash" class="primary">View analysis</button>` : ""}<button id="go-zones">Draw zones on this video</button></div></div>`;
      if (body.job) { $("#go-dash").onclick = () => { App.show("dashboard"); }; Bus.emit("job-created", body.job.id); }
      $("#go-zones").onclick = () => { App.show("zones"); Bus.emit("edit-zones", { videoId: v.id, locationId: v.location_id }); };
      form.reset(); $("#upload-filename").textContent = "";
      refreshVideos(); Bus.emit("videos-changed");
    };
    xhr.onerror = () => { btn.disabled = false; prog.classList.add("hidden"); toast("Upload failed (network error)", true); };
    xhr.send(data);
  }

  function init() {
    const form = $("#upload-form"), dz = $("#dropzone"), input = $("#upload-file");
    input.onchange = () => $("#upload-filename").textContent = input.files[0]?.name || "";
    ["dragenter", "dragover"].forEach((e) => dz.addEventListener(e, () => dz.classList.add("drag")));
    ["dragleave", "drop"].forEach((e) => dz.addEventListener(e, () => dz.classList.remove("drag")));
    form.onsubmit = (e) => { e.preventDefault(); upload(form); };
    Bus.on("locations-changed", () => fillLocationSelect($("#upload-location"), { includeNone: true, selected: $("#upload-location").value }));
  }

  return { init, refreshVideos };
})();
