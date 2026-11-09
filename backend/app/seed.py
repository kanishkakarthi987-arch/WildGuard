"""First-run demo data: 7 original sightings, synthetic history, sensors, subscribers."""

import random
from datetime import datetime, timedelta

from . import db, geo, service
from .config import (
    CAMERAS,
    FOREST_CENTER,
    MOVEMENTS,
    SEED_OFFLINE_SENSORS,
    SENSOR_INVENTORY,
    VILLAGES,
)

# Your original seed sightings. Offsets are minutes before the newest one.
ORIGINAL_SIGHTINGS = [
    # animal, lat, lon, location, confidence, camera, source, minutes_before_latest, movement
    ("Elephant", 12.6652, 80.1081, "Forest Edge - North", 0.96, "CAM-01", "Camera Trap", 0, "Toward Village"),
    ("Elephant", 12.6745, 80.1215, "Forest Edge - East", 0.91, "CAM-02", "Camera Trap", 27, "Parallel To Boundary"),
    ("Leopard", 12.6922, 80.0865, "Forest Trail", 0.88, "CAM-03", "Camera Trap", 44, "Toward Village"),
    ("Elephant", 12.6478, 80.0925, "Water Source", 0.94, "CAM-04", "GPS Collar", 81, "Toward Village"),
    ("Leopard", 12.6815, 80.0715, "Forest Trail - West", 0.82, "CAM-05", "Camera Trap", 116, "Away From Village"),
    ("Elephant", 12.6588, 80.1372, "Village Boundary", 0.97, "CAM-01", "Camera Trap", 150, "Toward Village"),
    ("Leopard", 12.7012, 80.1124, "Forest North", 0.86, "CAM-02", "GPS Collar", 184, "Parallel To Boundary"),
]

SUBSCRIBERS = {
    # Placeholder numbers (leading 0) can never reach a real phone.
    # (name, phone, language, voice call too)
    "Village A": [("Murugan", "0000000001", "ta", True), ("Lakshmi", "0000000002", "ta", False), ("Ravi", "0000000003", "en", False)],
    "Village B": [("Selvi", "0000000004", "ta", False), ("Karthik", "0000000005", "en", False)],
    "Village C": [("Anbu", "0000000006", "ta", True), ("Meena", "0000000007", "ta", False), ("John", "0000000008", "en", False)],
}


def _ground_position(index: int) -> tuple[float, float]:
    """Place ground sensors on the forest side of each village, in two staggered rings."""
    name = list(VILLAGES)[index % 3]
    village = VILLAGES[name]
    base = geo.bearing_deg(village["lat"], village["lon"], FOREST_CENTER["lat"], FOREST_CENTER["lon"])
    ring = index // 3
    return geo.offset_point(village["lat"], village["lon"], base + (ring - 1.5) * 35, 0.6 + ring * 0.25)


def seed_sensors(rng):
    now = db.now_str()
    ground_index = 0
    for sensor_id, sensor_type in SENSOR_INVENTORY:
        offline = sensor_id in SEED_OFFLINE_SENSORS
        lat = lon = None
        if sensor_id in CAMERAS:
            lat, lon = CAMERAS[sensor_id]["lat"], CAMERAS[sensor_id]["lon"]
        elif sensor_type in ("Acoustic Sensor", "Perimeter Sensor"):
            lat, lon = _ground_position(ground_index)
            ground_index += 1
        db.upsert_sensor(
            sensor_id,
            sensor_type,
            "OFFLINE" if offline else "ONLINE",
            0 if offline else rng.randint(62, 97),
            None if offline else now,
            lat=lat,
            lon=lon,
        )


def seed_subscribers():
    for village, people in SUBSCRIBERS.items():
        for name, phone, language, voice in people:
            db.add_subscriber(name, phone, village, language, voice)


def seed_events(rng):
    now = datetime.now()
    history = []

    def store(**kwargs):
        event, _ = service.build_event(rng=rng, history=history, historical=True, simulation=False, **kwargs)
        event["seed"] = True
        event["id"] = db.insert_event(event)
        history.append(event)

    # Older "normal behaviour" history so the anomaly model has something to learn from.
    for _ in range(40):
        animal = rng.choice(["Elephant", "Elephant", "Leopard"])
        ts = now - timedelta(days=rng.uniform(1, 5), minutes=rng.uniform(0, 600))
        store(
            animal=animal,
            camera_id=rng.choice(list(CAMERAS)),
            source="Camera Trap",
            movement=rng.choices(MOVEMENTS, weights=[0.35, 0.3, 0.35])[0],
            ts=ts,
        )
    history.sort(key=lambda e: e["timestamp"])

    # Your original seven sightings, shifted so the newest is five minutes old.
    latest = now - timedelta(minutes=5)
    for animal, lat, lon, loc, conf, cam, source, minutes_before, movement in reversed(ORIGINAL_SIGHTINGS):
        store(
            animal=animal,
            camera_id=cam,
            source=source,
            movement=movement,
            ts=latest - timedelta(minutes=minutes_before),
            position=(lat, lon),
            confidence=conf,
            location=loc,
        )


def ensure_seeded() -> None:
    db.init_db()
    rng = random.Random(42)
    sensors = db.list_sensors()
    if not sensors:
        seed_sensors(rng)
    elif any(s["kind"] is None for s in sensors):
        seed_sensors(rng)  # upgrade a v3 database: adds kinds and positions, keeps everything else
    if not db.list_subscribers():
        seed_subscribers()
    if db.count_events() == 0:
        seed_events(rng)
