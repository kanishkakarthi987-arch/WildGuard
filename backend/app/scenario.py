"""Scripted animal movements that drive the real ingest pipeline (demos and evaluation).

A scenario is a list of steps (GPS fix, ground-sensor reading, camera detection, incident).
The same plan can be applied in-process (dashboard button) or posted over HTTP
(tools/scenario.py), so both exercise the same ingestion code.

Kinds:
  approach  the animal walks to the village            -> a real incident, alerts should be correct
  veer      it heads in, then turns away at ~1.2 km    -> alerts here are false alarms
  loiter    it wanders in the forest 2 km out          -> should stay quiet
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timedelta
from math import cos, radians, sin, sqrt

from . import db, geo, ingest
from .config import FOREST_CENTER, TIME_FORMAT, VILLAGES

KINDS = ("approach", "veer", "loiter")
FIX_INTERVAL_MIN = 2
SPEED_KMH = {"Elephant": (1.8, 2.6), "Leopard": (2.5, 3.4)}
ARRIVAL_KM = 0.3

MIXED = [
    ("approach", "Elephant", "Village A"),
    ("veer", "Elephant", "Village B"),
    ("approach", "Leopard", "Village C"),
    ("loiter", "Elephant", "Village A"),
    ("approach", "Elephant", "Village B"),
    ("veer", "Leopard", "Village C"),
]

_state = {"running": False, "kind": None, "step": 0, "total": 0, "message": "idle"}
_lock = threading.Lock()


def device_lists(devices: list[dict]) -> dict:
    located = [d for d in devices if d.get("lat") is not None]
    return {
        "collar": next((d for d in devices if d["kind"] == "collar"), None),
        "cameras": [d for d in located if d["kind"] == "camera"],
        "ground": [d for d in located if d["kind"] == "ground"],
    }


def _bearing_xy(dx: float, dy: float) -> float:
    from math import atan2, degrees
    return degrees(atan2(dx, dy)) % 360


def plan_scenario(kind: str, species: str, village: str, devices: dict, rng: random.Random) -> list[dict]:
    """Return steps with relative `offset_min`. Positions are generated in local km around the village."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    v = VILLAGES[village]
    lat0, lon0 = v["lat"], v["lon"]
    animal_id = f"{species[0]}-{rng.randint(10, 99)}"
    speed = rng.uniform(*SPEED_KMH[species])
    start_dist = rng.uniform(2.0, 2.4) if kind != "loiter" else rng.uniform(2.3, 2.8)
    # animals come out of the forest, so approach from the forest side of the village
    bearing = (geo.bearing_deg(lat0, lon0, FOREST_CENTER["lat"], FOREST_CENTER["lon"]) + rng.uniform(-50, 50)) % 360
    x, y = start_dist * sin(radians(bearing)), start_dist * cos(radians(bearing))
    dt_h = FIX_INTERVAL_MIN / 60

    turn_dist = rng.uniform(1.1, 1.4)
    turned, turn_steps = False, 0
    heading = (bearing + 180) % 360
    fired_cameras = set()
    steps: list[dict] = []
    arrived = False

    for i in range(0, 80):
        offset = i * FIX_INTERVAL_MIN
        dist = sqrt(x * x + y * y)
        to_village = _bearing_xy(-x, -y)

        if kind == "approach":
            heading = (to_village + rng.gauss(0, 6)) % 360
        elif kind == "veer":
            if not turned and dist <= turn_dist:
                turned = True
                heading = (to_village + rng.choice([-1, 1]) * rng.uniform(100, 140)) % 360
            elif turned:
                heading = (heading + rng.gauss(0, 6)) % 360
                turn_steps += 1
            else:
                heading = (to_village + rng.gauss(0, 6)) % 360
        else:  # loiter: wander, but never come inside 2 km
            heading = (heading + rng.gauss(0, 35)) % 360
            if dist < 2.0:
                heading = (to_village + 180 + rng.gauss(0, 20)) % 360

        # true position -> noisy GPS fix
        lat, lon = geo.from_local_km(x, y, lat0, lon0)
        fix_lat, fix_lon = geo.offset_point(lat, lon, rng.uniform(0, 360), abs(rng.gauss(0, 0.015)))
        steps.append({
            "offset_min": offset, "type": "gps", "device_id": devices["collar"]["id"],
            "payload": {"animal_id": animal_id, "species": species, "lat": round(fix_lat, 6), "lon": round(fix_lon, 6)},
        })

        # ground sensors that feel it
        for sensor in devices["ground"]:
            d = geo.haversine_km(lat, lon, sensor["lat"], sensor["lon"])
            if species == "Elephant" and d < 0.9 and rng.random() < 0.7:
                steps.append({"offset_min": offset, "type": "sensor", "device_id": sensor["id"],
                              "payload": {"kind": "seismic", "value": round(max(0.0, 1.35 - d * 1.1 + rng.gauss(0, 0.1)), 2)}})
                steps.append({"offset_min": offset, "type": "sensor", "device_id": sensor["id"],
                              "payload": {"kind": "acoustic", "value": round(48 + (1.0 - d) * 30 + rng.gauss(0, 2), 1)}})
            elif species == "Leopard" and d < 0.25 and rng.random() < 0.8:
                steps.append({"offset_min": offset, "type": "sensor", "device_id": sensor["id"],
                              "payload": {"kind": "pir", "value": 1}})

        # cameras it walks past
        for camera in devices["cameras"]:
            d = geo.haversine_km(lat, lon, camera["lat"], camera["lon"])
            if d < 0.35 and camera["id"] not in fired_cameras:
                fired_cameras.add(camera["id"])
                steps.append({"offset_min": offset, "type": "detection", "device_id": camera["id"],
                              "payload": {"species": species, "confidence": round(rng.uniform(0.74, 0.97), 2)}})

        if kind == "approach" and dist <= ARRIVAL_KM:
            steps.append({"offset_min": offset, "type": "incident", "device_id": None,
                          "payload": {"village": village, "animal": species, "source": "scenario",
                                      "notes": f"{animal_id} reached {village} (scripted)"}})
            arrived = True
            break
        if kind == "veer" and turned and turn_steps >= 12:
            break
        if kind == "loiter" and i >= 24:
            break

        x += speed * dt_h * sin(radians(heading))
        y += speed * dt_h * cos(radians(heading))

    if kind == "approach" and not arrived:
        raise RuntimeError("scenario did not reach the village; increase the step limit")
    return steps


