"""Movement prediction.

A constant-velocity Kalman filter smooths a noisy GPS/camera track and estimates
velocity. The estimate is projected forward to answer the question that matters:
will the animal come within THREAT_RADIUS_KM of a village, and when?

Units inside the filter: kilometres and hours. State = [x, y, vx, vy].
"""

from __future__ import annotations

from datetime import datetime
from math import atan2, degrees, hypot, sqrt

import numpy as np

from . import geo
from .config import (
    HORIZON_H,
    PATH_HORIZONS_MIN,
    SPECIES_PROFILES,
    THREAT_RADIUS_KM,
    TIME_FORMAT,
    VILLAGES,
)

MEAS_SIGMA_KM = 0.02   # ~20 m GPS / camera-position noise
ACCEL_SIGMA = 0.8      # km/h^2, how quickly an animal changes velocity
MIN_SPEED_KMH = 0.1    # below this the animal is treated as stationary


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def run_kalman(observations, accel_sigma: float = ACCEL_SIGMA):
    """observations: list of (t_hours, x_km, y_km) sorted by time.

    Returns (state[4], covariance[4x4]) at the last observation time.
    """
    t_prev, x0, y0 = observations[0]
    state = np.array([x0, y0, 0.0, 0.0])
    r = MEAS_SIGMA_KM ** 2
    cov = np.diag([r, r, 4.0, 4.0])  # velocity prior: +/- 2 km/h
    H = np.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0]])
    R = np.eye(2) * r
    q = accel_sigma ** 2

    for t, x, y in observations[1:]:
        dt = max(t - t_prev, 1e-6)
        F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
        Q = q * np.array([
            [dt ** 4 / 4, 0, dt ** 3 / 2, 0],
            [0, dt ** 4 / 4, 0, dt ** 3 / 2],
            [dt ** 3 / 2, 0, dt ** 2, 0],
            [0, dt ** 3 / 2, 0, dt ** 2],
        ])
        state = F @ state
        cov = F @ cov @ F.T + Q
        innovation = np.array([x, y]) - H @ state
        S = H @ cov @ H.T + R
        K = cov @ H.T @ np.linalg.inv(S)
        state = state + K @ innovation
        cov = (np.eye(4) - K @ H) @ cov
        t_prev = t
    return state, cov


def time_to_reach(rel_xy, vel_xy, radius_km=THREAT_RADIUS_KM):
    """Hours until |rel + vel*t| == radius, or None if it never gets there in the horizon.

    rel_xy is the animal position relative to the village.
    """
    rx, ry = rel_xy
    vx, vy = vel_xy
    if rx * rx + ry * ry <= radius_km ** 2:
        return 0.0
    a = vx * vx + vy * vy
    if a < 1e-9:
        return None
    b = 2 * (rx * vx + ry * vy)
    c = rx * rx + ry * ry - radius_km ** 2
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    t = (-b - sqrt(disc)) / (2 * a)
    if t < 0 or t > HORIZON_H:
        return None
    return t


def closest_approach(rel_xy, vel_xy):
    """(distance_km, hours) of closest approach in the future."""
    rx, ry = rel_xy
    vx, vy = vel_xy
    a = vx * vx + vy * vy
    t = 0.0 if a < 1e-9 else max(0.0, -(rx * vx + ry * vy) / a)
    return hypot(rx + vx * t, ry + vy * t), t


def track_from_fields(event: dict) -> list[dict]:
    """Fallback for events that carry no track: rebuild a short one from bearing + speed."""
    speed = float(event.get("speed_kmh") or 0.0)
    bearing = float(event.get("bearing") or 0.0)
    end = parse_ts(event["timestamp"])
    back_lat, back_lon = geo.offset_point(event["lat"], event["lon"], (bearing + 180) % 360, speed * 0.5)
    start = end.timestamp() - 1800
    return [
        {"t": datetime.fromtimestamp(start).strftime(TIME_FORMAT), "lat": back_lat, "lon": back_lon},
        {"t": event["timestamp"], "lat": event["lat"], "lon": event["lon"]},
    ]


