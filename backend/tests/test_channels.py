"""Voice and beacon channels, device staleness, LoRa frames and the live-stream counter."""

import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import bus, config, db, lora, notify
from app.config import TIME_FORMAT
from app.main import app

ADMIN = {"X-Admin-Token": "wildguard-admin"}
GATEWAY = {"X-Gateway-Key": "test-gateway-key"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def ts(minutes_ago=0.0):
    return (datetime.now() - timedelta(minutes=minutes_ago)).strftime(TIME_FORMAT)


def provision(client, device_id, type_, kind, lat=None, lon=None, lora_id=None):
    body = {"id": device_id, "type": type_, "kind": kind, "rotate": True}
    if lat is not None:
        body.update(lat=lat, lon=lon)
    if lora_id is not None:
        body["lora_id"] = lora_id
    r = client.post("/api/devices", json=body, headers=ADMIN)
    assert r.status_code == 201, r.text
    return {"X-API-Key": r.json()["api_key"]}


# ------------------------------------------------------------------ channels


def test_imminent_alert_logs_sms_and_voice_but_counts_once(client):
    event = {"animal": "Elephant"}
    before = db.count_notifications()
    # Village A has a voice subscriber (Murugan) in the seed data
    sms = notify.dispatch(9001, event, "Imminent", "Village A", 5, 0.8)
    assert sms["channel"] == "sms" and sms["status"] == "dry_run"
    assert sms["voice"]["channel"] == "voice" and sms["voice"]["status"] == "dry_run"
    assert sms["voice"]["recipients"] >= 1
    assert db.count_notifications() == before + 1  # one alert, not one per channel


def test_watch_tier_sends_no_voice_call(client):
    sms = notify.dispatch(9002, {"animal": "Leopard"}, "Watch", "Village C", 120, 2.0)
    assert sms["status"] in ("dry_run", "suppressed")
    assert "voice" not in sms


def test_repeat_alert_is_suppressed_on_every_channel(client):
    notify.dispatch(9003, {"animal": "Elephant"}, "Warning", "Village B", 30, 1.0)
    again = notify.dispatch(9004, {"animal": "Elephant"}, "Warning", "Village B", 25, 0.9)
    assert again["status"] == "suppressed" and "voice" not in again


def test_spoken_text_drops_the_bracket_tag():
    en, ta = notify.build_messages("Elephant", "Village A", "Warning", 1.2, 20)
    assert notify.spoken(en).startswith("Elephant detected")
    assert not notify.spoken(ta).startswith("[")


def test_voice_failure_is_recorded_not_raised(client, monkeypatch):
    monkeypatch.setattr(config, "VOICE_PROVIDER", "twilio")  # no Twilio settings configured
    sms = notify.dispatch(9005, {"animal": "Leopard"}, "Imminent", "Village C", 3, 0.4)
    assert sms["voice"]["status"] == "failed" and "Twilio" in sms["voice"]["error"]


def test_beacon_only_fires_when_a_webhook_is_configured(client, monkeypatch):
    posted = []
    monkeypatch.setattr(notify, "_post_json", lambda url, payload: (posted.append((url, payload)) or (True, None)))
    off = notify.dispatch(9006, {"animal": "Elephant"}, "Imminent", "Village A", 4, 0.6)
    assert off.get("beacon") is None and not posted
    monkeypatch.setattr(config, "BEACON_WEBHOOK_URL", "http://beacon.local/alarm")
    on = notify.dispatch(9007, {"animal": "Leopard"}, "Imminent", "Village A", 4, 0.6)
    assert on["beacon"]["status"] == "sent" and posted[0][1]["tier"] == "Imminent"


def test_subscriber_can_opt_in_to_voice(client):
    created = client.post("/api/subscribers", headers=ADMIN, json={
        "name": "Test", "phone": "9876543210", "village": "Village B", "language": "ta", "voice": True}).json()
    assert created["voice"] is True and created["phone"] == "******3210"


# ---------------------------------------------------------- device staleness


def test_silent_device_shows_offline(client):
    key = provision(client, "STALE-GPS", "GPS Collar", "collar")
    fix = {"fixes": [{"animal_id": "S-1", "species": "Elephant", "lat": 12.69, "lon": 80.12, "timestamp": ts(1)}]}
    assert client.post("/api/ingest/gps", json=fix, headers=key).status_code == 200
    assert db.get_device("STALE-GPS")["status"] == "ONLINE"
    long_ago = (datetime.now() - timedelta(minutes=config.DEVICE_STALE_MIN + 30)).strftime(TIME_FORMAT)
    db.touch_device("STALE-GPS", long_ago)
    assert db.get_device("STALE-GPS")["status"] == "OFFLINE"
    assert next(s for s in client.get("/api/sensors").json()["sensors"] if s["id"] == "STALE-GPS")["status"] == "OFFLINE"


def test_last_seen_is_server_time_even_for_old_buffered_data(client):
    key = provision(client, "BUFFER-GPS", "GPS Collar", "collar")
    old = {"fixes": [{"animal_id": "B-1", "species": "Elephant", "lat": 12.69, "lon": 80.12, "timestamp": ts(50)}]}
    client.post("/api/ingest/gps", json=old, headers=key)
    assert db.get_device("BUFFER-GPS")["status"] == "ONLINE"  # it just uploaded, even though the fix is 50 min old


# ------------------------------------------------------------------- LoRa


def test_lora_frames_round_trip():
    unix = int(time.time())
    gps = lora.decode(lora.encode_gps(7, unix, 12.65123, 80.10456, "Elephant", 12))
    assert (gps["lora_id"], gps["animal_id"], gps["species"]) == (7, "E-12", "Elephant")
    assert gps["lat"] == pytest.approx(12.65123, abs=1e-6) and gps["lon"] == pytest.approx(80.10456, abs=1e-6)
    ground = lora.decode(lora.encode_ground(8, unix, "acoustic", 70.5))
    assert ground["sensor_kind"] == "acoustic" and ground["value"] == pytest.approx(70.5)
    det = lora.decode(lora.encode_detection(9, unix, "Leopard", 0.87, 2))
    assert (det["species"], det["confidence"], det["count"]) == ("Leopard", 0.87, 2)
    assert len(lora.encode_gps(1, unix, 1.0, 1.0, "Elephant", 1)) == 18
    assert len(lora.encode_ground(1, unix, "pir", 1)) == 11


@pytest.mark.parametrize("frame", [b"", b"\x01", b"\x02\x01\x00\x01" + b"\x00" * 20, b"\x01\x09\x00\x01\x00\x00\x00\x00"])
def test_malformed_frames_are_rejected(frame):
    with pytest.raises(ValueError):
        lora.decode(frame)


def test_lora_endpoint_needs_the_gateway_key(client):
    body = {"frames": ["00"]}
    assert client.post("/api/ingest/lora", json=body).status_code == 401
    assert client.post("/api/ingest/lora", json=body, headers={"X-Gateway-Key": "nope"}).status_code == 401


def test_lora_uplink_reaches_the_same_pipeline(client):
    provision(client, "LORA-COLLAR", "GPS Collar", "collar", lora_id=4101)
    provision(client, "LORA-CAM", "IR Camera", "camera", 12.66, 80.1, lora_id=4102)
    now = int(time.time())
    # an elephant walking south toward Village A, five fixes 4 minutes apart
    frames = []
    for i in range(5):
        lat = 12.65 + (1.6 - 0.2 * i) / 111.195
        frames.append(lora.encode_gps(4101, now - (4 - i) * 240, lat, 80.1, "Elephant", 7).hex())
    frames.append(lora.encode_detection(4102, now, "Elephant", 0.93).hex())
    frames.append("zz")                                                    # not hex
    frames.append(lora.encode_gps(5999, now, 12.6, 80.1, "Elephant", 1).hex())  # unknown device
    frames.append(lora.encode_gps(4102, now, 12.6, 80.1, "Elephant", 1).hex())  # camera sending a GPS frame
    r = client.post("/api/ingest/lora", json={"frames": frames}, headers=GATEWAY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == 6 and body["rejected"] == 3
    assert [x["ok"] for x in body["results"]] == [True] * 6 + [False] * 3
    track = db.get_points("collar:E-7", datetime.now(), 60, 12)
    assert len(track) == 5
    events = [e for e in db.list_events(limit=50) if e.get("track_id") == "collar:E-7"]
    assert events and events[-1]["will_reach"] is True and events[-1]["target_village"] == "Village A"


def test_lora_is_off_without_a_gateway_key(client, monkeypatch):
    monkeypatch.setattr(config, "GATEWAY_KEY", "")
    assert client.post("/api/ingest/lora", json={"frames": ["00"]}, headers=GATEWAY).status_code == 503


# ------------------------------------------------------------------- stream


def test_every_write_bumps_the_stream_counter(client):
    before = bus.version()
    db.add_log("X", "camera", "accepted", "ping")
    assert bus.version() > before
    quiet = bus.version()
    db.list_events(limit=5)  # reads do not bump
    assert bus.version() == quiet


def test_stream_emits_an_event_after_a_write():
    import asyncio

    from app.main import stream

    class FakeRequest:
        async def is_disconnected(self):
            return False

    async def run():
        response = await stream(FakeRequest())
        it = response.body_iterator
        assert (await it.__anext__()).startswith("retry:")
        task = asyncio.ensure_future(it.__anext__())
        await asyncio.sleep(0.1)
        db.add_log("X", "camera", "accepted", "wake up")
        chunk = await asyncio.wait_for(task, timeout=3)
        await it.aclose()
        return chunk

    assert asyncio.run(run()).startswith("data: ")