def schedule(plans: list[list[dict]], now: datetime, gap_min: int = 45) -> list[dict]:
    """Lay scenarios end to end so the last step lands on `now`; return one time-sorted step list."""
    durations = [max(s["offset_min"] for s in plan) for plan in plans]
    total = sum(durations) + gap_min * (len(plans) - 1)
    cursor = now.replace(microsecond=0) - timedelta(minutes=total)
    flat = []
    order = {"gps": 0, "sensor": 1, "detection": 2, "incident": 3}
    for plan, duration in zip(plans, durations):
        for step in plan:
            when = cursor + timedelta(minutes=step["offset_min"])
            flat.append({**step, "t": when, "payload": {**step["payload"], "timestamp": when.strftime(TIME_FORMAT)}})
        cursor += timedelta(minutes=duration + gap_min)
    flat.sort(key=lambda s: (s["t"], order[s["type"]]))
    return flat


def build_plan(devices: list[dict], scenarios: list[tuple], now: datetime, seed: int | None = None) -> list[dict]:
    rng = random.Random(seed)
    lists = device_lists(devices)
    if lists["collar"] is None:
        raise RuntimeError("no GPS collar device is registered")
    plans = [plan_scenario(k, sp, vil, lists, rng) for k, sp, vil in scenarios]
    return schedule(plans, now)


# --------------------------------------------------------------- applying


def apply_step(step: dict, devices_by_id: dict) -> None:
    payload = step["payload"]
    kind = step["type"]
    if kind == "incident":
        db.add_incident(payload["timestamp"], payload["village"], payload.get("animal"),
                        payload.get("source", "scenario"), payload.get("notes"))
        return
    device = devices_by_id[step["device_id"]]
    if kind == "gps":
        ingest.ingest_gps(device, [payload])
    elif kind == "sensor":
        ingest.ingest_sensor(device, [payload])
    elif kind == "detection":
        ingest.ingest_detection(
            device, species=payload["species"], confidence=payload["confidence"],
            ts=ingest.parse_ts(payload["timestamp"]),
        )


def status() -> dict:
    return dict(_state)


def _run(steps: list[dict], speed: float, label: str) -> None:
    devices_by_id = {d["id"]: d for d in db.list_sensors()}
    _state.update(running=True, kind=label, step=0, total=len(steps), message="running")
    previous = None
    try:
        for index, step in enumerate(steps, start=1):
            if previous is not None:
                gap_min = (step["t"] - previous).total_seconds() / 60
                if 0 < gap_min <= 5:  # long gaps between scenarios are skipped, not waited out
                    time.sleep(gap_min / speed)
            previous = step["t"]
            apply_step(step, devices_by_id)
            _state["step"] = index
        _state["message"] = "finished"
    except Exception as exc:  # surfaced through /api/demo/status
        _state["message"] = f"failed: {exc}"
    finally:
        _state["running"] = False


def start_background(scenarios: list[tuple], speed: float = 10.0, label: str = "demo") -> dict:
    with _lock:
        if _state["running"]:
            raise RuntimeError("a scenario is already running")
        steps = build_plan(db.list_sensors(), scenarios, datetime.now())
        _state.update(running=True, kind=label, step=0, total=len(steps), message="starting")
    threading.Thread(target=_run, args=(steps, speed, label), daemon=True).start()
    return status()
