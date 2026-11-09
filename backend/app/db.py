"""SQLite storage. One short-lived connection per call keeps this simple and thread-safe."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from . import bus, config
from .config import TIME_FORMAT

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    animal TEXT NOT NULL,
    risk TEXT,
    track_id TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp);
CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    village TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    voice INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_id INTEGER,
    village TEXT,
    animal TEXT,
    tier TEXT,
    channel TEXT NOT NULL DEFAULT 'sms',
    recipients INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    provider TEXT,
    message TEXT,
    message_local TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS sensors (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    battery INTEGER NOT NULL,
    last_seen TEXT,
    kind TEXT,
    lat REAL,
    lon REAL,
    api_key_hash TEXT,
    lora_id INTEGER
);
CREATE TABLE IF NOT EXISTS track_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    species TEXT,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_points_track ON track_points(track_id, ts);
CREATE TABLE IF NOT EXISTS ground_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    device_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value REAL NOT NULL,
    lat REAL,
    lon REAL
);
CREATE INDEX IF NOT EXISTS idx_ground_ts ON ground_readings(ts);
CREATE TABLE IF NOT EXISTS ingest_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    device_id TEXT,
    kind TEXT,
    status TEXT NOT NULL,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    village TEXT NOT NULL,
    animal TEXT,
    source TEXT,
    notes TEXT
);
"""

DEVICE_COLUMNS = "id, type, kind, lat, lon, status, battery, last_seen, lora_id, (api_key_hash IS NOT NULL) AS has_key"


def now_str() -> str:
    return datetime.now().strftime(TIME_FORMAT)


def fmt(ts: datetime) -> str:
    return ts.strftime(TIME_FORMAT)


@contextmanager
def get_conn():
    path = config.DB_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
        if conn.total_changes:
            bus.bump()  # something was written: wake the live stream
    finally:
        conn.close()


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Upgrade databases created by v3.
        for column, ddl in (("kind", "TEXT"), ("lat", "REAL"), ("lon", "REAL"),
                            ("api_key_hash", "TEXT"), ("lora_id", "INTEGER")):
            if column not in _columns(conn, "sensors"):
                conn.execute(f"ALTER TABLE sensors ADD COLUMN {column} {ddl}")
        if "voice" not in _columns(conn, "subscribers"):
            conn.execute("ALTER TABLE subscribers ADD COLUMN voice INTEGER NOT NULL DEFAULT 0")
        if "channel" not in _columns(conn, "notifications"):
            conn.execute("ALTER TABLE notifications ADD COLUMN channel TEXT NOT NULL DEFAULT 'sms'")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sensors_lora ON sensors(lora_id) WHERE lora_id IS NOT NULL")
        if "track_id" not in _columns(conn, "events"):
            conn.execute("ALTER TABLE events ADD COLUMN track_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_track ON events(track_id)")


# ---------------------------------------------------------------- events


def _row_to_event(row) -> dict:
    event = json.loads(row["payload"])
    event["id"] = row["id"]
    return event


def insert_event(event: dict) -> int:
    payload = {k: v for k, v in event.items() if k != "id"}
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO events (timestamp, animal, risk, track_id, payload) VALUES (?, ?, ?, ?, ?)",
            (event["timestamp"], event["animal"], event.get("risk"), event.get("track_id"), json.dumps(payload)),
        )
        return cur.lastrowid


def list_events(limit: int | None = None) -> list[dict]:
    """Oldest-first list. With a limit, returns the newest `limit` events (still oldest-first)."""
    with get_conn() as conn:
        if limit:
            rows = conn.execute(
                "SELECT * FROM (SELECT * FROM events ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM events ORDER BY id ASC").fetchall()
    return [_row_to_event(r) for r in rows]


def list_events_since(ts: datetime) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE timestamp >= ? ORDER BY id ASC", (fmt(ts),)
        ).fetchall()
    return [_row_to_event(r) for r in rows]


def get_event(event_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return _row_to_event(row) if row else None


def find_live_event(track_id: str, ref: datetime, within_min: int) -> dict | None:
    """Most recent event on a track no older than `within_min` before `ref`."""
    cutoff = fmt(ref - timedelta(minutes=within_min))
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM events WHERE track_id = ? AND timestamp >= ? ORDER BY id DESC LIMIT 1",
            (track_id, cutoff),
        ).fetchone()
    return _row_to_event(row) if row else None


