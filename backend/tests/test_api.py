import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # Ranger actions (simulate, verify, subscribers) need the admin token; send it by default.
    with TestClient(app, headers={"X-Admin-Token": "wildguard-admin"}) as c:  # lifespan seeds the temp DB
        yield c


def test_seed_loaded_with_unified_schema(client):
    events = client.get("/api/sightings?limit=1000").json()
    assert len(events) >= 47
    for e in events:
        assert "lat" in e and "lon" in e and "risk" in e and "timestamp" in e
        assert "latitude" not in e and "risk_level" not in e


def test_statistics_and_sensors_are_computed(client):
    stats = client.get("/api/statistics").json()
    sensors = client.get("/api/sensors").json()
    assert sensors["total"] == 18
    assert stats["active_sensors"] == sensors["online"]
    assert sensors["offline"] == 2


def test_simulation_validates_input(client):
    bad = client.post("/api/simulate", json={"animal": "Tiger"})
    assert bad.status_code == 422
    bad_cam = client.post("/api/simulate", json={"camera_id": "CAM-99"})
    assert bad_cam.status_code == 422


def test_ids_never_collide(client):
    first = client.post("/api/simulate", json={}).json()["event"]["id"]
    second = client.post("/api/simulate", json={}).json()["event"]["id"]
    assert second > first


def test_direction_is_not_always_north_east(client):
    directions = set()
    for movement in ("Toward Village", "Away From Village", "Parallel To Boundary"):
        for cam in ("CAM-01", "CAM-03", "CAM-04"):
            r = client.post("/api/simulate", json={"movement": movement, "camera_id": cam}).json()
            directions.add(r["event"]["direction"])
    assert len(directions) >= 3


def test_prediction_fields_are_real(client):
    predictions = client.get("/api/predict").json()
    assert predictions
    for p in predictions:
        assert p["path"] and p["speed_kmh"] >= 0
        if p["will_reach"]:
            assert isinstance(p["eta_minutes"], int)


def test_emergency_produces_an_alert(client):
    body = client.post("/api/simulate-emergency").json()
    event = body["event"]
    assert event["will_reach"] is True
    assert event["alert_tier"] in ("Watch", "Warning", "Imminent")
    assert body["notification"] is not None
    assert body["notification"]["status"] in ("dry_run", "suppressed")


def test_duplicate_alerts_are_suppressed(client):
    # Hammer one village/species; later alerts at the same tier must be suppressed.
    statuses = []
    for _ in range(6):
        r = client.post("/api/simulate-emergency").json()
        if r["notification"]:
            statuses.append((r["event"]["animal"], r["notification"]["village"], r["notification"]["status"]))
    assert any(s[2] == "suppressed" for s in statuses) or len(statuses) <= 1


def test_low_confidence_needs_ranger_then_sends(client):
    pending = [a for a in client.get("/api/alerts?limit=200").json() if a["verification"] == "pending"]
    if not pending:
        for _ in range(60):
            e = client.post("/api/simulate", json={"movement": "Toward Village"}).json()["event"]
            if e["verification"] == "pending":
                pending = [e]
                break
    if not pending:
        pytest.skip("random run produced no low-confidence alert")
    event_id = pending[0]["id"]
    ok = client.post(f"/api/events/{event_id}/verify", json={"action": "confirm"})
    assert ok.status_code == 200
    again = client.post(f"/api/events/{event_id}/verify", json={"action": "confirm"})
    assert again.status_code == 409


def test_subscribers_masked_and_validated(client):
    listing = client.get("/api/subscribers").json()
    assert listing and all(s["phone"].startswith("******") for s in listing)
    bad = client.post("/api/subscribers", json={"name": "X", "phone": "123", "village": "Village A"})
    assert bad.status_code == 422


def test_ranger_actions_reject_a_missing_or_wrong_token(client):
    bad = {"X-Admin-Token": "wrong"}
    assert client.post("/api/simulate", json={}, headers=bad).status_code == 401
    assert client.post("/api/simulate-emergency", headers=bad).status_code == 401
    assert client.post("/api/events/1/verify", json={"action": "confirm"}, headers=bad).status_code == 401
    assert client.get("/api/subscribers", headers=bad).status_code == 401
    assert client.post("/api/subscribers", headers=bad,
                       json={"name": "X", "phone": "9876543210", "village": "Village A"}).status_code == 401
    assert client.get("/api/auth/check", headers=bad).status_code == 401
    assert client.get("/api/auth/check").status_code == 200


def test_unset_admin_token_is_random_and_persisted(tmp_path, monkeypatch):
    import importlib

    from app import config

    monkeypatch.delenv("WILDGUARD_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("WILDGUARD_DB", str(tmp_path / "x.db"))
    try:
        first = importlib.reload(config)
        token = first.ADMIN_TOKEN
        assert len(token) >= 20 and token != "wildguard-admin"
        assert (tmp_path / "admin_token.txt").read_text().strip() == token
        assert importlib.reload(config).ADMIN_TOKEN == token  # stable across restarts
    finally:
        monkeypatch.setenv("WILDGUARD_ADMIN_TOKEN", "wildguard-admin")
        monkeypatch.setenv("WILDGUARD_DB", os.environ["WILDGUARD_DB"])
        importlib.reload(config)


def test_config_reports_server_utc_offset(client):
    cfg = client.get("/api/config").json()
    assert isinstance(cfg["utc_offset_minutes"], int)
    assert -14 * 60 <= cfg["utc_offset_minutes"] <= 14 * 60
