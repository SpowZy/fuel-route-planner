"""Measure latency and external calls on real routes between US cities.

    uv run python scripts/bench.py [--routes 12] [--repeat 5]

Each route is planned once with a live routing call (cold) and then repeated from the route
cache (warm). Cold numbers include the public OSRM server, so they vary with its load.
"""

import argparse
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.test import Client  # noqa: E402

CITIES = [
    "New York, NY", "Los Angeles, CA", "Chicago, IL", "Houston, TX", "Phoenix, AZ",
    "Philadelphia, PA", "San Antonio, TX", "Dallas, TX", "Denver, CO", "Seattle, WA",
    "Miami, FL", "Atlanta, GA", "Boston, MA", "Minneapolis, MN", "Kansas City, MO",
    "Nashville, TN", "Salt Lake City, UT", "Las Vegas, NV", "Oklahoma City, OK", "Memphis, TN",
    "Charlotte, NC", "Detroit, MI", "St. Louis, MO", "Omaha, NE", "Albuquerque, NM",
]  # fmt: skip


def percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def row(name, values):
    p50, p95 = statistics.median(values), percentile(values, 0.95)
    return f"| {name} | {p50:.0f} | {p95:.0f} | {max(values):.0f} |"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--routes", type=int, default=12)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()

    random.seed(7)
    pairs = [tuple(random.sample(CITIES, 2)) for _ in range(args.routes)]
    client = Client()
    client.get("/api/v1/health/")  # load the in-memory tables once, as a running server would

    cold, warm_wall, warm_server, corridor, optimize = [], [], [], [], []
    cold_calls, warm_calls, distances, failed = [], [], [], 0
    for start, finish in pairs:
        params = {"start": start, "finish": finish}
        response = client.get("/api/v1/route/", {**params, "nocache": "1"})
        if response.status_code != 200:
            failed += 1
            print(f"skipped {start} -> {finish}: {response.json()['error']['message']}")
            continue
        body = response.json()
        cold.append(body["meta"]["timings_ms"]["total"])
        cold_calls.append(body["meta"]["external_calls"])
        distances.append(body["route"]["distance_miles"])
        for _ in range(args.repeat):
            began = time.perf_counter()
            body = client.get("/api/v1/route/", params).json()
            warm_wall.append((time.perf_counter() - began) * 1000)
            timings = body["meta"]["timings_ms"]
            warm_server.append(timings["total"])
            corridor.append(timings["corridor"])
            optimize.append(timings["optimize"])
            warm_calls.append(body["meta"]["external_calls"])

    span = f"{min(distances):.0f} to {max(distances):.0f} miles"
    print(f"\n{len(cold)} routes planned, {failed} skipped, {span}")
    print("\n| milliseconds | p50 | p95 | max |\n|---|---|---|---|")
    print(row("cold, server total (live routing call)", cold))
    print(row("warm, server total (route cached)", warm_server))
    print(row("warm, whole request incl. Django test client", warm_wall))
    print(row("warm, corridor search", corridor))
    print(row("warm, optimizer", optimize))
    print(f"\nexternal calls per cold request: min {min(cold_calls)}, max {max(cold_calls)}")
    print(f"external calls per warm request: min {min(warm_calls)}, max {max(warm_calls)}")


if __name__ == "__main__":
    main()
