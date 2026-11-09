from datetime import datetime, timedelta

import pytest

from app import geo, predictor, risk
from app.config import TIME_FORMAT, VILLAGES


def test_haversine_one_degree_latitude():
    assert geo.haversine_km(12.0, 80.0, 13.0, 80.0) == pytest.approx(111.19, abs=0.2)


def test_bearing_cardinals():
    assert geo.bearing_deg(12.0, 80.0, 13.0, 80.0) == pytest.approx(0, abs=0.5)
    assert geo.bearing_deg(12.0, 80.0, 12.0, 81.0) == pytest.approx(90, abs=0.5)
    assert geo.bearing_to_direction(45) == "North-East"
    assert geo.bearing_to_direction(359) == "North"


def test_angle_diff_wraps():
    assert geo.angle_diff(350, 10) == 20
    assert geo.angle_diff(90, 270) == 180


def _straight_track(start, bearing, speed_kmh, steps=6, interval_min=10):
    end = datetime(2026, 10, 3, 12, 0, 0)
    lat, lon = start
    pts = []
    for i in range(steps):
        age = (steps - 1 - i) * interval_min
        d = speed_kmh * age / 60
        p = geo.offset_point(lat, lon, (bearing + 180) % 360, d)
        pts.append({"t": (end - timedelta(minutes=age)).strftime(TIME_FORMAT), "lat": p[0], "lon": p[1]})
    return pts


def test_kalman_recovers_speed_and_heading():
    village = VILLAGES["Village A"]
    start = geo.offset_point(village["lat"], village["lon"], 0, 2.0)  # 2 km north of village A
    track = _straight_track(start, bearing=180, speed_kmh=2.0)
    p = predictor.predict_from_track(track)
    assert p["speed_kmh"] == pytest.approx(2.0, abs=0.3)
    assert p["heading_deg"] == pytest.approx(180, abs=5)


def test_eta_matches_geometry():
    village = VILLAGES["Village A"]
    start = geo.offset_point(village["lat"], village["lon"], 0, 2.0)
    p = predictor.predict_from_track(_straight_track(start, bearing=180, speed_kmh=2.0))
    # (2.0 km - 0.5 km threat radius) / 2 km/h = 45 min
    assert p["will_reach"] is True
    assert p["target_village"] == "Village A"
    assert p["eta_minutes"] == pytest.approx(45, abs=5)


def test_moving_away_never_reaches():
    village = VILLAGES["Village A"]
    start = geo.offset_point(village["lat"], village["lon"], 0, 2.0)
    p = predictor.predict_from_track(_straight_track(start, bearing=0, speed_kmh=2.0))
    assert p["will_reach"] is False
    assert p["eta_minutes"] is None


def test_alert_tiers():
    assert risk.alert_tier("HIGH", True, 10) == "Imminent"
    assert risk.alert_tier("HIGH", True, 40) == "Warning"
    assert risk.alert_tier("MODERATE", True, 40) == "Watch"
    assert risk.alert_tier("CRITICAL", False, None) is None
    assert risk.alert_tier("LOW", True, 400) is None


def test_confirmation_threshold():
    assert risk.needs_confirmation(0.82) is True
    assert risk.needs_confirmation(0.95) is False
