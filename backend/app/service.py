"""Simulated detections and ranger verification.

Builds a synthetic GPS track for the Simulation Lab and the first-run seed data, then hands it
to pipeline.assemble_event (the same analysis real cameras, collars and sensors get).
create_simulated_event stores the result and sends the alert when it needs no ranger;
verify_event is the ranger's confirm / reject step for low-confidence detections.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from . import db, geo
from .pipeline import alert_for, assemble_event
from .config import CAMERAS, CONFIRM_THRESHOLD, TIME_FORMAT, VILLAGES
from .sensors import generate_sensors, sensor_activity

TRACK_STEPS = 6
TRACK_INTERVAL_MIN = 10
SPEED_RANGE = {"Elephant": (1.5, 3.0), "Leopard": (2.0, 4.0)}


def _fmt(ts: datetime) -> str:
    return ts.strftime(TIME_FORMAT)


def _pick_heading(movement, bearing_to_village, rng, toward_sigma=12.0):
    if movement == "Toward Village":
        # toward_sigma is the aiming error in degrees; 0 means walking straight at the village.
        return (bearing_to_village + (rng.gauss(0, toward_sigma) if toward_sigma else 0.0)) % 360
    if movement == "Away From Village":
        return (bearing_to_village + 180 + rng.gauss(0, 15)) % 360
    side = rng.choice([90, -90])
    return (bearing_to_village + side + rng.gauss(0, 12)) % 360


def _make_track(lat, lon, heading, speed, ts, rng, erratic):
    """Walk backwards from the current position to build a noisy GPS track."""
    sigma_heading = 55 if erratic else 5
    points = [(lat, lon)]
    cur_lat, cur_lon = lat, lon
    for _ in range(TRACK_STEPS - 1):
        step_heading = (heading + rng.gauss(0, sigma_heading)) % 360
        step_km = speed * (TRACK_INTERVAL_MIN / 60) * max(0.3, 1 + rng.gauss(0, 0.1))
        cur_lat, cur_lon = geo.offset_point(cur_lat, cur_lon, (step_heading + 180) % 360, step_km)
        points.append((cur_lat, cur_lon))
    points.reverse()

    track = []
    for i, (p_lat, p_lon) in enumerate(points):
        age_min = (TRACK_STEPS - 1 - i) * TRACK_INTERVAL_MIN
        # ~15 m GPS noise
        n_lat, n_lon = geo.offset_point(p_lat, p_lon, rng.uniform(0, 360), abs(rng.gauss(0, 0.015)))
        track.append({
            "t": _fmt(ts - timedelta(minutes=age_min)),
            "lat": round(n_lat, 6),
            "lon": round(n_lon, 6),
        })
    return track


def build_event(
    *,
    animal: str,
    camera_id: str,
    source: str,
    movement: str,
    ts: datetime,
    rng: random.Random,
    history: list[dict],
    position: tuple[float, float] | None = None,
    confidence: float | None = None,
    erratic: bool = False,
    location: str = "Simulated Forest Zone",
    historical: bool = False,
    simulation: bool = True,
    toward_sigma: float = 12.0,
):
    """Build a fully analysed event (not yet stored). Returns (event, prediction)."""
    camera = CAMERAS.get(camera_id, CAMERAS["CAM-01"])
    if position is None:
        position = (
            camera["lat"] + rng.uniform(-0.006, 0.006),
            camera["lon"] + rng.uniform(-0.006, 0.006),
        )
    lat, lon = position
    confidence = round(confidence if confidence is not None else rng.uniform(0.82, 0.98), 2)

    near = geo.nearest_village(lat, lon)
    village = VILLAGES[near["name"]]
    to_village = geo.bearing_deg(lat, lon, village["lat"], village["lon"])
    heading = _pick_heading(movement, to_village, rng, toward_sigma)
    low, high = SPEED_RANGE[animal]
    speed = rng.uniform(low, high) * (2.2 if erratic else 1.0)

    track = _make_track(lat, lon, heading, speed, ts, rng, erratic)
    sensors = generate_sensors(animal, rng, now_str=_fmt(ts))

    return assemble_event(
        species=animal,
        track=track,
        confidence=confidence,
        device_id=camera_id,
        source=source,
        ts=ts,
        sensor_activity=sensor_activity(animal, sensors),
        sensor_data=sensors,
        history=history,
        location=location,
        historical=historical,
        simulation=simulation,
    )


def create_simulated_event(*, animal, camera_id, source, movement, emergency=False):
    """Create, store, and (if warranted) alert on a simulated detection."""
    rng = random.Random()
    ts = datetime.now()
    history = db.list_events()

    position = None
    confidence = None
    erratic = False
    if emergency:
        # Spawn 0.8-1.5 km out from a random village, heading in: forces a real alert path.
        name = rng.choice(list(VILLAGES))
        village = VILLAGES[name]
        position = geo.offset_point(village["lat"], village["lon"], rng.uniform(0, 360), rng.uniform(0.8, 1.5))
        confidence = rng.uniform(CONFIRM_THRESHOLD + 0.05, 0.98)
    else:
        erratic = rng.random() < 0.1  # ~1 in 10 detections shows panicked, erratic movement

    event, prediction = build_event(
        animal=animal,
        camera_id=camera_id,
        source=source,
        movement=movement,
        ts=ts,
        rng=rng,
        history=history,
        position=position,
        confidence=confidence,
        erratic=erratic,
        # An emergency walks straight at the village so it always reaches it.
        toward_sigma=0.0 if emergency else 12.0,
    )
    event_id = db.insert_event(event)
    event["id"] = event_id
    db.heartbeat(camera_id, event["sensor_data"]["battery"], event["timestamp"])

    notification = None
    if event["verification"] == "auto":
        notification = alert_for(event_id, event)
    return event, prediction, notification


def verify_event(event_id: int, action: str):
    """Ranger confirms (sends the alert) or rejects (drops it) a low-confidence detection."""
    event = db.get_event(event_id)
    if event is None:
        return None, None, "not_found"
    if event.get("verification") != "pending":
        return event, None, "not_pending"
    if action == "reject":
        return db.update_event(event_id, {"verification": "rejected"}), None, None
    event = db.update_event(event_id, {"verification": "confirmed"})
    return event, alert_for(event_id, event), None
