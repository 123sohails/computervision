"""Rule-based congestion detection with transparent, human-readable reasons."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from backend.services.zone_manager import OCCUPANCY_ZONE, QUEUE_ZONE, Zone

QUEUE_THRESHOLD = "QUEUE_THRESHOLD"
OCCUPANCY_THRESHOLD = "OCCUPANCY_THRESHOLD"
SUSTAINED_CONGESTION = "SUSTAINED_CONGESTION"
RAPID_GROWTH = "RAPID_GROWTH"

STATUS_ORDER = {"normal": 0, "elevated": 1, "congested": 2}


@dataclass
class CongestionEvent:
    event_type: str
    severity: str
    zone_id: str
    zone_name: str
    start_time: float
    threshold: float
    peak_value: float
    reason: str
    end_time: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["peak_value"] = round(self.peak_value, 2)
        return d


@dataclass
class _Condition:
    active: bool = False
    since: float = 0.0
    peak: float = 0.0
    event: CongestionEvent | None = None
    sustained_event: CongestionEvent | None = None
    last_end: dict = field(default_factory=dict)  # event_type -> end time of last event


def _rule(zone: Zone, rules: dict, key: str):
    return zone.settings.get(key, rules.get(key))


class CongestionEngine:
    """Evaluates per-zone rules on smoothed values.

    * QUEUE_THRESHOLD: rolling-average queue count exceeds `queue_threshold`.
    * OCCUPANCY_THRESHOLD: rolling-average utilisation exceeds `occupancy_pct_threshold`.
    * SUSTAINED_CONGESTION: either threshold holds for `sustained_seconds`.
    * RAPID_GROWTH: queue grows by >= `growth_amount` within `growth_window_seconds`.

    The same alert type is not re-raised for a zone within `cooldown_seconds` of the
    previous one ending. Release uses a small hysteresis to avoid flapping.
    """

    def __init__(self, zones: list[Zone], rules: dict):
        self.rules = rules
        self.zones = {z.id: z for z in zones if z.zone_type in (QUEUE_ZONE, OCCUPANCY_ZONE)}
        self.state: dict[tuple[str, str], _Condition] = {}
        self.events: list[CongestionEvent] = []
        self.zone_status: dict[str, str] = {zid: "normal" for zid in self.zones}

    def _cond(self, zone_id: str, kind: str) -> _Condition:
        return self.state.setdefault((zone_id, kind), _Condition())

    def _can_open(self, cond: _Condition, event_type: str, t: float, cooldown: float) -> bool:
        last = cond.last_end.get(event_type)
        return last is None or t - last >= cooldown

    def _open(self, cond, event_type, severity, zone, t, threshold, value, reason) -> CongestionEvent:
        ev = CongestionEvent(event_type, severity, zone.id, zone.name, round(t, 3), threshold, value, reason)
        self.events.append(ev)
        return ev

    def _close(self, cond: _Condition, t: float, suffix: str = "") -> None:
        for attr in ("event", "sustained_event"):
            ev = getattr(cond, attr)
            if ev is not None:
                ev.end_time = round(t, 3)
                ev.peak_value = max(ev.peak_value, cond.peak)
                dur = ev.end_time - ev.start_time
                ev.reason += f" Lasted {dur:.0f} s, peak {ev.peak_value:.1f}.{suffix}"
                cond.last_end[ev.event_type] = t
                setattr(cond, attr, None)

    def _threshold_rule(self, zone: Zone, kind: str, t: float, value: float | None,
                        threshold: float | None, unit: str, label: str) -> str:
        if value is None or threshold is None:
            return "normal"
        cond = self._cond(zone.id, kind)
        cooldown = float(_rule(zone, self.rules, "cooldown_seconds") or 0)
        sustained = float(_rule(zone, self.rules, "sustained_seconds") or 0)
        smoothing = float(_rule(zone, self.rules, "smoothing_seconds") or 0)
        release = threshold - max(0.5, 0.1 * threshold)

        if not cond.active and value > threshold:
            cond.active, cond.since, cond.peak = True, t, value
            if self._can_open(cond, kind, t, cooldown):
                cond.event = self._open(
                    cond, kind, "warning", zone, t, threshold, value,
                    f"{label} in '{zone.name}' averaged {value:.1f}{unit} over {smoothing:.0f} s, "
                    f"above the configured limit of {threshold:g}{unit}.")
        elif cond.active and value <= release:
            self._close(cond, t)
            cond.active = False
            return "normal"

        if not cond.active:
            return "normal"
        cond.peak = max(cond.peak, value)
        if cond.event:
            cond.event.peak_value = cond.peak
        if t - cond.since >= sustained:
            if cond.sustained_event is None and self._can_open(cond, SUSTAINED_CONGESTION, t, cooldown):
                cond.sustained_event = self._open(
                    cond, SUSTAINED_CONGESTION, "critical", zone, cond.since, threshold, cond.peak,
                    f"{label} in '{zone.name}' stayed above the configured limit of {threshold:g}{unit} "
                    f"for at least {sustained:.0f} s.")
            if cond.sustained_event:
                cond.sustained_event.peak_value = cond.peak
            return "congested"
        return "elevated"

    def _growth_rule(self, zone: Zone, t: float, rise: float | None) -> str:
        amount = _rule(zone, self.rules, "growth_amount")
        window = float(_rule(zone, self.rules, "growth_window_seconds") or 60)
        if rise is None or not amount:
            return "normal"
        cond = self._cond(zone.id, RAPID_GROWTH)
        cooldown = float(_rule(zone, self.rules, "cooldown_seconds") or 0)
        if rise >= amount:
            if not cond.active:
                cond.active, cond.since, cond.peak = True, t, rise
                if self._can_open(cond, RAPID_GROWTH, t, cooldown):
                    cond.event = self._open(
                        cond, RAPID_GROWTH, "warning", zone, t, float(amount), rise,
                        f"Queue in '{zone.name}' grew by {rise:.1f} people within {window:.0f} s "
                        f"(configured limit +{amount}).")
            cond.peak = max(cond.peak, rise)
            return "elevated"
        if cond.active and rise < amount * 0.5:
            self._close(cond, t)
            cond.active = False
        return "elevated" if cond.active else "normal"

    def update(self, t: float, zone_values: dict[str, dict]) -> str:
        """zone_values[zone_id] = {"avg": float, "utilisation": float|None, "rise": float|None}."""
        overall = "normal"
        for zid, zone in self.zones.items():
            vals = zone_values.get(zid)
            if vals is None:
                continue
            statuses = []
            if zone.zone_type == QUEUE_ZONE:
                statuses.append(self._threshold_rule(
                    zone, QUEUE_THRESHOLD, t, vals.get("avg"),
                    _rule(zone, self.rules, "queue_threshold"), "", "Queue count"))
                statuses.append(self._growth_rule(zone, t, vals.get("rise")))
            else:
                thr = _rule(zone, self.rules, "occupancy_pct_threshold")
                statuses.append(self._threshold_rule(
                    zone, OCCUPANCY_THRESHOLD, t, vals.get("utilisation"),
                    float(thr) if thr is not None else None, "%", "Occupancy"))
            status = max(statuses, key=STATUS_ORDER.get)
            self.zone_status[zid] = status
            overall = max(overall, status, key=STATUS_ORDER.get)
        return overall

    def finalize(self, t_end: float) -> list[CongestionEvent]:
        for cond in self.state.values():
            if cond.active:
                self._close(cond, t_end, " Still active when the video ended.")
                cond.active = False
        return self.events
