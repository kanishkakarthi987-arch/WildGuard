"""Shared analysis: turn a track plus context into a fully scored event, and send its alert.

Every input path (simulator, camera, collar, ground sensor) ends up here, so they all get the
same prediction, risk scoring, tiering, confirmation rule, and de-duplication.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import anomaly, db, fusion, geo, notify, predictor, risk
from .config import (
    RECENT_WINDOW_MIN,
    SPECIES_PROFILES,
    TIME_FORMAT,
    VILLAGES,
)


def profile_for(species: str) -> dict:
    return SPECIES_PROFILES.get(species, SPECIES_PROFILES["Unknown"])


def movement_label(rel_heading: float | None) -> str:
    if rel_heading is None:
        return "Stationary"
    if rel_heading < 45:
        return "Toward Village"
    if rel_heading > 135:
        return "Away From Village"
    return "Parallel To Boundary"


def assemble_event(
    *,
    species: str,
    track: list[dict],
    confidence: float,
    device_id: str,
    source: str,
    ts: datetime,
    sensor_activity: str,
    sensor_data: dict,
    history: list[dict],
    location: str,
    historical: bool = False,
    simulation: bool = True,
    track_id: str | None = None,
    extra: dict | None = None,
):
    """Analyse a track and return (event, prediction). Nothing is stored here."""
    profile = profile_for(species)
    prediction = predictor.predict_from_track(
        track, radius_km=profile["threat_radius_km"], accel_sigma=profile["accel_sigma"]
    )

    est_heading = prediction["heading_deg"]
    cur_lat, cur_lon = prediction["lat"], prediction["lon"]
    near = geo.nearest_village(cur_lat, cur_lon)
    near_loc = VILLAGES[near["name"]]
    bearing_to_near = geo.bearing_deg(cur_lat, cur_lon, near_loc["lat"], near_loc["lon"])
    rel_heading = None if est_heading is None else geo.angle_diff(est_heading, bearing_to_near)

    window_start = ts - timedelta(minutes=RECENT_WINDOW_MIN)
    recent_count = sum(
        1
        for e in history
        if e["animal"] == species
        and e.get("track_id") != track_id  # a track is one animal, not repeated sightings
        and window_start <= datetime.strptime(e["timestamp"], TIME_FORMAT) <= ts
    )

    score, level = risk.calculate_risk(
        distance_km=near["distance_km"],
        confidence=confidence,
        sensor_activity=sensor_activity,
        recent_count=recent_count,
        approaching=prediction["will_reach"],
        night_bonus=profile["night_bonus"] if fusion.is_night(ts) else 0,
    )
    heading_unknown = est_heading is None and not prediction["will_reach"]
    tier = risk.alert_tier(
        level,
        prediction["will_reach"],
        prediction["eta_minutes"],
        heading_unknown=heading_unknown,
        distance_km=near["distance_km"],
    )

    if historical:
        verification = "historical"
    elif tier is None:
        verification = "n/a"
    elif risk.needs_confirmation(confidence):
        verification = "pending"
    else:
        verification = "auto"

    event = {
        "animal": species,
        "lat": prediction["lat"],
        "lon": prediction["lon"],
        "location": location,
        "confidence": round(confidence, 2),
        "risk": level,
        "risk_score": score,
        "timestamp": ts.strftime(TIME_FORMAT),
        "camera_id": device_id,
        "source": source,
        "direction": prediction["direction"] or "Stationary",
        "bearing": est_heading,
        "speed_kmh": prediction["speed_kmh"],
        "distance_km": near["distance_km"],
        "nearest_village": near["name"],
        "movement": movement_label(rel_heading),
        "rel_heading": None if rel_heading is None else round(rel_heading, 1),
        "straightness": round(anomaly.straightness(track), 3),
        "will_reach": prediction["will_reach"],
        "target_village": prediction["target_village"],
        "eta_minutes": prediction["eta_minutes"],
        "alert_tier": tier,
        "verification": verification,
        "sensor_data": sensor_data,
        "track": track,
        "track_id": track_id,
        "simulation": simulation,
    }
    if extra:
        event.update(extra)
    event.update(anomaly.score_event(event, history))
    return event, prediction


def alert_for(event_id: int, event: dict, when: datetime | None = None):
    """Send the tiered alert for a stored event. Returns the notification record or None."""
    tier = event.get("alert_tier")
    if not tier:
        return None
    return notify.dispatch(
        event_id,
        event,
        tier,
        event["target_village"],
        event.get("eta_minutes"),
        event["distance_km"],
        when=when,
    )
