"""Daily risk-zone grid over the study area.

A transparent heuristic (not a trained model): each cell combines
  - proximity to a village (conflict happens where animals meet people),
  - closeness to the forest edge (where animals emerge),
  - a recency-weighted kernel density of past high-risk sightings and reported incidents.
Once you have real conflict records, replace this with a learned model (for example gradient
boosting on terrain, crop and water layers). The API shape can stay the same.
"""

from __future__ import annotations

import time
from datetime import datetime

import numpy as np

from . import db, fusion, geo
from .config import FOREST_CENTER, TIME_FORMAT, VILLAGES

CELL_KM = 0.5
PAD_KM = 2.5
BANDWIDTH_KM = 1.0
HALF_LIFE_DAYS = 14.0
MIN_RISK = 0.12

EVENT_WEIGHT = {"CRITICAL": 1.5, "HIGH": 1.0, "MODERATE": 0.4, "LOW": 0.15}
INCIDENT_WEIGHT = 3.0

_cache: dict = {"at": 0.0, "value": None}


def _level(risk: float) -> str:
    if risk >= 0.6:
        return "HIGH"
    if risk >= 0.35:
        return "MODERATE"
    return "LOW"


def build_zones(now: datetime | None = None) -> dict:
    if now is None:
        cached = _cache["value"]
        if cached is not None and time.time() - _cache["at"] < 20:
            return cached
    now = now or datetime.now()

    lat0, lon0 = FOREST_CENTER["lat"], FOREST_CENTER["lon"]
    village_xy = np.array([geo.to_local_km(v["lat"], v["lon"], lat0, lon0) for v in VILLAGES.values()])
    xs_all = np.concatenate([village_xy[:, 0], [0.0]])
    ys_all = np.concatenate([village_xy[:, 1], [0.0]])
    reach = FOREST_CENTER["radius_m"] / 1000
    x_min, x_max = min(xs_all.min(), -reach) - PAD_KM, max(xs_all.max(), reach) + PAD_KM
    y_min, y_max = min(ys_all.min(), -reach) - PAD_KM, max(ys_all.max(), reach) + PAD_KM

    gx = np.arange(x_min, x_max + CELL_KM, CELL_KM)
    gy = np.arange(y_min, y_max + CELL_KM, CELL_KM)
    cx, cy = np.meshgrid(gx, gy)
    cx, cy = cx.ravel(), cy.ravel()

    # proximity to the nearest village
    d_village = np.min(
        np.sqrt((cx[:, None] - village_xy[:, 0]) ** 2 + (cy[:, None] - village_xy[:, 1]) ** 2), axis=1
    )
    proximity = np.exp(-((d_village / 1.5) ** 2))

    # forest edge
    d_center = np.sqrt(cx ** 2 + cy ** 2)
    edge = np.exp(-(((d_center - reach) / 1.0) ** 2))

    # kernel density of past conflict
    sources = []
    for e in db.list_events(limit=1000):
        weight = EVENT_WEIGHT.get(e.get("risk"), 0.0)
        if weight and e["animal"] != "Unknown":
            sources.append((e["lat"], e["lon"], weight, e["timestamp"]))
    for i in db.list_incidents():
        v = VILLAGES.get(i["village"])
        if v:
            sources.append((v["lat"], v["lon"], INCIDENT_WEIGHT, i["timestamp"]))

    density = np.zeros_like(cx)
    if sources:
        sx, sy, sw = [], [], []
        for lat, lon, weight, ts in sources:
            x, y = geo.to_local_km(lat, lon, lat0, lon0)
            age_days = max((now - datetime.strptime(ts, TIME_FORMAT)).total_seconds() / 86400, 0.0)
            sx.append(x)
            sy.append(y)
            sw.append(weight * 0.5 ** (age_days / HALF_LIFE_DAYS))
        sx, sy, sw = np.array(sx), np.array(sy), np.array(sw)
        d2 = (cx[:, None] - sx) ** 2 + (cy[:, None] - sy) ** 2
        raw = (sw * np.exp(-0.5 * d2 / BANDWIDTH_KM ** 2)).sum(axis=1)
        density = 1 - np.exp(-raw / 4.0)  # squash to 0..1

    risk = 0.45 * proximity + 0.20 * edge + 0.35 * density

    cells = []
    for x, y, r in zip(cx, cy, risk):
        if r >= MIN_RISK:
            lat, lon = geo.from_local_km(float(x), float(y), lat0, lon0)
            cells.append({"lat": round(lat, 5), "lon": round(lon, 5), "risk": round(float(r), 3),
                          "level": _level(float(r))})

    half_lat = CELL_KM / 2 / geo.KM_PER_DEG_LAT
    half_lon = half_lat / np.cos(np.radians(lat0))
    result = {
        "cell_km": CELL_KM,
        "half_lat": round(float(half_lat), 6),
        "half_lon": round(float(half_lon), 6),
        "night": fusion.is_night(now),
        "sources": len(sources),
        "cells": cells,
    }
    _cache["at"], _cache["value"] = time.time(), result
    return result
