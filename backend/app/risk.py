"""Risk scoring and alert-tier policy."""

from . import config
from .config import CONFIRM_THRESHOLD

TIER_RANK = {"Watch": 1, "Warning": 2, "Imminent": 3}


def calculate_risk(distance_km, confidence, sensor_activity, recent_count, approaching, night_bonus=0):
    """Return (score 0-100, level). Weights are heuristic and meant to be tuned."""
    score = 0

    # proximity to the nearest village (halved if the animal is not heading in:
    # being close while moving away is much less dangerous)
    if distance_km < 0.5:
        proximity = 40
    elif distance_km < 1.5:
        proximity = 30
    elif distance_km < 3:
        proximity = 18
    else:
        proximity = 8
    score += proximity if approaching else proximity // 2

    # detector confidence
    score += int(confidence * 20)

    # ground-sensor activity
    if sensor_activity == "HIGH":
        score += 15
    elif sensor_activity == "MEDIUM":
        score += 8

    # repeated recent sightings of the species
    score += min(recent_count * 3, 12)

    # predicted to reach a village
    if approaching:
        score += 15

    # species-specific night activity (elephants raid crops at night)
    score += night_bonus

    score = min(score, 100)

    if score >= 80:
        level = "CRITICAL"
    elif score >= 61:
        level = "HIGH"
    elif score >= 31:
        level = "MODERATE"
    else:
        level = "LOW"
    return score, level


def alert_tier(risk_level, will_reach, eta_minutes, heading_unknown=False, distance_km=None):
    """Watch / Warning / Imminent, or None when no village is threatened.

    A single sighting has no heading. If it is close to a village we cannot rule out an
    approach, so it gets a Watch (which still needs a ranger when confidence is low).
    """
    if not will_reach or eta_minutes is None:
        if heading_unknown and distance_km is not None and distance_km <= config.UNKNOWN_HEADING_WATCH_KM:
            return "Watch"
        return None
    if eta_minutes <= 15:
        return "Imminent"
    if eta_minutes <= 60 and risk_level in ("HIGH", "CRITICAL"):
        return "Warning"
    if eta_minutes <= 180:
        return "Watch"
    return None


def needs_confirmation(confidence):
    """Low-confidence detections wait for a ranger before any SMS goes out."""
    return confidence < CONFIRM_THRESHOLD