def estimate_motion(track: list[dict], accel_sigma: float = ACCEL_SIGMA) -> dict:
    """Run the Kalman filter over a track. Independent of any village, so it can be reused."""
    points = sorted(track, key=lambda p: p["t"])
    lat0, lon0 = points[-1]["lat"], points[-1]["lon"]
    t0 = parse_ts(points[0]["t"]).timestamp()
    obs = []
    for p in points:
        x, y = geo.to_local_km(p["lat"], p["lon"], lat0, lon0)
        obs.append(((parse_ts(p["t"]).timestamp() - t0) / 3600.0, x, y))

    state, cov = run_kalman(obs, accel_sigma)
    vel = state[2:]
    speed = float(hypot(vel[0], vel[1]))
    moving = speed >= MIN_SPEED_KMH
    return {
        "lat0": lat0,
        "lon0": lon0,
        "pos": state[:2],
        "vel": vel,
        "moving_vel": vel if moving else np.zeros(2),
        "speed": speed,
        "speed_sigma": float(sqrt(max((cov[2, 2] + cov[3, 3]) / 2, 0.0))),
        "heading": degrees(atan2(vel[0], vel[1])) % 360 if moving else None,
    }


def village_approaches(motion: dict, villages=VILLAGES, radius_km: float = THREAT_RADIUS_KM) -> list[dict]:
    """For each village: distance, hours until the threat radius is reached (or None), closest pass."""
    out = []
    for name, loc in villages.items():
        vx_, vy_ = geo.to_local_km(loc["lat"], loc["lon"], motion["lat0"], motion["lon0"])
        rel = (motion["pos"][0] - vx_, motion["pos"][1] - vy_)
        d_min, _ = closest_approach(rel, motion["moving_vel"])
        out.append({
            "village": name,
            "distance_km": hypot(*rel),
            "eta_h": time_to_reach(rel, motion["moving_vel"], radius_km),
            "closest_km": d_min,
        })
    return out


def predict_from_track(
    track: list[dict],
    villages=VILLAGES,
    radius_km: float = THREAT_RADIUS_KM,
    accel_sigma: float = ACCEL_SIGMA,
) -> dict:
    motion = estimate_motion(track, accel_sigma)
    pos, moving_vel = motion["pos"], motion["moving_vel"]
    lat0, lon0 = motion["lat0"], motion["lon0"]
    heading = motion["heading"]

    cur_lat, cur_lon = geo.from_local_km(pos[0], pos[1], lat0, lon0)
    path = []
    for minutes in PATH_HORIZONS_MIN:
        p = pos + moving_vel * (minutes / 60.0)
        lat, lon = geo.from_local_km(p[0], p[1], lat0, lon0)
        path.append({"minutes": minutes, "lat": round(lat, 6), "lon": round(lon, 6)})

    approaches = village_approaches(motion, villages, radius_km)
    reaching = [a for a in approaches if a["eta_h"] is not None]
    if reaching:
        target = min(reaching, key=lambda a: a["eta_h"])
    else:
        target = min(approaches, key=lambda a: a["distance_km"])
    nearest = min(approaches, key=lambda a: a["distance_km"])

    return {
        "lat": round(cur_lat, 6),
        "lon": round(cur_lon, 6),
        "speed_kmh": round(motion["speed"], 2),
        "speed_sigma_kmh": round(motion["speed_sigma"], 2),
        "heading_deg": None if heading is None else round(heading, 1),
        "direction": None if heading is None else geo.bearing_to_direction(heading),
        "path": path,
        "will_reach": bool(reaching),
        "target_village": target["village"],
        "eta_minutes": None if target["eta_h"] is None else int(round(target["eta_h"] * 60)),
        "closest_approach_km": round(target["closest_km"], 2),
        "nearest_village": nearest["village"],
        "nearest_distance_km": round(nearest["distance_km"], 2),
    }


def predict_event(event: dict) -> dict:
    track = event.get("track")
    if not track or len(track) < 2:
        track = track_from_fields(event)
    profile = SPECIES_PROFILES.get(event.get("animal"), SPECIES_PROFILES["Unknown"])
    return predict_from_track(track, radius_km=profile["threat_radius_km"], accel_sigma=profile["accel_sigma"])
