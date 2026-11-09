"""WildGuard configuration: environment variables, demo geography and tuning constants.

Everything other modules need to know about the deployment lives here. Secrets and
switches come from environment variables (or backend/.env); thresholds are plain constants
you tune against real incident records.
"""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # the backend/ folder


def _load_env_file() -> None:
    """Tiny .env loader (KEY=VALUE lines). Real environment variables always win."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

# ---------------------------------------------------------------------------
# STORAGE AND NETWORK
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("WILDGUARD_DB", str(BASE_DIR / "data" / "wildguard.db"))

# Frontend origins allowed to call the API (CORS).
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

# ---------------------------------------------------------------------------
# ALERT CHANNELS
# ---------------------------------------------------------------------------

# "dry_run" records the alert that would be sent without contacting anyone.
# Real sending needs the matching keys below.
NOTIFY_PROVIDER = os.environ.get("NOTIFY_PROVIDER", "dry_run")  # dry_run | fast2sms
VOICE_PROVIDER = os.environ.get("VOICE_PROVIDER", "dry_run")  # dry_run | twilio
FAST2SMS_API_KEY = os.environ.get("FAST2SMS_API_KEY", "")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.environ.get("TWILIO_FROM", "")

# Optional webhook that drives a siren or LED beacon at the village (receives a JSON POST).
BEACON_WEBHOOK_URL = os.environ.get("BEACON_WEBHOOK_URL", "")

# Voice calls go out only for these alert tiers (to subscribers who opted in).
VOICE_TIERS = ("Warning", "Imminent")

# ---------------------------------------------------------------------------
# ACCESS CONTROL
# ---------------------------------------------------------------------------

# Shared secret your LoRaWAN network server sends in the X-Gateway-Key header.
# Empty means POST /api/ingest/lora is switched off.
GATEWAY_KEY = os.environ.get("WILDGUARD_GATEWAY_KEY", "")


def _resolve_admin_token() -> tuple[str, str]:
    """Return (token, where it came from).

    Set WILDGUARD_ADMIN_TOKEN yourself, or let the first start create a random one and keep
    it in data/admin_token.txt. There is no built-in default password.
    """
    token = os.environ.get("WILDGUARD_ADMIN_TOKEN", "").strip()
    if token:
        return token, "environment"
    path = Path(DB_PATH).parent / "admin_token.txt"
    try:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip(), str(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(18)
        path.write_text(token + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # Windows: chmod is a no-op, the file is still created
        return token, str(path)
    except OSError:
        return secrets.token_urlsafe(18), "memory (changes every restart)"


# Ranger/admin token for the dashboard (simulate, verify alerts, register devices, log incidents).
ADMIN_TOKEN, ADMIN_TOKEN_SOURCE = _resolve_admin_token()

# ---------------------------------------------------------------------------
# CAMERA UPLOADS AND DETECTION
# ---------------------------------------------------------------------------

UPLOAD_DIR = os.environ.get("WILDGUARD_UPLOADS", str(BASE_DIR / "data" / "uploads"))
MAX_UPLOAD_MB = 8  # larger camera images are rejected with HTTP 413

# Server-side detector (needs requirements-ml.txt). The default COCO weights know elephants
# but not leopards; point WILDGUARD_MODEL at your own fine-tuned weights to detect leopards.
DETECTOR_MODEL = os.environ.get("WILDGUARD_MODEL", "yolov8n.pt")
DETECTOR_MIN_CONF = float(os.environ.get("WILDGUARD_MIN_CONF", "0.25"))

# ---------------------------------------------------------------------------
# DEMO GEOGRAPHY (replace with real survey data for a real deployment)
# ---------------------------------------------------------------------------

VILLAGES = {
    "Village A": {"lat": 12.65, "lon": 80.1},
    "Village B": {"lat": 12.67, "lon": 80.13},
    "Village C": {"lat": 12.69, "lon": 80.08},
}

CAMERAS = {
    "CAM-01": {"lat": 12.6652, "lon": 80.1081},
    "CAM-02": {"lat": 12.6745, "lon": 80.1215},
    "CAM-03": {"lat": 12.6922, "lon": 80.0865},
    "CAM-04": {"lat": 12.6478, "lon": 80.0925},
    "CAM-05": {"lat": 12.6815, "lon": 80.0715},
}

FOREST_CENTER = {"lat": 12.675, "lon": 80.105, "radius_m": 4500}

# First-run device inventory: 18 devices (5 cameras, 3 collars, 5 acoustic, 5 PIR perimeter).
CAMERA_TYPES = {
    "CAM-01": "Thermal Camera",
    "CAM-02": "IR Camera",
    "CAM-03": "IR Camera",
    "CAM-04": "Thermal Camera",
    "CAM-05": "IR Camera",
}
SENSOR_INVENTORY = (
    [(cid, CAMERA_TYPES[cid]) for cid in CAMERAS]
    + [(f"GPS-{i:02d}", "GPS Collar") for i in range(1, 4)]
    + [(f"ACOUSTIC-{i:02d}", "Acoustic Sensor") for i in range(1, 6)]
    + [(f"PIR-{i:02d}", "Perimeter Sensor") for i in range(1, 6)]
)
SEED_OFFLINE_SENSORS = {"PIR-01", "GPS-03"}

# ---------------------------------------------------------------------------
# PREDICTION AND ALERT THRESHOLDS
# ---------------------------------------------------------------------------

THREAT_RADIUS_KM = 0.5  # default "at the village" ring (species profiles override it)
HORIZON_H = 3.0  # ignore arrivals further out than this many hours
PATH_HORIZONS_MIN = (15, 30, 60)  # minutes ahead for the predicted-path points
RECENT_WINDOW_MIN = 120  # window for the "repeated sightings" risk term
DEDUP_WINDOW_MIN = 30  # suppress repeat alerts for the same village + species
CONFIRM_THRESHOLD = 0.85  # below this confidence a ranger must confirm before alerts go out
SPECIES = ("Elephant", "Leopard")
MOVEMENTS = ("Toward Village", "Away From Village", "Parallel To Boundary")
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"  # every timestamp is stored in this format, server-local time

# ---------------------------------------------------------------------------
# LIVE INGESTION AND FUSION
# ---------------------------------------------------------------------------

FUTURE_TOLERANCE_MIN = 5  # reject device timestamps more than this far in the future
LINK_WINDOW_MIN = 90  # how far back a new fix/detection may be linked to an existing track
TRACK_POINTS_MAX = 12  # most recent track points fed to the Kalman filter
FUSION_RADIUS_KM = 1.0  # ground readings this close to a detection count as corroboration
FUSION_WINDOW_MIN = 10  # ...if they arrived within this many minutes
SENSOR_ONLY_CONFIDENCE = 0.55  # confidence given to a detection built from a ground sensor alone
SENSOR_CORROBORATION_MIN = 15  # a ground reading backs up an existing event within this window
SENSOR_CORROBORATION_KM = 1.5  # ...and within this distance
UNKNOWN_HEADING_WATCH_KM = 1.5  # stationary/unknown-heading animals this close still get a Watch
EVAL_WINDOW_MIN = 180  # default look-back for the evaluation page (lead time, precision)
LIVE_EVENT_WINDOW_MIN = 60  # a track's live event is reused (not duplicated) within this window
DEVICE_STALE_MIN = 180  # a device silent for this long is shown OFFLINE

# Species behave differently, so each gets its own profile.
#   threat_radius_km  ring around a village that counts as "reached"
#   link_max_kmh      fastest plausible speed when linking detections into one track
#   night_bonus       extra risk points after dark (elephants raid crops at night)
#   accel_sigma       Kalman process noise: how abruptly the animal changes velocity
SPECIES_PROFILES = {
    "Elephant": {"threat_radius_km": 0.5, "link_max_kmh": 8.0, "night_bonus": 10, "accel_sigma": 0.8},
    "Leopard": {"threat_radius_km": 0.4, "link_max_kmh": 12.0, "night_bonus": 8, "accel_sigma": 1.5},
    "Unknown": {"threat_radius_km": 0.5, "link_max_kmh": 8.0, "night_bonus": 0, "accel_sigma": 1.0},
}

NIGHT_START_H = 18  # "night" is from 18:00 ...
NIGHT_END_H = 6  # ... until 06:00

# Ground-sensor kinds and the reading levels that count as MEDIUM / HIGH activity.
SENSOR_KINDS = {
    "seismic": {"unit": "mm/s", "medium": 0.4, "high": 1.0},
    "acoustic": {"unit": "dB", "medium": 55.0, "high": 70.0},
    "pir": {"unit": "triggered", "medium": 1.0, "high": 1.0},
    "fence": {"unit": "broken", "medium": 1.0, "high": 1.0},
}
DEVICE_KINDS = ("camera", "collar", "ground")
KIND_BY_TYPE = {
    "Thermal Camera": "camera",
    "IR Camera": "camera",
    "GPS Collar": "collar",
    "Acoustic Sensor": "ground",
    "Perimeter Sensor": "ground",
}
