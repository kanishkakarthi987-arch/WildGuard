"""Live ingestion: camera detections and images, GPS collar fixes, ground-sensor readings.

Each handler validates input, stores the raw data, then runs the shared analysis in pipeline.py
and sends an alert when one is warranted.
"""

from __future__ import annotations

import io
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import config, db, detector, fusion, geo
from .config import SENSOR_KINDS
from .pipeline import alert_for, assemble_event, profile_for

WILDLIFE = ("Elephant", "Leopard")
IMAGE_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
COLLAR_CONFIDENCE = 0.99


class IngestError(ValueError):
    """Bad input from a device. Maps to HTTP 422."""


# ---------------------------------------------------------------- validation


def parse_ts(value) -> datetime:
    if value is None or value == "":
        return datetime.now().replace(microsecond=0)
    if isinstance(value, datetime):
        ts = value
    else:
        try:
            ts = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise IngestError(f"bad timestamp {value!r}; use YYYY-MM-DD HH:MM:SS") from None
    if ts.tzinfo is not None:
        ts = ts.astimezone().replace(tzinfo=None)
    ts = ts.replace(microsecond=0)
    if ts > datetime.now() + timedelta(minutes=config.FUTURE_TOLERANCE_MIN):
        raise IngestError("timestamp is in the future")
    return ts


def check_coords(lat, lon) -> tuple[float, float]:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise IngestError("lat/lon must be numbers") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise IngestError("lat/lon out of range")
    return lat, lon


def check_species(species) -> str:
    if species not in WILDLIFE:
        raise IngestError(f"species must be one of {list(WILDLIFE)}")
    return species


def _summary_for(event: dict) -> str:
    tail = (
        f"{event['alert_tier']} for {event['target_village']}"
        if event.get("alert_tier")
        else "no village threatened"
    )
    return f"{event['animal']} {event['confidence']:.0%} · risk {event['risk']} · {tail}"


# ------------------------------------------------------------------- cameras


def _link_camera_track(species: str, lat: float, lon: float, ts: datetime) -> str:
    """Attach a sighting to a recent plausible track of the same species, else start a new one.

    Plausible = reachable at the species' maximum walking speed since the last point.
    """
    profile = profile_for(species)
    best = None
    seen = set()
    for event in db.list_events_since(ts - timedelta(minutes=config.LINK_WINDOW_MIN)):
        track_id = event.get("track_id")
        if not track_id or track_id in seen or track_id.startswith(("collar:", "gnd-")):
            continue
        seen.add(track_id)
        if event["animal"] != species:
            continue
        points = db.get_points(track_id, ts, config.LINK_WINDOW_MIN, 1)
        if not points:
            continue
        last = points[-1]
        dt_h = (ts - datetime.strptime(last["t"], config.TIME_FORMAT)).total_seconds() / 3600
        if dt_h < 0:
            continue
        distance = geo.haversine_km(lat, lon, last["lat"], last["lon"])
        if distance <= profile["link_max_kmh"] * dt_h + 0.3 and (best is None or distance < best[0]):
            best = (distance, track_id)
    return best[1] if best else f"cam-{uuid.uuid4().hex[:8]}"