def update_event(event_id: int, fields: dict) -> dict | None:
    event = get_event(event_id)
    if event is None:
        return None
    event.update(fields)
    payload = {k: v for k, v in event.items() if k != "id"}
    with get_conn() as conn:
        conn.execute(
            "UPDATE events SET timestamp = ?, risk = ?, track_id = ?, payload = ? WHERE id = ?",
            (event["timestamp"], event.get("risk"), event.get("track_id"), json.dumps(payload), event_id),
        )
    return event


def count_events() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


# ----------------------------------------------------------- track points


def add_points(track_id: str, species: str, source: str, points: list[tuple]) -> None:
    """points: [(ts_str, lat, lon), ...]. Re-sending the same fix is a no-op (retries are safe)."""
    with get_conn() as conn:
        for ts, lat, lon in points:
            conn.execute(
                "INSERT INTO track_points (track_id, ts, lat, lon, species, source) "
                "SELECT ?, ?, ?, ?, ?, ? WHERE NOT EXISTS "
                "(SELECT 1 FROM track_points WHERE track_id = ? AND ts = ?)",
                (track_id, ts, lat, lon, species, source, track_id, ts),
            )


def get_points(track_id: str, ref: datetime, window_min: int, limit: int) -> list[dict]:
    """Newest `limit` points within the window ending at `ref`, returned oldest-first."""
    cutoff = fmt(ref - timedelta(minutes=window_min))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ts, lat, lon FROM track_points WHERE track_id = ? AND ts >= ? AND ts <= ? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (track_id, cutoff, fmt(ref), limit),
        ).fetchall()
    return [{"t": r["ts"], "lat": r["lat"], "lon": r["lon"]} for r in reversed(rows)]


def recent_tracks(minutes: int, ref: datetime, limit_points: int = 20) -> list[dict]:
    cutoff = fmt(ref - timedelta(minutes=minutes))
    with get_conn() as conn:
        ids = conn.execute(
            "SELECT track_id, MAX(species) AS species, MAX(source) AS source, MAX(ts) AS last_ts "
            "FROM track_points WHERE ts >= ? GROUP BY track_id ORDER BY last_ts DESC LIMIT 40",
            (cutoff,),
        ).fetchall()
    tracks = []
    for row in ids:
        pts = get_points(row["track_id"], ref, minutes, limit_points)
        if pts:
            tracks.append({
                "track_id": row["track_id"],
                "species": row["species"],
                "source": row["source"],
                "points": pts,
            })
    return tracks


# -------------------------------------------------------- ground readings


def add_reading(ts: str, device_id: str, kind: str, value: float, lat, lon) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO ground_readings (ts, device_id, kind, value, lat, lon) VALUES (?, ?, ?, ?, ?, ?)",
            (ts, device_id, kind, value, lat, lon),
        )


def recent_readings(ref: datetime, minutes: int) -> list[dict]:
    cutoff = fmt(ref - timedelta(minutes=minutes))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ground_readings WHERE ts >= ? AND ts <= ? ORDER BY ts ASC",
            (cutoff, fmt(ref)),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------- ingest log


def add_log(device_id, kind, status, summary, ts: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO ingest_log (timestamp, device_id, kind, status, summary) VALUES (?, ?, ?, ?, ?)",
            (ts or now_str(), device_id, kind, status, summary),
        )


def list_log(limit: int = 40) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM ingest_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# -------------------------------------------------------------- incidents


def add_incident(ts: str, village: str, animal: str | None, source: str, notes: str | None) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO incidents (timestamp, village, animal, source, notes) VALUES (?, ?, ?, ?, ?)",
            (ts, village, animal, source, notes),
        )
        return {"id": cur.lastrowid, "timestamp": ts, "village": village, "animal": animal,
                "source": source, "notes": notes}


def list_incidents() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM incidents ORDER BY timestamp ASC, id ASC").fetchall()
    return [dict(r) for r in rows]


# ----------------------------------------------------------- subscribers


def list_subscribers(village: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if village:
            rows = conn.execute("SELECT * FROM subscribers WHERE village = ? ORDER BY id", (village,))
        else:
            rows = conn.execute("SELECT * FROM subscribers ORDER BY id")
        return [dict(r) for r in rows.fetchall()]


def add_subscriber(name: str, phone: str, village: str, language: str, voice: bool = False) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO subscribers (name, phone, village, language, voice) VALUES (?, ?, ?, ?, ?)",
            (name, phone, village, language, int(voice)),
        )
        return {"id": cur.lastrowid, "name": name, "phone": phone, "village": village,
                "language": language, "voice": bool(voice)}


