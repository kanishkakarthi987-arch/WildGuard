import io
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db, detector, evaluation, scenario
from app.config import TIME_FORMAT
from app.main import app

ADMIN = {"X-Admin-Token": "wildguard-admin"}


def ts(minutes_ago=0.0):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(TIME_FORMAT)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def provision(client, device_id, type_, kind, lat=None, lon=None, rotate=False):
    body = {"id": device_id, "type": type_, "kind": kind, "rotate": rotate}
    if lat is not None:
        body.update(lat=lat, lon=lon)
    r = client.post("/api/devices", json=body, headers=ADMIN)
    assert r.status_code == 201, r.text
    return {"X-API-Key": r.json()["api_key"]}


# ------------------------------------------------------------------ auth


def test_ingest_requires_a_device_key(client):
    body = {"fixes": [{"animal_id": "X", "species": "Elephant", "lat": 12.66, "lon": 80.1}]}
    assert client.post("/api/ingest/gps", json=body).status_code == 401
    assert client.post("/api/ingest/gps", json=body, headers={"X-API-Key": "nope"}).status_code == 401


def test_key_for_wrong_kind_is_forbidden(client):
    cam_key = provision(client, "AUTH-CAM", "IR Camera", "camera", 12.66, 80.1)
    body = {"fixes": [{"animal_id": "X", "species": "Elephant", "lat": 12.66, "lon": 80.1}]}
    assert client.post("/api/ingest/gps", json=body, headers=cam_key).status_code == 403


def test_provisioning_needs_admin_and_rotation_invalidates_old_key(client):
    body = {"id": "ROT-COLLAR", "type": "GPS Collar", "kind": "collar"}
    assert client.post("/api/devices", json=body).status_code == 401
    old = provision(client, "ROT-COLLAR", "GPS Collar", "collar")
    again = client.post("/api/devices", json=body, headers=ADMIN)
    assert again.status_code == 409
    new = provision(client, "ROT-COLLAR", "GPS Collar", "collar", rotate=True)
    fix = {"fixes": [{"animal_id": "R-1", "species": "Elephant", "lat": 12.66, "lon": 80.1, "timestamp": ts(1)}]}
    assert client.post("/api/ingest/gps", json=fix, headers=old).status_code == 401
    assert client.post("/api/ingest/gps", json=fix, headers=new).status_code == 200


def test_listing_never_exposes_key_hashes(client):
    for d in client.get("/api/devices").json():
        assert "api_key_hash" not in d and "api_key" not in d


# ----------------------------------------------------------------- collars


def approach_fixes(animal_id, minutes=20, n=6):
    """Walk from 2 km north of Village A to 1 km north of it."""
    out = []
    for i in range(n):
        frac = i / (n - 1)
        lat = 12.65 + (2.0 - 1.0 * frac) / 111.195
        out.append({"animal_id": animal_id, "species": "Elephant", "lat": lat, "lon": 80.1,
                    "timestamp": ts(minutes * (1 - frac))})
    return out


def test_collar_track_predicts_arrival_and_alerts(client):
    key = provision(client, "TEST-COLLAR", "GPS Collar", "collar")
    r = client.post("/api/ingest/gps", json={"fixes": approach_fixes("T-01")}, headers=key)
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    event = result["event"]
    assert event["will_reach"] is True and event["target_village"] == "Village A"
    assert event["alert_tier"] in ("Warning", "Imminent")
    assert event["direction"] in ("South", "South-East", "South-West")
    assert result["notification"]["status"] in ("dry_run", "suppressed")
    assert event["verification"] == "auto"  # collar fixes are high confidence


def test_collar_keeps_one_live_event_per_animal(client):
    key = provision(client, "LIVE-COLLAR", "GPS Collar", "collar")
    first = client.post("/api/ingest/gps", json={"fixes": approach_fixes("T-02")}, headers=key).json()
    more = {"fixes": [{"animal_id": "T-02", "species": "Elephant", "lat": 12.6575, "lon": 80.1, "timestamp": ts(0)}]}
    second = client.post("/api/ingest/gps", json=more, headers=key).json()
    assert first["results"][0]["event"]["id"] == second["results"][0]["event"]["id"]