def ingest_detection(device, *, species, confidence, ts, lat=None, lon=None, image=None, count=1) -> dict:
    """One detection from a camera (usually from an edge device that ran the model itself)."""
    check_species(species)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise IngestError("confidence must be a number") from None
    if not 0 <= confidence <= 1:
        raise IngestError("confidence must be between 0 and 1")
    lat = device["lat"] if lat is None else lat
    lon = device["lon"] if lon is None else lon
    if lat is None or lon is None:
        raise IngestError("this device has no fixed location; send lat and lon")
    lat, lon = check_coords(lat, lon)

    # Retries from an offline edge buffer must not create duplicate events.
    for existing in db.list_events_since(ts):
        if (
            existing["timestamp"] == db.fmt(ts)
            and existing.get("camera_id") == device["id"]
            and existing["animal"] == species
        ):
            return {"event": existing, "notification": None, "duplicate": True}

    source = "Camera Trap"
    track_id = _link_camera_track(species, lat, lon, ts)
    db.add_points(track_id, species, source, [(db.fmt(ts), lat, lon)])
    track = db.get_points(track_id, ts, config.LINK_WINDOW_MIN, config.TRACK_POINTS_MAX)
    context = fusion.sensor_context(lat, lon, ts)

    event, _ = assemble_event(
        species=species,
        track=track,
        confidence=confidence,
        device_id=device["id"],
        source=source,
        ts=ts,
        sensor_activity=context["activity"],
        sensor_data={"fused_readings": context["count"], "strongest": context["strongest"]},
        history=db.list_events(limit=800),
        location=f"Camera {device['id']}",
        simulation=False,
        track_id=track_id,
        extra={"image": image, "count": count},
    )
    event_id = db.insert_event(event)
    event["id"] = event_id
    db.touch_device(device["id"], db.now_str())
    notification = alert_for(event_id, event, when=ts) if event["verification"] == "auto" else None
    db.add_log(device["id"], "camera", "accepted", _summary_for(event), ts=db.fmt(ts))
    return {"event": event, "notification": notification, "duplicate": False}


def process_image(device, data: bytes, *, ts, lat=None, lon=None, manual_species=None, manual_confidence=None):
    """Validate an uploaded image, detect wildlife in it, and ingest each species found."""
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
        image_format = image.format
        image.verify()
    except Exception:
        raise IngestError("file is not a valid image") from None
    extension = IMAGE_EXTENSIONS.get(image_format)
    if extension is None:
        raise IngestError("only JPEG, PNG or WebP images are accepted")

    if manual_species:
        check_species(manual_species)
        confidence = 0.95 if manual_confidence is None else manual_confidence
        detections = [{"species": manual_species, "confidence": confidence, "label": "manual"}]
    else:
        detections = detector.detect(data)  # raises DetectorUnavailable when YOLO is not installed

    if not detections:
        db.add_log(device["id"], "camera", "no_wildlife", "image received, no elephant or leopard found")
        return {"image": None, "detections": [], "results": []}

    name = f"{uuid.uuid4().hex}.{extension}"
    upload_dir = Path(config.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / name).write_bytes(data)

    by_species = defaultdict(list)
    for d in detections:
        by_species[d["species"]].append(d)
    results = []
    for species, found in by_species.items():
        best = max(found, key=lambda d: d["confidence"])
        results.append(
            ingest_detection(
                device, species=species, confidence=best["confidence"], ts=ts,
                lat=lat, lon=lon, image=name, count=len(found),
            )
        )
    return {"image": name, "detections": detections, "results": results}


# -------------------------------------------------------------- GPS collars


def ingest_gps(device, fixes: list[dict]) -> dict:
    """Batch of collar fixes (collars buffer fixes and upload them over LoRa/GSM in bursts)."""
    grouped = defaultdict(list)
    for fix in fixes:
        species = check_species(fix.get("species"))
        animal_id = str(fix.get("animal_id") or "").strip()
        if not animal_id:
            raise IngestError("animal_id is required")
        lat, lon = check_coords(fix.get("lat"), fix.get("lon"))
        grouped[(animal_id, species)].append((parse_ts(fix.get("timestamp")), lat, lon))

    results = []
    for (animal_id, species), points in grouped.items():
        points.sort()
        track_id = f"collar:{animal_id}"
        db.add_points(track_id, species, "GPS Collar", [(db.fmt(t), la, lo) for t, la, lo in points])
        last_ts = points[-1][0]
        track = db.get_points(track_id, last_ts, config.LINK_WINDOW_MIN, config.TRACK_POINTS_MAX)
        context = fusion.sensor_context(track[-1]["lat"], track[-1]["lon"], last_ts)

        event, _ = assemble_event(
            species=species,
            track=track,
            confidence=COLLAR_CONFIDENCE,
            device_id=device["id"],
            source="GPS Collar",
            ts=last_ts,
            sensor_activity=context["activity"],
            sensor_data={"fused_readings": context["count"], "strongest": context["strongest"]},
            history=db.list_events(limit=800),
            location=f"GPS collar {animal_id}",
            simulation=False,
            track_id=track_id,
            extra={"animal_id": animal_id},
        )
        # One live event per collared animal, updated as fixes arrive (not one per fix).
        existing = db.find_live_event(track_id, last_ts, config.LIVE_EVENT_WINDOW_MIN)
        if existing:
            if existing.get("verification") in ("confirmed", "rejected"):
                event["verification"] = existing["verification"]
            db.update_event(existing["id"], event)
            event_id = existing["id"]
        else:
            event_id = db.insert_event(event)
        event["id"] = event_id

        notification = None
        if event["verification"] in ("auto", "confirmed"):
            notification = alert_for(event_id, event, when=last_ts)
        results.append({"animal_id": animal_id, "event": event, "notification": notification})
        db.add_log(device["id"], "collar", "accepted",
                   f"{animal_id}: {len(points)} fix(es) · {_summary_for(event)}", ts=db.fmt(last_ts))

    db.touch_device(device["id"], db.now_str())
    return {"accepted": len(fixes), "results": results}


