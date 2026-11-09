"""Geographic helpers (distances, bearings, local flat-earth projection)."""

from math import atan2, cos, degrees, radians, sin, sqrt

from .config import VILLAGES

EARTH_RADIUS_KM = 6371.0
KM_PER_DEG_LAT = 111.195

_DIRECTIONS = [
    "North", "North-East", "East", "South-East",
    "South", "South-West", "West", "North-West",
]


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return EARTH_RADIUS_KM * 2 * atan2(sqrt(a), sqrt(1 - a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """Initial bearing from point 1 to point 2, 0-360 degrees clockwise from north."""
    p1, p2 = radians(lat1), radians(lat2)
    dlon = radians(lon2 - lon1)
    x = sin(dlon) * cos(p2)
    y = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dlon)
    return (degrees(atan2(x, y)) + 360) % 360


def bearing_to_direction(bearing: float) -> str:
    return _DIRECTIONS[int((bearing % 360 + 22.5) / 45) % 8]


def angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings (0-180)."""
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def offset_point(lat, lon, bearing: float, dist_km: float):
    """Move dist_km along a bearing (accurate enough at village scale)."""
    b = radians(bearing)
    dlat = dist_km * cos(b) / KM_PER_DEG_LAT
    dlon = dist_km * sin(b) / (KM_PER_DEG_LAT * cos(radians(lat)))
    return lat + dlat, lon + dlon


def to_local_km(lat, lon, lat0, lon0):
    """Equirectangular projection around (lat0, lon0): x = east km, y = north km."""
    x = (lon - lon0) * KM_PER_DEG_LAT * cos(radians(lat0))
    y = (lat - lat0) * KM_PER_DEG_LAT
    return x, y


def from_local_km(x, y, lat0, lon0):
    lat = lat0 + y / KM_PER_DEG_LAT
    lon = lon0 + x / (KM_PER_DEG_LAT * cos(radians(lat0)))
    return lat, lon


def nearest_village(lat, lon, villages=VILLAGES) -> dict:
    best_name, best_dist = None, float("inf")
    for name, loc in villages.items():
        d = haversine_km(lat, lon, loc["lat"], loc["lon"])
        if d < best_dist:
            best_name, best_dist = name, d
    return {"name": best_name, "distance_km": round(best_dist, 2)}
