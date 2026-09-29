"""Turn what the caller typed into coordinates.

Accepted, in the order they are tried:
  "40.7128,-74.0060"        coordinates, no external call
  "Dallas, TX" / "Dallas, Texas"   looked up in the offline Census places table, no external call
  anything else             sent to the Census one-line geocoder (one external call)
"""

from __future__ import annotations

import csv
import gzip
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import requests
from django.conf import settings

from stations.geo import NOT_COVERED, norm_place, parse_state

from .calls import CallLog

# Contiguous United States. Loose on purpose: it catches typos and other continents,
# while the price data (48 states) limits where a plan can actually be built.
LAT_RANGE = (24.3, 49.6)
LON_RANGE = (-125.1, -66.8)

_COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class LocationError(Exception):
    def __init__(self, message: str, code: str = "location_not_found"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Location:
    query: str
    label: str
    lat: float
    lon: float
    source: str  # "coordinates", "places" or "census-geocoder"


@lru_cache(maxsize=1)
def _places() -> dict[tuple[str, str], tuple[str, float, float]]:
    path = Path(settings.BASE_DIR) / "data" / "us_places.csv.gz"
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        rows = csv.reader(handle)
        next(rows)  # key, name, state, lat, lon
        return {(key, state): (name, float(lat), float(lon)) for key, name, state, lat, lon in rows}


@lru_cache(maxsize=1)
def _places_by_state() -> dict[str, list[tuple[str, tuple[str, float, float]]]]:
    by_state = defaultdict(list)
    for (key, state), value in _places().items():
        by_state[state].append((key, value))
    return by_state


def _lookup(city: str, state: str):
    """Exact name first; else the one place whose name starts with it ("Boise" for "Boise City")."""
    key = norm_place(city)
    hit = _places().get((key, state))
    if hit:
        return hit
    matches = {value[0]: value for k, value in _places_by_state()[state] if k.startswith(key + " ")}
    return next(iter(matches.values())) if len(matches) == 1 else None


def warm_places() -> int:
    _places_by_state()
    return len(_places())


def _check_in_us(lat: float, lon: float, query: str) -> None:
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
        raise LocationError(
            f"'{query}' is outside the 48 contiguous states this service covers",
            "outside_coverage",
        )


def resolve_location(text: str, log: CallLog) -> Location:
    query = text.strip()
    match = _COORDINATES.match(query)
    if match:
        lat, lon = float(match.group(1)), float(match.group(2))
        _check_in_us(lat, lon, query)
        return Location(query, f"{lat:.4f}, {lon:.4f}", lat, lon, "coordinates")

    parts = [
        p.strip() for p in re.sub(r",?\s*(USA|US|United States)$", "", query, flags=re.I).split(",")
    ]
    if len(parts) == 2 and parts[0]:
        state = parse_state(parts[1])
        if state in NOT_COVERED:
            raise LocationError(
                f"'{query}' is outside the 48 contiguous states this service covers",
                "outside_coverage",
            )
        if state:
            hit = _lookup(parts[0], state)
            if hit:
                name, lat, lon = hit
                return Location(query, f"{parts[0].title()}, {state}", lat, lon, "places")
    return _census(query, log)


def _census(query: str, log: CallLog) -> Location:
    started = time.perf_counter()
    try:
        response = requests.get(
            "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
            params={"address": query, "benchmark": "Public_AR_Current", "format": "json"},
            headers={"User-Agent": settings.ROUTING["USER_AGENT"]},
            timeout=15,
        )
        matches = response.json()["result"]["addressMatches"]
    except (requests.RequestException, ValueError, KeyError) as error:
        log.record("census-geocoder", started, f"error: {type(error).__name__}")
        raise LocationError(
            f"Could not look up '{query}'. Use 'City, ST' or 'lat,lon'.", "geocoder_unavailable"
        ) from error
    log.record("census-geocoder", started, f"{len(matches)} matches")
    if not matches:
        raise LocationError(f"No US location found for '{query}'. Use 'City, ST' or 'lat,lon'.")
    lat, lon = matches[0]["coordinates"]["y"], matches[0]["coordinates"]["x"]
    _check_in_us(lat, lon, query)
    return Location(query, matches[0]["matchedAddress"].title(), lat, lon, "census-geocoder")
