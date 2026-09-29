"""Build the offline geodata the app ships with.

The price file has no coordinates (addresses look like "I-44, EXIT 283 & US-69"), so stations
are placed at the centroid of their city. Two committed outputs come from this script:

  data/us_places.csv.gz      every US place (Census Gazetteer): used to resolve "City, ST" inputs
  data/city_coordinates.csv  one row per (city, state) found in the price file

Run:  uv run python scripts/build_geodata.py [--fallback]
--fallback geocodes the cities the Census file cannot match through Nominatim (1 request per
second, results cached in data/geocode_cache.json).
"""

import argparse
import csv
import gzip
import io
import json
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stations.geo import CA_PROVINCES, US_STATES, norm_place  # noqa: E402

DATA = ROOT / "data"
GAZETTEER_ZIP = DATA / "raw" / "2025_Gaz_place_national.zip"
CACHE_PATH = DATA / "geocode_cache.json"
USER_AGENT = "fuel-route-planner-assessment/0.1"


CONSOLIDATED = re.compile(r"(METROPOLITAN|CONSOLIDATED|UNIFIED) GOVERNMENT|URBAN COUNTY", re.I)
COUSUB_ZIP = DATA / "raw" / "2025_Gaz_cousubs_national.zip"
# Towns and townships (NH, MA, PA, ME...) are county subdivisions, not Census "places".
COUSUB_KINDS = (" town", " township", " borough", " village", " city", " plantation")


def load_places(path: Path = GAZETTEER_ZIP, only_suffixes: tuple[str, ...] = ()) -> dict:
    """Best place per (normalized name, state): incorporated places beat CDPs, then land area."""
    with zipfile.ZipFile(path) as archive:
        text = archive.read(archive.namelist()[0]).decode("utf-8", "replace")
    best: dict[tuple[str, str], tuple[tuple[int, float], str, float, float]] = {}
    for raw in csv.DictReader(io.StringIO(text), delimiter="|"):
        row = {key.strip(): value.strip() for key, value in raw.items()}
        name = row["NAME"]
        if only_suffixes and not name.lower().endswith(only_suffixes):
            continue
        rank = (0 if name.endswith(" CDP") else 1, float(row["ALAND"] or 0))
        # Two keys: "Bay City city" -> BAY CITY, and "Carson City" (no suffix) -> CARSON CITY.
        keys = {norm_place(name, strip_suffix=True), norm_place(name)}
        if CONSOLIDATED.search(name):  # "Nashville-Davidson metropolitan government (balance)"
            keys.add(norm_place(re.split(r"[-/]", name)[0]))
        for key in keys:
            slot = (key, row["USPS"])
            if slot not in best or rank > best[slot][0]:
                best[slot] = (rank, name, float(row["INTPTLAT"]), float(row["INTPTLONG"]))
    return {slot: (name, lat, lon) for slot, (_, name, lat, lon) in best.items()}


def write_places(places) -> None:
    path = DATA / "us_places.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["key", "name", "state", "lat", "lon"])
        for (key, state), (name, lat, lon) in sorted(places.items()):
            writer.writerow([key, name, state, f"{lat:.6f}", f"{lon:.6f}"])
    print(f"wrote {path.name}: {len(places)} places, {path.stat().st_size // 1024} KB")


def unique_cities() -> list[tuple[str, str]]:
    seen = set()
    with open(DATA / "fuel-prices.csv", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            seen.add((row["City"].strip(), row["State"].strip()))
    return sorted(seen)


def prefix_match(places_by_state, key: str, state: str):
    """Accept 'JACUMBA' for 'JACUMBA HOT SPRINGS' only when exactly one place qualifies."""
    hits = {v[0]: v for k, v in places_by_state[state] if k.startswith(key + " ")}
    return next(iter(hits.values())) if len(hits) == 1 else None


def nominatim(city: str, state: str, cache: dict):
    slot = f"{city}|{state}"
    if slot in cache:
        return cache[slot]
    region = CA_PROVINCES.get(state) or US_STATES.get(state)
    country = "ca" if state in CA_PROVINCES else "us"
    result = None
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "city": city,
                "state": region,
                "countrycodes": country,
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        hits = response.json() if response.ok else []
        if hits and hits[0].get("address", {}).get("state", "").upper() == region.upper():
            result = {
                "lat": float(hits[0]["lat"]),
                "lon": float(hits[0]["lon"]),
                "name": hits[0].get("name") or city,
            }
    except (requests.RequestException, ValueError):
        return None  # transient failure: not cached, retried on the next run
    cache[slot] = result
    time.sleep(1.1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fallback", action="store_true", help="geocode unmatched cities with Nominatim"
    )
    args = parser.parse_args()

    places = load_places()
    write_places(places)
    subdivisions = load_places(COUSUB_ZIP, COUSUB_KINDS)
    places_by_state = defaultdict(list)
    for (key, state), value in places.items():
        places_by_state[state].append((key, value))

    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    rows, stats, missing = [], Counter(), []
    for city, state in unique_cities():
        key = norm_place(city)
        hit = places.get((key, state)) if state in US_STATES else None
        source = "census"
        if hit is None and state in US_STATES:
            hit = subdivisions.get((key, state))
            source = "census-subdivision"
        if hit is None and state in US_STATES:
            hit = prefix_match(places_by_state, key, state)
            source = "census-prefix"
        if hit is not None:
            rows.append([city, state, f"{hit[1]:.6f}", f"{hit[2]:.6f}", source, hit[0]])
            stats[source] += 1
        else:
            missing.append((city, state))

    if args.fallback:
        for index, (city, state) in enumerate(missing, 1):
            found = nominatim(city, state, cache)
            if found:
                rows.append(
                    [
                        city,
                        state,
                        f"{found['lat']:.6f}",
                        f"{found['lon']:.6f}",
                        "nominatim",
                        found["name"],
                    ]
                )
                stats["nominatim"] += 1
            else:
                rows.append([city, state, "", "", "unmatched", ""])
                stats["unmatched"] += 1
            if index % 25 == 0:
                CACHE_PATH.write_text(json.dumps(cache, indent=0, sort_keys=True))
                print(f"  fallback {index}/{len(missing)}", flush=True)
        CACHE_PATH.write_text(json.dumps(cache, indent=0, sort_keys=True))
    else:
        for city, state in missing:
            rows.append([city, state, "", "", "unmatched", ""])
            stats["unmatched"] += 1

    rows.sort(key=lambda r: (r[1], r[0]))
    with open(DATA / "city_coordinates.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["city", "state", "lat", "lon", "source", "matched_name"])
        writer.writerows(rows)
    print(f"unique (city, state) pairs: {len(rows)}")
    print("by source:", dict(stats))
    by_country = Counter(
        "CA" if s in CA_PROVINCES else "US" for _, s, *_r in rows if _r[3] == "unmatched"
    )
    print("unmatched by country:", dict(by_country))
    if not args.fallback:
        print("sample unmatched:", missing[:25])


if __name__ == "__main__":
    main()
