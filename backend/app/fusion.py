"""Ground-sensor fusion: turn raw readings near a detection into a corroboration level."""

from __future__ import annotations

from datetime import datetime

from . import config, db, geo

LEVELS = ["LOW", "MEDIUM", "HIGH"]


def reading_level(kind: str, value: float) -> int:
    """0 = below threshold, 1 = medium, 2 = high."""
    spec = config.SENSOR_KINDS.get(kind)
    if spec is None:
        return 0
    if value >= spec["high"]:
        return 2
    if value >= spec["medium"]:
        return 1
    return 0


def sensor_context(lat: float, lon: float, ts: datetime) -> dict:
    """Summarise ground readings within FUSION_RADIUS_KM / FUSION_WINDOW_MIN of a point."""
    nearby = []
    for r in db.recent_readings(ts, config.FUSION_WINDOW_MIN):
        if r["lat"] is None or r["lon"] is None:
            continue
        if geo.haversine_km(lat, lon, r["lat"], r["lon"]) <= config.FUSION_RADIUS_KM:
            level = reading_level(r["kind"], r["value"])
            if level:
                nearby.append({**r, "level": level})
    top = max((r["level"] for r in nearby), default=0)
    strongest = max(nearby, key=lambda r: (r["level"], r["value"]), default=None)
    return {
        "activity": LEVELS[top],
        "count": len(nearby),
        "strongest": None
        if strongest is None
        else f"{strongest['kind']} {strongest['value']:g} at {strongest['device_id']}",
    }


def is_night(ts: datetime) -> bool:
    return ts.hour >= config.NIGHT_START_H or ts.hour < config.NIGHT_END_H