def test_resent_fix_is_not_duplicated(client):
    key = provision(client, "RETRY-COLLAR", "GPS Collar", "collar")
    fixes = approach_fixes("T-03", n=4)
    client.post("/api/ingest/gps", json={"fixes": fixes}, headers=key)
    again = client.post("/api/ingest/gps", json={"fixes": fixes}, headers=key).json()
    assert len(again["results"][0]["event"]["track"]) == 4


def test_bad_gps_input_is_rejected(client):
    key = provision(client, "BAD-COLLAR", "GPS Collar", "collar")
    future = {"fixes": [{"animal_id": "B", "species": "Elephant", "lat": 12.66, "lon": 80.1,
                         "timestamp": (datetime.now() + timedelta(hours=2)).strftime(TIME_FORMAT)}]}
    assert client.post("/api/ingest/gps", json=future, headers=key).status_code == 422
    out_of_range = {"fixes": [{"animal_id": "B", "species": "Elephant", "lat": 123.0, "lon": 80.1}]}
    assert client.post("/api/ingest/gps", json=out_of_range, headers=key).status_code == 422
    wrong_species = {"fixes": [{"animal_id": "B", "species": "Tiger", "lat": 12.66, "lon": 80.1}]}
    assert client.post("/api/ingest/gps", json=wrong_species, headers=key).status_code == 422


# ----------------------------------------------------------------- cameras


def test_low_confidence_detection_waits_for_ranger_then_alerts(client):
    key = provision(client, "CONF-CAM", "IR Camera", "camera", 12.655, 80.101)  # ~0.6 km from Village A
    r = client.post("/api/ingest/detection", json={"species": "Leopard", "confidence": 0.6, "timestamp": ts(2)}, headers=key)
    assert r.status_code == 200, r.text
    event = r.json()["event"]
    assert event["alert_tier"] == "Watch"  # single sighting, heading unknown, close to a village
    assert event["verification"] == "pending"
    assert r.json()["notification"] is None
    confirmed = client.post(f"/api/events/{event['id']}/verify", json={"action": "confirm"}, headers=ADMIN)
    assert confirmed.status_code == 200
    assert confirmed.json()["notification"] is not None


def test_detection_retry_is_a_duplicate(client):
    key = provision(client, "DUP-CAM", "IR Camera", "camera", 12.60, 80.20)
    body = {"species": "Elephant", "confidence": 0.9, "timestamp": ts(30)}
    first = client.post("/api/ingest/detection", json=body, headers=key).json()
    second = client.post("/api/ingest/detection", json=body, headers=key).json()
    assert first["duplicate"] is False and second["duplicate"] is True
    assert first["event"]["id"] == second["event"]["id"]


def test_sightings_of_one_animal_are_linked_into_a_track(client):
    key = provision(client, "LINK-CAM", "IR Camera", "camera", 12.60, 80.25)
    a = client.post("/api/ingest/detection", json={"species": "Elephant", "confidence": 0.9, "timestamp": ts(40)}, headers=key).json()
    far = {"species": "Elephant", "confidence": 0.9, "timestamp": ts(20), "lat": 12.6015, "lon": 80.25}
    b = client.post("/api/ingest/detection", json=far, headers=key).json()
    assert a["event"]["track_id"] == b["event"]["track_id"]
    assert len(b["event"]["track"]) == 2
    assert b["event"]["speed_kmh"] > 0


