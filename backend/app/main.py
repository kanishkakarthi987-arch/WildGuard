"""WildGuard API: routes only. Logic lives in the sibling modules."""

import asyncio
import hmac
import logging
import random
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from . import auth, bus, config, db, detector, evaluation, fusion, ingest, lora, predictor, riskzones, scenario, seed, service
from .auth import device_auth, require_admin
from .config import CAMERAS, FOREST_CENTER, SPECIES_PROFILES, THREAT_RADIUS_KM, VILLAGES
from .schemas import (
    DetectionIn,
    DeviceCreate,
    GpsBatch,
    IncidentCreate,
    LoraUplink,
    ScenarioRequest,
    SensorBatch,
    SimulationRequest,
    SubscriberCreate,
    VerifyRequest,
)

log = logging.getLogger("wildguard")

ALERT_LEVELS = ("HIGH", "CRITICAL")


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed.ensure_seeded()
    log.warning("Admin token source: %s (the dashboard asks for it before ranger actions)", config.ADMIN_TOKEN_SOURCE)
    yield


app = FastAPI(
    title="WildGuard API",
    description="Predictive early-warning for human-wildlife conflict",
    version="5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ingest.IngestError)
async def ingest_error_handler(_, exc: ingest.IngestError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(detector.DetectorUnavailable)
async def detector_unavailable_handler(_, exc: detector.DetectorUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _public(event: dict) -> dict:
    """Event as sent to the dashboard (the heavy GPS track stays server-side except for the map)."""
    return event


@app.get("/")
def root():
    return {"message": "WildGuard API is running", "status": "online", "version": app.version}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "events": db.count_events(),
        "notify_provider": config.NOTIFY_PROVIDER,
        "voice_provider": config.VOICE_PROVIDER,
        "detector_installed": detector.is_installed(),
        "lora_enabled": bool(config.GATEWAY_KEY),
    }


@app.get("/api/auth/check", dependencies=[Depends(require_admin)])
def auth_check():
    """The dashboard calls this to validate a ranger token before saving it."""
    return {"ok": True}


@app.get("/api/stream")
async def stream(request: Request):
    """Server-sent events: one message each time anything is written, so the dashboard updates live."""

    async def events():
        last = bus.version()
        yield "retry: 3000\n\n"
        quiet = 0
        while not await request.is_disconnected():
            await asyncio.sleep(0.5)
            current = bus.version()
            if current != last:
                last, quiet = current, 0
                yield f"data: {current}\n\n"
            else:
                quiet += 1
                if quiet >= 30:  # keep proxies from closing an idle connection
                    quiet = 0
                    yield ": keepalive\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/config")
def get_config():
    """Geography for the map, so the frontend hardcodes nothing."""
    return {
        "villages": [
            {
                "name": n, "lat": v["lat"], "lon": v["lon"], "threat_radius_km": THREAT_RADIUS_KM,
                "threat_radius_by_species": {k: p["threat_radius_km"] for k, p in SPECIES_PROFILES.items() if k != "Unknown"},
            }
            for n, v in VILLAGES.items()
        ],
        "cameras": [{"id": n, "lat": c["lat"], "lon": c["lon"]} for n, c in CAMERAS.items()],
        "forest": FOREST_CENTER,
        # Timestamps are naive server-local strings. This lets a browser in another time zone
        # (or a server hosted in UTC) still show correct "5 min ago" values.
        "utc_offset_minutes": int(datetime.now().astimezone().utcoffset().total_seconds() // 60),
    }


@app.get("/api/sightings")
def get_sightings(limit: int = 200):
    return [_public(e) for e in db.list_events(limit=max(1, min(limit, 1000)))]


@app.get("/api/statistics")
def get_statistics():
    events = db.list_events()
    sensors = db.list_sensors()
    return {
        "total_sightings": len(events),
        "elephants": sum(1 for e in events if e["animal"] == "Elephant"),
        "leopards": sum(1 for e in events if e["animal"] == "Leopard"),
        "high_risk_events": sum(1 for e in events if e.get("risk") in ALERT_LEVELS),
        "anomalies": sum(1 for e in events if e.get("anomaly")),
        "pending_verification": sum(1 for e in events if e.get("verification") == "pending"),
        "alerts_sent": db.count_notifications(),
        "active_sensors": sum(1 for s in sensors if s["status"] == "ONLINE"),
    }


@app.get("/api/alerts")
def get_alerts(limit: int = 20):
    events = sorted(db.list_events(limit=300), key=lambda e: e["timestamp"])
    alerts = [
        {
            "id": e["id"],
            "animal": e["animal"],
            "risk": e["risk"],
            "risk_score": e["risk_score"],
            "location": e["location"],
            "distance_km": e["distance_km"],
            "direction": e["direction"],
            "timestamp": e["timestamp"],
            "alert_tier": e.get("alert_tier"),
            "verification": e.get("verification"),
            "eta_minutes": e.get("eta_minutes"),
            "target_village": e.get("target_village"),
            "nearest_village": e.get("nearest_village"),
            "anomaly": e.get("anomaly"),
            "confidence": e.get("confidence"),
            "image": e.get("image"),
            "source": e.get("source"),
        }
        for e in events
        if e.get("risk") in ALERT_LEVELS or e.get("alert_tier")
    ]
    return alerts[-limit:][::-1]


@app.get("/api/predict")
def predict(limit: int = 6):
    predictions = []
    for e in db.list_events(limit=max(1, min(limit, 30)))[::-1]:
        p = predictor.predict_event(e)
        predictions.append({
            "event_id": e["id"],
            "animal": e["animal"],
            "timestamp": e["timestamp"],
            "current_lat": p["lat"],
            "current_lon": p["lon"],
            "direction": p["direction"] or "Stationary",
            "speed_kmh": p["speed_kmh"],
            "speed_sigma_kmh": p["speed_sigma_kmh"],
            "path": p["path"],
            "will_reach": p["will_reach"],
            "predicted_zone": p["target_village"],
            "eta_minutes": p["eta_minutes"],
            "closest_approach_km": p["closest_approach_km"],
            "alert_tier": e.get("alert_tier"),
            "risk": e.get("risk", "LOW"),
            "risk_score": e.get("risk_score", 0),
            "anomaly": e.get("anomaly"),
        })
    return predictions


@app.get("/api/sensors")
def get_sensors():
    sensors = db.list_sensors()
    online = sum(1 for s in sensors if s["status"] == "ONLINE")
    return {
        "network_status": "ONLINE" if online else "OFFLINE",
        "total": len(sensors),
        "online": online,
        "offline": len(sensors) - online,
        "sensors": sensors,
    }


@app.post("/api/simulate", dependencies=[Depends(require_admin)])
def simulate_detection(request: SimulationRequest):
    event, _, notification = service.create_simulated_event(
        animal=request.animal,
        camera_id=request.camera_id,
        source=request.source,
        movement=request.movement,
    )
    return {"message": "Detection simulated successfully", "event": event, "notification": notification}


@app.post("/api/simulate-emergency", dependencies=[Depends(require_admin)])
def simulate_emergency():
    event, _, notification = service.create_simulated_event(
        animal=random.choice(["Elephant", "Leopard"]),
        camera_id=random.choice(list(CAMERAS)),
        source="Emergency Simulation",
        movement="Toward Village",
        emergency=True,
    )
    return {
        "emergency": True,
        "message": "Emergency wildlife event simulated",
        "event": event,
        "notification": notification,
    }


@app.post("/api/events/{event_id}/verify", dependencies=[Depends(require_admin)])
def verify_event(event_id: int, request: VerifyRequest):
    event, notification, problem = service.verify_event(event_id, request.action)
    if problem == "not_found":
        raise HTTPException(status_code=404, detail="Event not found")
    if problem == "not_pending":
        raise HTTPException(status_code=409, detail="Event is not awaiting verification")
    return {"event": event, "notification": notification}


@app.get("/api/notifications")
def get_notifications(limit: int = 30):
    return db.list_notifications(limit=max(1, min(limit, 200)))


@app.get("/api/subscribers", dependencies=[Depends(require_admin)])
def get_subscribers():
    # Phone numbers are masked in API output.
    return [
        {**s, "phone": "******" + s["phone"][-4:]}
        for s in db.list_subscribers()
    ]


@app.post("/api/subscribers", status_code=201, dependencies=[Depends(require_admin)])
def add_subscriber(body: SubscriberCreate):
    created = db.add_subscriber(body.name, body.phone, body.village, body.language, body.voice)
    return {**created, "phone": "******" + created["phone"][-4:]}


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


@app.get("/api/devices")
def list_devices():
    return db.list_sensors()


@app.post("/api/devices", status_code=201, dependencies=[Depends(require_admin)])
def provision_device(body: DeviceCreate):
    """Register a device (or issue it a new key). The API key is shown once and never stored."""
    existing = db.get_device(body.id)
    if existing and existing["has_key"] and not body.rotate:
        raise HTTPException(status_code=409, detail="Device already has a key. Send rotate=true to replace it.")
    db.upsert_sensor(
        body.id, body.type, existing["status"] if existing else "OFFLINE",
        existing["battery"] if existing else 100, existing["last_seen"] if existing else None,
        kind=body.kind, lat=body.lat, lon=body.lon, lora_id=body.lora_id,
    )
    key = auth.generate_key()
    db.set_device_key(body.id, auth.hash_key(key))
    return {"device": db.get_device(body.id), "api_key": key}


# ---------------------------------------------------------------------------
# Ingestion (authenticated per device)
# ---------------------------------------------------------------------------


@app.post("/api/ingest/detection")
def ingest_detection(body: DetectionIn, device: dict = Depends(device_auth("camera"))):
    """Edge-inference path: the camera ran the model locally and sends only the detection."""
    result = ingest.ingest_detection(
        device, species=body.species, confidence=body.confidence, ts=ingest.parse_ts(body.timestamp),
        lat=body.lat, lon=body.lon, count=body.count,
    )
    return result


@app.post("/api/ingest/camera")
async def ingest_camera(
    file: UploadFile = File(...),
    timestamp: str | None = Form(None),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    species: str | None = Form(None),
    confidence: float | None = Form(None),
    device: dict = Depends(device_auth("camera")),
):
    """Upload a camera-trap image. The server runs YOLO, or use `species` for a manual label."""
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"Image larger than {config.MAX_UPLOAD_MB} MB")
    return await run_in_threadpool(
        ingest.process_image, device, data,
        ts=ingest.parse_ts(timestamp), lat=lat, lon=lon, manual_species=species, manual_confidence=confidence,
    )


@app.post("/api/ingest/gps")
def ingest_gps(body: GpsBatch, device: dict = Depends(device_auth("collar"))):
    return ingest.ingest_gps(device, [fix.model_dump() for fix in body.fixes])


@app.post("/api/ingest/sensor")
def ingest_sensor(body: SensorBatch, device: dict = Depends(device_auth("ground"))):
    return ingest.ingest_sensor(device, [r.model_dump(exclude_none=True) for r in body.readings])


@app.post("/api/ingest/lora")
def ingest_lora(body: LoraUplink, x_gateway_key: str = Header(default="")):
    """Uplinks forwarded by a LoRaWAN network server. Frames are decoded by app/lora.py."""
    if not config.GATEWAY_KEY:
        raise HTTPException(status_code=503, detail="LoRa ingestion is off: set WILDGUARD_GATEWAY_KEY")
    if not hmac.compare_digest(x_gateway_key.encode(), config.GATEWAY_KEY.encode()):
        raise HTTPException(status_code=401, detail="Invalid gateway key (X-Gateway-Key header)")
    results = lora.process(body.frames)
    return {"accepted": sum(r["ok"] for r in results), "rejected": sum(not r["ok"] for r in results), "results": results}


@app.get("/api/ingest/feed")
def ingest_feed(limit: int = 40):
    return db.list_log(limit=max(1, min(limit, 200)))


@app.get("/api/media/{name}")
def get_media(name: str):
    if not re.fullmatch(r"[a-f0-9]{32}\.(jpg|png|webp)", name):
        raise HTTPException(status_code=404, detail="Not found")
    path = Path(config.UPLOAD_DIR) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/detector")
def detector_info():
    return detector.info()


# ---------------------------------------------------------------------------
# Live map data, risk zones
# ---------------------------------------------------------------------------


@app.get("/api/tracks")
def get_tracks(minutes: int = 180):
    return db.recent_tracks(max(5, min(minutes, 1440)), datetime.now())


@app.get("/api/ground-readings")
def get_ground_readings(minutes: int = 60):
    now = datetime.now()
    rows = db.recent_readings(now, max(1, min(minutes, 1440)))
    return [{**r, "level": fusion.LEVELS[fusion.reading_level(r["kind"], r["value"])]} for r in rows[-200:]]


@app.get("/api/risk-zones")
def get_risk_zones():
    return riskzones.build_zones()


# ---------------------------------------------------------------------------
# Ground truth and evaluation
# ---------------------------------------------------------------------------


@app.post("/api/incidents", status_code=201, dependencies=[Depends(require_admin)])
def log_incident(body: IncidentCreate):
    ts = ingest.parse_ts(body.timestamp)
    return db.add_incident(db.fmt(ts), body.village, body.animal, "ranger", body.notes)


@app.get("/api/incidents")
def get_incidents():
    return db.list_incidents()[::-1]


@app.get("/api/evaluation")
def get_evaluation(window_min: int = config.EVAL_WINDOW_MIN):
    return evaluation.evaluate(max(10, min(window_min, 1440)))


# ---------------------------------------------------------------------------
# Demo scenarios (drive the real ingest pipeline)
# ---------------------------------------------------------------------------


@app.post("/api/demo/scenario", status_code=202, dependencies=[Depends(require_admin)])
def run_demo_scenario(body: ScenarioRequest):
    scenarios = scenario.MIXED if body.mode == "mixed" else [(body.mode, body.species, body.village)]
    try:
        return scenario.start_background(scenarios, speed=body.speed, label=body.mode)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.get("/api/demo/status")
def demo_status():
    return scenario.status()
