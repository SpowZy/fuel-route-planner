"""One trip plan, end to end: resolve places, route, find stations, optimize, describe."""

from __future__ import annotations

import time
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlencode

import numpy as np
from django.conf import settings

from planner.baseline import baseline_cost
from planner.corridor import stations_along
from planner.optimizer import plan_fuel
from routing.calls import CallLog
from routing.client import get_route
from routing.locations import resolve_location
from stations.index import get_index
from stations.models import Station

CENT = Decimal("0.01")
MILLI = Decimal("0.001")


class Timings:
    def __init__(self) -> None:
        self.ms: dict[str, float] = {}
        self._start = time.perf_counter()

    @contextmanager
    def stage(self, name: str):
        started = time.perf_counter()
        yield
        self.ms[name] = round((time.perf_counter() - started) * 1000, 1)

    def finish(self) -> dict[str, float]:
        return {**self.ms, "total": round((time.perf_counter() - self._start) * 1000, 1)}


def _money(gallons: float, price: float) -> tuple[Decimal, Decimal, Decimal]:
    """Round the displayed numbers first, then multiply, so a reader can redo the sum."""
    g = Decimal(str(gallons)).quantize(MILLI, ROUND_HALF_UP)
    p = Decimal(str(round(price, 4)))
    return g, p, (g * p).quantize(CENT, ROUND_HALF_UP)


def plan_trip(params: dict, log: CallLog, base_url: str = "") -> tuple[dict, dict]:
    cfg = settings.FUEL
    timings = Timings()

    range_miles = params.get("range_miles") or cfg["RANGE_MILES"]
    mpg = params.get("mpg") or cfg["MPG"]
    tank_gallons = range_miles / mpg
    start_gallons = min(params.get("start_fuel_gallons", tank_gallons), tank_gallons)
    reserve = params.get("reserve_miles", 0.0)
    stop_penalty = params.get("stop_penalty_usd", cfg["STOP_PENALTY_USD"])
    max_offset = params.get("max_offset_miles") or cfg["MAX_OFFSET_MILES"]
    free_offset = min(cfg["FREE_OFFSET_MILES"], max_offset)

    with timings.stage("resolve"):
        start = resolve_location(params["start"], log)
        finish = resolve_location(params["finish"], log)
    with timings.stage("routing"):
        result = get_route(
            (start.lat, start.lon),
            (finish.lat, finish.lon),
            log,
            use_cache=not params.get("nocache"),
        )
    route = result.route

    index = get_index()
    with timings.stage("corridor"):
        corridor = stations_along(route, index.xyz, max_offset)
    price = index.price[corridor.station_rows]
    detour = 2 * cfg["CIRCUITY"] * np.maximum(0.0, corridor.offset - free_offset)

    planning = {
        "range_miles": range_miles,
        "mpg": mpg,
        "start_range": start_gallons * mpg,
        "reserve": reserve,
    }
    with timings.stage("optimize"):
        plan = plan_fuel(
            route.distance_miles,
            corridor.mile,
            price,
            detour,
            stop_penalty=stop_penalty,
            **planning,
        )
        baseline = baseline_cost(route.distance_miles, corridor.mile, price, detour, **planning)

    with timings.stage("describe"):
        payload = _describe(
            params, start, finish, result, plan, baseline, corridor, index, tank_gallons,
            start_gallons, range_miles, mpg, max_offset, free_offset, stop_penalty, log, base_url,
        )  # fmt: skip
    payload["meta"]["timings_ms"] = timings.finish()
    return payload, payload["meta"]["timings_ms"]