def png_bytes():
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (90, 120, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_upload_with_manual_label_and_media_served(client):
    key = provision(client, "IMG-CAM", "IR Camera", "camera", 12.655, 80.1005)
    files = {"file": ("trap.png", png_bytes(), "image/png")}
    r = client.post("/api/ingest/camera", files=files, data={"species": "Elephant", "confidence": "0.95"}, headers=key)
    assert r.status_code == 200, r.text
    name = r.json()["image"]
    assert r.json()["results"][0]["event"]["image"] == name
    media = client.get(f"/api/media/{name}")
    assert media.status_code == 200 and media.headers["content-type"].startswith("image/")
    assert client.get("/api/media/../../etc/passwd").status_code in (404, 422)
    assert client.get("/api/media/" + "0" * 32 + ".png").status_code == 404


def test_image_upload_rejects_non_images(client):
    key = provision(client, "BADIMG-CAM", "IR Camera", "camera", 12.60, 80.3)
    files = {"file": ("x.png", b"not an image", "image/png")}
    r = client.post("/api/ingest/camera", files=files, data={"species": "Elephant"}, headers=key)
    assert r.status_code == 422


def test_image_upload_runs_the_detector(client, monkeypatch):
    key = provision(client, "YOLO-CAM", "IR Camera", "camera", 12.60, 80.35)
    monkeypatch.setattr(
        detector, "detect",
        lambda data: [{"species": "Elephant", "confidence": 0.91, "label": "elephant", "box": [0, 0, 5, 5]},
                      {"species": "Elephant", "confidence": 0.72, "label": "elephant", "box": [5, 5, 9, 9]}],
    )
    files = {"file": ("trap.png", png_bytes(), "image/png")}
    r = client.post("/api/ingest/camera", files=files, headers=key)
    assert r.status_code == 200, r.text
    event = r.json()["results"][0]["event"]
    assert event["count"] == 2 and event["confidence"] == 0.91  # best box, herd size recorded


def test_image_upload_without_yolo_returns_503(client, monkeypatch):
    key = provision(client, "NOYOLO-CAM", "IR Camera", "camera", 12.60, 80.36)
    monkeypatch.setattr(detector, "is_installed", lambda: False)
    monkeypatch.setattr(detector, "_model", None)
    files = {"file": ("trap.png", png_bytes(), "image/png")}
    r = client.post("/api/ingest/camera", files=files, headers=key)
    assert r.status_code == 503 and "Ultralytics" in r.json()["detail"]


# ----------------------------------------------------------- ground sensors


def test_uncorroborated_ground_trigger_is_unverified_then_deduplicated(client):
    key = provision(client, "TEST-GND", "Acoustic Sensor", "ground", 12.682, 80.081)  # ~0.9 km from Village C
    old = ts(20 * 60)  # 20 h ago: nothing else is happening around then
    r = client.post("/api/ingest/sensor", json={"readings": [{"kind": "seismic", "value": 1.4, "timestamp": old}]}, headers=key)
    assert r.status_code == 200, r.text
    triggers = r.json()["triggers"]
    assert len(triggers) == 1
    event = triggers[0]
    assert event["animal"] == "Unknown" and event["verification"] == "pending"
    assert event["alert_tier"] == "Watch"
    again = client.post("/api/ingest/sensor", json={"readings": [{"kind": "seismic", "value": 1.6, "timestamp": old}]}, headers=key)
    assert again.json()["triggers"] == []


def test_weak_or_unknown_sensor_readings(client):
    key = provision(client, "WEAK-GND", "Perimeter Sensor", "ground", 12.60, 80.4)
    weak = client.post("/api/ingest/sensor", json={"readings": [{"kind": "seismic", "value": 0.1}]}, headers=key)
    assert weak.status_code == 200 and weak.json()["triggers"] == []
    bad = client.post("/api/ingest/sensor", json={"readings": [{"kind": "radar", "value": 1}]}, headers=key)
    assert bad.status_code == 422


def test_ground_readings_raise_the_risk_of_a_nearby_detection(client):
    gkey = provision(client, "FUSE-GND", "Acoustic Sensor", "ground", 12.5000, 80.5000)
    ckey = provision(client, "FUSE-CAM", "IR Camera", "camera", 12.5000, 80.5002)
    when = ts(45 * 60)
    plain = client.post("/api/ingest/detection", json={"species": "Elephant", "confidence": 0.9, "timestamp": when, "lat": 12.55, "lon": 80.55}, headers=ckey).json()
    client.post("/api/ingest/sensor", json={"readings": [{"kind": "seismic", "value": 1.5, "timestamp": ts(45 * 60 - 1)}]}, headers=gkey)
    fused = client.post("/api/ingest/detection", json={"species": "Elephant", "confidence": 0.9, "timestamp": ts(45 * 60 - 2)}, headers=ckey).json()
    assert fused["event"]["sensor_data"]["fused_readings"] >= 1
    assert fused["event"]["risk_score"] > plain["event"]["risk_score"]


# --------------------------------------------------- zones, scenario, metrics


def test_risk_zones_peak_near_villages(client):
    zones = client.get("/api/risk-zones").json()
    assert zones["cells"] and all(0 <= c["risk"] <= 1 for c in zones["cells"])
    best = max(zones["cells"], key=lambda c: c["risk"])
    near = min(((best["lat"] - v[0]) ** 2 + (best["lon"] - v[1]) ** 2) ** 0.5 for v in [(12.65, 80.10), (12.67, 80.13), (12.69, 80.08)])
    assert near < 0.03  # within about 3 km of a village


def test_scenario_plan_is_deterministic_and_complete(client):
    devices = db.list_sensors()
    now = datetime.now()
    a = scenario.build_plan(devices, [("approach", "Elephant", "Village A")], now, seed=11)
    b = scenario.build_plan(devices, [("approach", "Elephant", "Village A")], now, seed=11)
    assert [s["payload"] for s in a] == [s["payload"] for s in b]
    assert a[-1]["type"] == "incident" and a[0]["type"] == "gps"
    assert all(a[i]["t"] <= a[i + 1]["t"] for i in range(len(a) - 1))
    assert a[-1]["t"] <= now


def test_approach_scenario_warns_before_the_incident(client):
    before = len(db.list_incidents())
    steps = scenario.build_plan(db.list_sensors(), [("approach", "Elephant", "Village B")], datetime.now(), seed=5)
    by_id = {d["id"]: d for d in db.list_sensors()}
    for step in steps:
        scenario.apply_step(step, by_id)
    assert len(db.list_incidents()) == before + 1
    report = client.get("/api/evaluation").json()
    assert report["incidents"] >= 1 and report["alerts"] >= 1
    assert report["median_lead_minutes"] is not None and report["median_lead_minutes"] > 0
    assert report["recall"] is not None


def test_evaluation_math(monkeypatch):
    notifications = [
        {"id": 1, "timestamp": "2026-10-01 10:00:00", "village": "Village A", "animal": "Elephant", "tier": "Warning", "status": "dry_run"},
        {"id": 2, "timestamp": "2026-10-01 11:00:00", "village": "Village B", "animal": "Elephant", "tier": "Watch", "status": "dry_run"},
        {"id": 3, "timestamp": "2026-10-01 11:05:00", "village": "Village B", "animal": "Elephant", "tier": "Watch", "status": "suppressed"},
    ]
    incidents = [
        {"id": 1, "timestamp": "2026-10-01 10:40:00", "village": "Village A", "animal": "Elephant", "source": "ranger", "notes": None},
        {"id": 2, "timestamp": "2026-10-03 10:00:00", "village": "Village C", "animal": "Leopard", "source": "ranger", "notes": None},
    ]
    monkeypatch.setattr(db, "list_notifications", lambda limit=0: notifications)
    monkeypatch.setattr(db, "list_incidents", lambda: incidents)
    monkeypatch.setattr(db, "list_events", lambda limit=None: [])
    result = evaluation.evaluate(180)
    assert result["alerts"] == 2 and result["true_alerts"] == 1 and result["false_alerts"] == 1
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5  # Village C incident was never warned about
    assert result["median_lead_minutes"] == 40.0
    assert result["suppressed_duplicates"] == 1
    # span 2 days -> 1 false alarm over 2/7 weeks = 3.5 per week
    assert result["false_alarms_per_week"] == 3.5


def test_incident_and_demo_endpoints_need_admin(client):
    assert client.post("/api/incidents", json={"village": "Village A"}).status_code == 401
    assert client.post("/api/demo/scenario", json={}).status_code == 401
    ok = client.post("/api/incidents", json={"village": "Village A", "animal": "Elephant", "notes": "test"}, headers=ADMIN)
    assert ok.status_code == 201
    assert client.post("/api/incidents", json={"village": "Nowhere"}, headers=ADMIN).status_code == 422
