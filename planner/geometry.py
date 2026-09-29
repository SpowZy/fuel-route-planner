"""Route geometry on the sphere: distances, densification, projection helpers.

Pure numpy, no Django. Stations and route points are compared as unit vectors in 3D, so a
cross-country route has no map-projection distortion: chord length maps exactly to arc length.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

EARTH_RADIUS_MILES = 3958.7613
METERS_PER_MILE = 1609.344


def to_xyz(lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    lat = np.radians(np.asarray(lat_deg, dtype=float))
    lon = np.radians(np.asarray(lon_deg, dtype=float))
    cos_lat = np.cos(lat)
    return np.column_stack((cos_lat * np.cos(lon), cos_lat * np.sin(lon), np.sin(lat)))


def miles_to_chord(miles: float) -> float:
    return 2.0 * math.sin(miles / (2.0 * EARTH_RADIUS_MILES))


def chord_to_miles(chord: np.ndarray) -> np.ndarray:
    return 2.0 * EARTH_RADIUS_MILES * np.arcsin(np.clip(np.asarray(chord) / 2.0, 0.0, 1.0))


def haversine_miles(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def cumulative_miles(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    steps = haversine_miles(lat[:-1], lon[:-1], lat[1:], lon[1:])
    return np.concatenate(([0.0], np.cumsum(steps)))


@dataclass(frozen=True)
class Route:
    """A drivable route: vertices plus the distance the routing service reported."""

    lat: np.ndarray
    lon: np.ndarray
    distance_miles: float
    duration_hours: float
    cum_miles: np.ndarray  # same length as lat, from 0 to distance_miles
    map_indices: np.ndarray | None = None  # vertices kept for drawing, see with_map_indices

    @classmethod
    def from_points(cls, lat, lon, distance_miles: float, duration_hours: float) -> Route:
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
        cum = cumulative_miles(lat, lon)
        if cum[-1] > 0:
            # trust the router's distance; the vertex chain is only used for positions
            cum = cum * (distance_miles / cum[-1])
        return cls(lat, lon, float(distance_miles), float(duration_hours), cum)

    def with_map_indices(self, tolerance_miles: float) -> Route:
        """Simplify once, when the route is fetched, so cached routes cost nothing to draw."""
        return replace(self, map_indices=simplify_indices(self.lat, self.lon, tolerance_miles))

    def point_at(self, mile: float) -> tuple[float, float]:
        return (
            float(np.interp(mile, self.cum_miles, self.lat)),
            float(np.interp(mile, self.cum_miles, self.lon)),
        )


def densify(route: Route, step_miles: float = 0.25) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Insert points so no two consecutive vertices are more than step_miles apart."""
    seg = np.diff(route.cum_miles)
    parts = np.maximum(1, np.ceil(seg / step_miles).astype(int))
    seg_index = np.repeat(np.arange(len(seg)), parts)
    first = np.repeat(np.cumsum(parts) - parts, parts)
    t = (np.arange(parts.sum()) - first) / np.repeat(parts, parts)
    lat = route.lat[seg_index] + t * (route.lat[seg_index + 1] - route.lat[seg_index])
    lon = route.lon[seg_index] + t * (route.lon[seg_index + 1] - route.lon[seg_index])
    cum = route.cum_miles[seg_index] + t * seg[seg_index]
    return (
        np.append(lat, route.lat[-1]),
        np.append(lon, route.lon[-1]),
        np.append(cum, route.cum_miles[-1]),
    )


def simplify_indices(lat: np.ndarray, lon: np.ndarray, tolerance_miles: float) -> np.ndarray:
    """Douglas-Peucker: indices of the vertices to keep so the line stays within tolerance."""
    n = len(lat)
    if n <= 2:
        return np.arange(n)
    lat0 = math.radians(float(np.mean(lat)))
    x = np.radians(lon) * math.cos(lat0) * EARTH_RADIUS_MILES
    y = np.radians(lat) * EARTH_RADIUS_MILES
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        dx, dy = x[j] - x[i], y[j] - y[i]
        px, py = x[i + 1 : j] - x[i], y[i + 1 : j] - y[i]
        length = math.hypot(dx, dy)
        dist = np.hypot(px, py) if length == 0 else np.abs(px * dy - py * dx) / length
        k = int(np.argmax(dist))
        if dist[k] > tolerance_miles:
            mid = i + 1 + k
            keep[mid] = True
            stack.append((i, mid))
            stack.append((mid, j))
    return np.flatnonzero(keep)


def decode_polyline(encoded: str, precision: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """Decode an encoded polyline (Valhalla uses precision 6). Returns (lat, lon)."""
    factor = 10.0**precision
    lat = lon = 0
    coords_lat: list[float] = []
    coords_lon: list[float] = []
    index = 0
    length = len(encoded)
    while index < length:
        for axis in (0, 1):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lon += delta
        coords_lat.append(lat / factor)
        coords_lon.append(lon / factor)
    return np.array(coords_lat), np.array(coords_lon)