# ------------------------------------------------------------ ground sensors


def _sensor_trigger_needed(device, ts: datetime, lat: float, lon: float) -> bool:
    """A strong ground reading only raises its own event if nothing else explains it."""
    for event in db.list_events_since(ts - timedelta(minutes=config.SENSOR_CORROBORATION_MIN)):
        if event.get("source") == "Ground Sensor":
            if event.get("camera_id") == device["id"]:
                return False  # this sensor already raised one recently
            continue
        if (
            event["timestamp"] <= db.fmt(ts)
            and geo.haversine_km(lat, lon, event["lat"], event["lon"]) <= config.SENSOR_CORROBORATION_KM
        ):
            return False  # a camera or collar already accounts for it
    return True


def ingest_sensor(device, readings: list[dict]) -> dict:
    triggers = []
    latest = None
    parsed = []
    for reading in readings:
        kind = reading.get("kind")
        if kind not in SENSOR_KINDS:
            raise IngestError(f"kind must be one of {sorted(SENSOR_KINDS)}")
        try:
            value = float(reading.get("value"))
        except (TypeError, ValueError):
            raise IngestError("value must be a number") from None
        lat = reading.get("lat", device["lat"])
        lon = reading.get("lon", device["lon"])
        if lat is None or lon is None:
            raise IngestError("this sensor has no fixed location; send lat and lon")
        lat, lon = check_coords(lat, lon)
        parsed.append((parse_ts(reading.get("timestamp")), kind, value, lat, lon))

    for ts, kind, value, lat, lon in sorted(parsed):
        db.add_reading(db.fmt(ts), device["id"], kind, value, lat, lon)
        latest = ts
        if fusion.reading_level(kind, value) == 2 and _sensor_trigger_needed(device, ts, lat, lon):
            triggers.append(_raise_sensor_event(device, ts, kind, value, lat, lon))

    db.touch_device(device["id"], db.now_str())
    db.add_log(device["id"], "ground", "accepted",
               f"{len(parsed)} reading(s)" + (f" · {len(triggers)} unverified trigger(s)" if triggers else ""),
               ts=db.fmt(latest) if latest else None)
    return {"accepted": len(parsed), "triggers": triggers}


def _raise_sensor_event(device, ts, kind, value, lat, lon) -> dict:
    unit = SENSOR_KINDS[kind]["unit"]
    event, _ = assemble_event(
        species="Unknown",
        track=[{"t": db.fmt(ts), "lat": lat, "lon": lon}],
        confidence=config.SENSOR_ONLY_CONFIDENCE,
        device_id=device["id"],
        source="Ground Sensor",
        ts=ts,
        sensor_activity="HIGH",
        sensor_data={"kind": kind, "value": value, "unit": unit},
        history=db.list_events(limit=800),
        location=f"{kind} trigger at {device['id']}",
        simulation=False,
        track_id=f"gnd-{uuid.uuid4().hex[:8]}",
    )
    event["id"] = db.insert_event(event)
    # Confidence is below the threshold, so any alert waits for a ranger. Nothing is sent here.
    db.add_log(device["id"], "ground", "trigger",
               f"{kind} {value:g} {unit} with no camera or collar match · {_summary_for(event)}",
               ts=db.fmt(ts))
    return event
