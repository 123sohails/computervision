// Locations tab: list/create locations and edit congestion rules.
const Locations = (() => {
  const RULE_META = {
    queue_threshold: ["Queue alert threshold", "people"],
    occupancy_pct_threshold: ["Occupancy alert", "% of capacity"],
    sustained_seconds: ["Sustained for", "seconds"],
    growth_amount: ["Rapid growth: increase of", "people"],
    growth_window_seconds: ["Rapid growth: within", "seconds"],
    smoothing_seconds: ["Rolling average window", "seconds"],
    trend_window_seconds: ["Queue trend window", "seconds"],
    cooldown_seconds: ["Alert cooldown", "seconds"],
    dwell_absence_seconds: ["Dwell: visit ends after absent", "seconds"],
    line_cooldown_seconds: ["Line crossing cooldown per track", "seconds"],
  };
  let current = null;

  async function refresh(selectId) {
    const locs = await API.get("/api/locations");
    const ul = $("#location-list");
    ul.innerHTML = locs.map((l) => `<li data-id="${esc(l.id)}"><b>${esc(l.name)}</b><span class="muted">${l.zone_count} zones · ${esc(l.description)}</span></li>`).join("");
    $$("li", ul).forEach((li) => li.onclick = () => select(li.dataset.id));
    const id = selectId || current?.id || locs[0]?.id;
    if (id) select(id);
  }

  async function select(id) {
    current = await API.get(`/api/locations/${id}`);
    $$("#location-list li").forEach((li) => li.classList.toggle("active", li.dataset.id === id));
    const f = $("#rules-form");
    f.name.value = current.name; f.description.value = current.description || "";
    $("#rules-title").textContent = `Congestion rules · ${current.name}`;
    $("#rules-fields").innerHTML = Object.entries(RULE_META).map(([k, [label, unit]]) =>
      `<label>${label} <span class="muted">(${unit})</span><input type="number" step="any" min="0" name="${k}" value="${current.rules[k] ?? ""}"></label>`).join("");
    $("#rules-msg").textContent = "";
  }

  function init() {
    $("#rules-form").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target, rules = {};
      for (const k of Object.keys(RULE_META)) if (f[k].value !== "") rules[k] = +f[k].value;
      try {
        await API.put(`/api/locations/${current.id}`, { name: f.name.value, description: f.description.value, rules });
        $("#rules-msg").className = "msg ok"; $("#rules-msg").textContent = "Saved. Re-run analysis to apply.";
        refresh(current.id); Bus.emit("locations-changed");
      } catch (err) { $("#rules-msg").className = "msg error"; $("#rules-msg").textContent = err.message; }
    };
    $("#location-create").onsubmit = async (e) => {
      e.preventDefault();
      try {
        const loc = await API.post("/api/locations", { name: e.target.name.value });
        e.target.reset(); refresh(loc.id); Bus.emit("locations-changed");
      } catch (err) { toast(err.message, true); }
    };
    $("#location-delete").onclick = async () => {
      if (!current || !confirm(`Delete location "${current.name}" and its zones? Videos are kept.`)) return;
      await API.del(`/api/locations/${current.id}`); current = null; refresh(); Bus.emit("locations-changed");
    };
  }

  return { init, refresh };
})();