# --------------------------------------------------------- notifications


def add_notification(record: dict) -> dict:
    cols = ("timestamp", "event_id", "village", "animal", "tier", "channel", "recipients",
            "status", "provider", "message", "message_local", "error")
    values = [record.get(c) if c != "channel" else record.get("channel", "sms") for c in cols]
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO notifications ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            values,
        )
        record = dict(record)
        record["id"] = cur.lastrowid
        return record


def list_notifications(limit: int = 30) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows.fetchall()]


def recent_notifications(village: str, animal: str, minutes: int, ref: datetime | None = None) -> list[dict]:
    """Alerts that went out (or would have, in dry-run) in the window before `ref`."""
    ref = ref or datetime.now()
    cutoff = fmt(ref - timedelta(minutes=minutes))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE village = ? AND animal = ? AND timestamp >= ? "
            "AND timestamp <= ? AND channel = 'sms' AND status IN ('sent', 'dry_run')",
            (village, animal, cutoff, fmt(ref)),
        )
        return [dict(r) for r in rows.fetchall()]


def find_notification(event_id: int, tier: str, status: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM notifications WHERE event_id = ? AND tier = ? AND status = ? AND channel = 'sms' LIMIT 1",
            (event_id, tier, status),
        ).fetchone()
    return dict(row) if row else None


def count_notifications() -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE channel = 'sms' AND status IN ('sent', 'dry_run')"
        ).fetchone()[0]


# --------------------------------------------------- devices (sensors table)


def _with_status(row) -> dict:
    """ONLINE only if the device reported recently. The stored status column is not trusted:
    a device that dies cannot tell us, so silence has to mean OFFLINE."""
    device = dict(row)
    online = False
    if device.get("last_seen"):
        try:
            age = datetime.now() - datetime.strptime(device["last_seen"], TIME_FORMAT)
            online = age <= timedelta(minutes=config.DEVICE_STALE_MIN)
        except ValueError:
            pass
    device["status"] = "ONLINE" if online else "OFFLINE"
    return device


def list_sensors() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(f"SELECT {DEVICE_COLUMNS} FROM sensors ORDER BY id").fetchall()
    return [_with_status(r) for r in rows]


def get_device(device_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(f"SELECT {DEVICE_COLUMNS} FROM sensors WHERE id = ?", (device_id,)).fetchone()
    return _with_status(row) if row else None


def get_device_by_key_hash(key_hash: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT {DEVICE_COLUMNS} FROM sensors WHERE api_key_hash = ?", (key_hash,)
        ).fetchone()
    return _with_status(row) if row else None


def get_device_by_lora_id(lora_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(f"SELECT {DEVICE_COLUMNS} FROM sensors WHERE lora_id = ?", (lora_id,)).fetchone()
    return _with_status(row) if row else None


def upsert_sensor(sensor_id, sensor_type, status, battery, last_seen, kind=None, lat=None, lon=None, lora_id=None):
    kind = kind or config.KIND_BY_TYPE.get(sensor_type, "ground")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sensors (id, type, status, battery, last_seen, kind, lat, lon, lora_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET type=excluded.type, status=excluded.status, "
            "battery=excluded.battery, last_seen=excluded.last_seen, kind=excluded.kind, "
            "lat=COALESCE(excluded.lat, sensors.lat), lon=COALESCE(excluded.lon, sensors.lon), "
            "lora_id=COALESCE(excluded.lora_id, sensors.lora_id)",
            (sensor_id, sensor_type, status, battery, last_seen, kind, lat, lon, lora_id),
        )


def set_device_key(device_id: str, key_hash: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE sensors SET api_key_hash = ? WHERE id = ?", (key_hash, device_id))


def heartbeat(sensor_id: str, battery: int, when: str) -> None:
    """A detection from a sensor proves it is alive."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE sensors SET status = 'ONLINE', battery = ?, last_seen = ? WHERE id = ?",
            (battery, when, sensor_id),
        )


def touch_device(device_id: str, when: str, battery: int | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sensors SET status = 'ONLINE', last_seen = ?, battery = COALESCE(?, battery) WHERE id = ?",
            (when, battery, device_id),
        )
