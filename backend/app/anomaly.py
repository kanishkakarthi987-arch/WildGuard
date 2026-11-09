"""Isolation Forest anomaly detection on movement behaviour.

Flags unusual movement for a species (panicked running, erratic paths, strange
approach angles) relative to the history stored for that species.
"""

from __future__ import annotations

from . import geo
from .predictor import parse_ts

MIN_HISTORY = 15
FEATURES = ("speed_kmh", "rel_heading", "straightness", "distance_km")

_cache: dict = {}


def straightness(track) -> float:
    """Net displacement / path length. 1.0 is a straight line, near 0 is wandering."""
    if not track or len(track) < 3:
        return 1.0
    pts = sorted(track, key=lambda p: p["t"])
    lat0, lon0 = pts[-1]["lat"], pts[-1]["lon"]
    xy = [geo.to_local_km(p["lat"], p["lon"], lat0, lon0) for p in pts]
    path = sum(
        ((xy[i + 1][0] - xy[i][0]) ** 2 + (xy[i + 1][1] - xy[i][1]) ** 2) ** 0.5
        for i in range(len(xy) - 1)
    )
    if path < 1e-9:
        return 1.0
    net = ((xy[-1][0] - xy[0][0]) ** 2 + (xy[-1][1] - xy[0][1]) ** 2) ** 0.5
    return min(net / path, 1.0)


def feature_vector(event: dict):
    try:
        return [float(event[name]) for name in FEATURES]
    except (KeyError, TypeError, ValueError):
        return None


def score_event(event: dict, history: list[dict]) -> dict:
    """Return {"anomaly": bool|None, "anomaly_score": float|None}.

    None means there is not enough history for this species yet.
    """
    species = event.get("animal")
    vector = feature_vector(event)
    rows = [
        v for v in (feature_vector(e) for e in history if e.get("animal") == species)
        if v is not None
    ]
    if vector is None or len(rows) < MIN_HISTORY:
        return {"anomaly": None, "anomaly_score": None}

    from sklearn.ensemble import IsolationForest  # imported lazily: slow to import

    key = (species, len(rows) // 5)
    model = _cache.get(key)
    if model is None:
        model = IsolationForest(n_estimators=100, contamination=0.05, random_state=0)
        model.fit(rows)
        _cache.clear()
        _cache[key] = model

    label = model.predict([vector])[0]
    score = -float(model.decision_function([vector])[0])  # higher = more anomalous
    return {"anomaly": bool(label == -1), "anomaly_score": round(score, 3)}
