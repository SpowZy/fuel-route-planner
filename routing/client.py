"""Driving routes from a public routing service: one call per trip, then cached.

OSRM's public server is the primary. If it fails or times out, Valhalla's public server is
tried once. Results are cached by start and end rounded to about 100 meters, and a few demo
routes ship as snapshots so the demo works offline.
"""

from __future__ import annotations

import gzip
import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from django.conf import settings
from django.core.cache import cache

from planner.geometry import METERS_PER_MILE, Route, decode_polyline

from .calls import CallLog

Point = tuple[float, float]  # (lat, lon)
MAP_TOLERANCE_MILES = 0.05  # drawn line stays within about 80 m of the driven route

_throttle_lock = threading.Lock()
_last_request = 0.0


class RoutingError(Exception):
    """The routing services could not produce a route."""

    def __init__(self, message: str, code: str = "routing_unavailable", status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class RouteResult:
    route: Route
    provider: str
    source: str  # "osrm", "valhalla", "cache" or "snapshot"


def route_key(origin: Point, destination: Point) -> str:
    return f"route:v1:{origin[0]:.3f},{origin[1]:.3f};{destination[0]:.3f},{destination[1]:.3f}"


def snapshot_path(key: str) -> Path:
    slug = re.sub(r"[^0-9a-z.-]+", "_", key.removeprefix("route:v1:").lower())
    return Path(settings.ROUTING["SNAPSHOT_DIR"]) / f"{slug}.json.gz"


def get_route(
    origin: Point, destination: Point, log: CallLog, use_cache: bool = True
) -> RouteResult:
    key = route_key(origin, destination)
    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            return RouteResult(cached[0], cached[1], "cache")
        snapshot = snapshot_path(key)
        if snapshot.exists():
            payload = json.loads(gzip.decompress(snapshot.read_bytes()))
            route = parse_osrm(payload)
            _store(key, route, "osrm")
            return RouteResult(route, "osrm", "snapshot")

    try:
        route, raw = fetch_osrm(origin, destination, log)
        provider = "osrm"
    except RoutingError as error:
        if error.code == "no_route":
            raise
        route, raw = fetch_valhalla(origin, destination, log)
        provider = "valhalla"
    _store(key, route, provider)
    return RouteResult(route, provider, provider)


def save_snapshot(origin: Point, destination: Point, log: CallLog) -> Path:
    """Fetch a route from OSRM and write it where get_route will find it offline."""
    _, raw = fetch_osrm(origin, destination, log)
    path = snapshot_path(route_key(origin, destination))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(raw, separators=(",", ":")).encode()))
    return path


def _store(key: str, route: Route, provider: str) -> None:
    cache.set(key, (route, provider), settings.ROUTING["CACHE_SECONDS"])


def _wait_turn() -> None:
    """Keep to the public server's one-request-per-second limit across threads."""
    global _last_request
    with _throttle_lock:
        pause = settings.ROUTING["MIN_INTERVAL_SECONDS"] - (time.monotonic() - _last_request)
        if pause > 0:
            time.sleep(pause)
        _last_request = time.monotonic()


def _headers() -> dict:
    return {"User-Agent": settings.ROUTING["USER_AGENT"]}


def fetch_osrm(origin: Point, destination: Point, log: CallLog) -> tuple[Route, dict]:
    cfg = settings.ROUTING
    url = (
        f"{cfg['OSRM_URL']}/route/v1/driving/"
        f"{origin[1]:.6f},{origin[0]:.6f};{destination[1]:.6f},{destination[0]:.6f}"
    )
    params = {
        "overview": "full",
        "geometries": "geojson",
        "alternatives": "false",
        "steps": "false",
    }
    last_error = "no response"
    for _attempt in range(2):
        _wait_turn()
        started = time.perf_counter()
        try:
            response = requests.get(
                url, params=params, headers=_headers(), timeout=cfg["TIMEOUT_SECONDS"]
            )
        except requests.RequestException as error:
            log.record("osrm", started, f"error: {type(error).__name__}")
            last_error = type(error).__name__
            continue
        log.record("osrm", started, f"HTTP {response.status_code}")
        if response.status_code == 200:
            payload = response.json()
            if payload.get("code") == "NoRoute":
                raise RoutingError("No drivable route between these points", "no_route", 422)
            return parse_osrm(payload), payload
        last_error = f"HTTP {response.status_code}"
        if response.status_code < 500 and response.status_code != 429:
            break
    raise RoutingError(f"OSRM failed ({last_error})")


def parse_osrm(payload: dict) -> Route:
    if payload.get("code") == "NoRoute" or not payload.get("routes"):
        raise RoutingError("No drivable route between these points", "no_route", 422)
    best = payload["routes"][0]
    coordinates = best["geometry"]["coordinates"]  # [lon, lat]
    lon = [c[0] for c in coordinates]
    lat = [c[1] for c in coordinates]
    route = Route.from_points(lat, lon, best["distance"] / METERS_PER_MILE, best["duration"] / 3600)
    return route.with_map_indices(MAP_TOLERANCE_MILES)


def fetch_valhalla(origin: Point, destination: Point, log: CallLog) -> tuple[Route, dict]:
    cfg = settings.ROUTING
    body = {
        "locations": [
            {"lat": origin[0], "lon": origin[1]},
            {"lat": destination[0], "lon": destination[1]},
        ],
        "costing": "auto",
        "units": "miles",
    }
    started = time.perf_counter()
    try:
        response = requests.post(
            f"{cfg['VALHALLA_URL']}/route",
            json=body,
            headers=_headers(),
            timeout=cfg["TIMEOUT_SECONDS"],
        )
    except requests.RequestException as error:
        log.record("valhalla", started, f"error: {type(error).__name__}")
        raise RoutingError("Routing services are unavailable, try again shortly") from error
    log.record("valhalla", started, f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise RoutingError(
            f"Routing services are unavailable (Valhalla HTTP {response.status_code})"
        )
    trip = response.json()["trip"]
    lat, lon = decode_polyline(trip["legs"][0]["shape"], precision=6)
    summary = trip["summary"]
    route = Route.from_points(lat, lon, summary["length"], summary["time"] / 3600)
    return route.with_map_indices(MAP_TOLERANCE_MILES), trip
