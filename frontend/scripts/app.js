// Tab routing and bootstrapping.
const App = {
  show(tab) {
    $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    $$(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${tab}`));
    if (location.hash !== `#${tab}`) history.replaceState(null, "", `#${tab}`);
    Bus.emit("tab-shown", tab);
  },
};

window.addEventListener("DOMContentLoaded", async () => {
  $$(".tabs button").forEach((b) => b.onclick = () => App.show(b.dataset.tab));
  Dashboard.init(); Upload.init(); Zones.init(); Locations.init();
  await fillLocationSelect($("#upload-location"), { includeNone: true });
  await Promise.all([Dashboard.refreshList(), Upload.refreshVideos(), Zones.refresh(), Locations.refresh()]);
  const tab = location.hash.slice(1);
  if (["dashboard", "upload", "zones", "locations"].includes(tab)) App.show(tab);
});