def _describe(
    params, start, finish, result, plan, baseline, corridor, index, tank_gallons,
    start_gallons, range_miles, mpg, max_offset, free_offset, stop_penalty, log, base_url,
) -> dict:  # fmt: skip
    route = result.route
    stations = Station.objects.in_bulk(
        [int(index.pk[corridor.station_rows[s.index]]) for s in plan.stops]
    )

    stops, total_cost, total_gallons = [], Decimal("0"), Decimal("0")
    for order, stop in enumerate(plan.stops, 1):
        row = corridor.station_rows[stop.index]
        station = stations[int(index.pk[row])]
        gallons, price, cost = _money(stop.gallons, stop.price)
        total_cost += cost
        total_gallons += gallons
        last = order == len(plan.stops)
        nxt = route.distance_miles if last else plan.stops[order].mile
        if stop.tank_after >= tank_gallons - 0.05:
            decision = "fills the tank: nothing cheaper within range ahead"
        elif last:
            decision = "buys just enough to reach the destination"
        elif plan.stops[order].price < stop.price:
            decision = f"buys only what reaches mile {nxt:.0f}, where fuel is cheaper"
        else:
            decision = f"buys only what reaches the next stop at mile {nxt:.0f}"
        stops.append(
            {
                "order": order,
                "station": {
                    "id": station.opis_id,
                    "name": station.name,
                    "address": station.address,
                    "city": station.city,
                    "state": station.state,
                    "country": station.country,
                    "latitude": round(station.latitude, 5),
                    "longitude": round(station.longitude, 5),
                    "location_precision": "city",
                },
                "mile_marker": round(stop.mile, 1),
                "offset_miles": round(float(corridor.offset[stop.index]), 1),
                "detour_miles": round(stop.detour_miles, 1),
                "price_per_gallon": float(price),
                "gallons_purchased": float(gallons),
                "cost_usd": float(cost),
                "tank_gallons_before": round(stop.tank_before, 2),
                "tank_gallons_after": round(stop.tank_after, 2),
                "miles_to_next_stop": round(nxt - stop.mile, 1),
                "decision": decision,
            }
        )

    keep = route.map_indices
    line = np.round(np.column_stack((route.lon[keep], route.lat[keep])), 5).tolist()
    features = [
        {
            "type": "Feature",
            "properties": {"kind": "route"},
            "geometry": {"type": "LineString", "coordinates": line},
        },
        _point("start", start.label, start.lon, start.lat),
        _point("finish", finish.label, finish.lon, finish.lat),
    ]
    for stop in stops:
        s = stop["station"]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "fuel_stop", "order": stop["order"], "name": s["name"],
                    "price_per_gallon": stop["price_per_gallon"],
                    "gallons_purchased": stop["gallons_purchased"], "cost_usd": stop["cost_usd"],
                },
                "geometry": {"type": "Point", "coordinates": [s["longitude"], s["latitude"]]},
            }
        )  # fmt: skip

    burned = round(plan.gallons_burned, 3)
    baseline_usd = (
        None if baseline is None else float(Decimal(str(baseline)).quantize(CENT, ROUND_HALF_UP))
    )
    savings = None if baseline_usd is None else round(baseline_usd - float(total_cost), 2)
    if stops:
        summary = (
            f"{len(stops)} fuel stop{'s' if len(stops) > 1 else ''}, ${total_cost:,.2f} for "
            f"{total_gallons:,.1f} gallons over {route.distance_miles:,.0f} miles"
        )
    else:
        summary = (
            f"No stop needed: the starting tank ({start_gallons:.0f} gal) covers "
            f"{route.distance_miles:,.0f} miles, so nothing is bought at the pump"
        )

    strategy = settings.FUEL["PRICE_STRATEGY"]
    query = urlencode({"start": params["start"], "finish": params["finish"]})
    return {
        "summary": summary,
        "start": _place(start),
        "finish": _place(finish),
        "vehicle": {
            "range_miles": range_miles,
            "mpg": mpg,
            "tank_gallons": round(tank_gallons, 2),
            "start_fuel_gallons": round(start_gallons, 2),
        },
        "route": {
            "distance_miles": round(route.distance_miles, 1),
            "duration_hours": round(route.duration_hours, 2),
            "geometry": {"type": "LineString", "coordinates": line},
        },
        "fuel_stops": stops,
        "totals": {
            "fuel_cost_usd": float(total_cost),
            "gallons_purchased": float(total_gallons),
            "gallons_burned": burned,
            "stops": len(stops),
            "average_price_per_gallon": (
                round(float(total_cost / total_gallons), 4) if total_gallons else None
            ),
            "baseline_cost_usd": baseline_usd,
            "savings_vs_baseline_usd": savings,
            "baseline": "drive to the farthest reachable station, fill the tank, repeat",
        },
        "map": {
            "url": f"{base_url}?{query}",
            "geojson": {"type": "FeatureCollection", "features": features},
        },
        "meta": {
            "external_calls": len(log),
            "calls": log.calls,
            "routing": {"provider": result.provider, "source": result.source},
            "candidates_in_corridor": len(corridor),
            "stations_loaded": len(index),
            "assumptions": [
                "Stations sit at their city centroid: the price file has addresses like "
                "'I-44, EXIT 283' and no coordinates.",
                f"A station with several rows in the price file uses the {strategy} price.",
                f"The truck starts with {start_gallons:.0f} of {tank_gallons:.0f} gallons and "
                "may arrive with an empty tank.",
                f"Stations up to {free_offset:.0f} miles from the route count as on the route; "
                f"up to {max_offset:.0f} miles are allowed and pay for the round trip.",
                "Total cost is what is paid at the pump, detour fuel included.",
                f"Stops are chosen as if each cost ${stop_penalty:.0f} of driver time, so the plan "
                "does not stop to save a few cents. Set stop_penalty_usd=0 for fuel price only.",
            ],
        },
    }


def _place(location) -> dict:
    return {
        "query": location.query, "label": location.label, "latitude": round(location.lat, 5),
        "longitude": round(location.lon, 5), "source": location.source,
    }  # fmt: skip


def _point(kind: str, name: str, lon: float, lat: float) -> dict:
    return {
        "type": "Feature",
        "properties": {"kind": kind, "name": name},
        "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
    }
