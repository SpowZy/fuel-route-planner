from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pytest
import requests
from rest_framework.test import APIClient

from planner.geometry import cumulative_miles

from .conftest import FakeResponse, make_station

URL = "/api/v1/route/"
TRIP = {"start": "40.0,-100.0", "finish": "40.0,-85.0"}  # about 795 miles


@pytest.fixture
def client():
    return APIClient()


def cents(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def encode_polyline(lat, lon, precision=6):
    """Encode vertices the way Valhalla does, to feed the fallback path."""
    factor = 10**precision
    out, prev_lat, prev_lon = [], 0, 0
    for la, lo in zip(lat, lon, strict=True):
        cur_lat, cur_lon = round(la * factor), round(lo * factor)
        for delta in (cur_lat - prev_lat, cur_lon - prev_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev_lat, prev_lon = cur_lat, cur_lon
    return "".join(out)


def test_plan_is_consistent_and_within_range(client, line_stations, fake_osrm):
    response = client.get(URL, TRIP)
    assert response.status_code == 200
    body = response.json()

    assert body["route"]["distance_miles"] == pytest.approx(795, abs=5)
    stops = body["fuel_stops"]
    assert stops, "a 795 mile trip on a 500 mile tank needs at least one stop"

    # the bill adds up from the numbers on display
    assert sum(cents(s["cost_usd"]) for s in stops) == cents(body["totals"]["fuel_cost_usd"])
    for stop in stops:
        assert cents(stop["gallons_purchased"] * stop["price_per_gallon"]) == cents(
            stop["cost_usd"]
        )
        assert stop["tank_gallons_before"] >= -0.001
        assert stop["tank_gallons_after"] <= body["vehicle"]["tank_gallons"] + 0.001

    # never more than 500 miles between fills, start to first stop and last stop to finish
    marks = [0.0, *[s["mile_marker"] for s in stops], body["route"]["distance_miles"]]
    assert max(np.diff(marks)) <= 500 + 1e-6
    assert body["totals"]["savings_vs_baseline_usd"] >= 0

    assert body["meta"]["external_calls"] == 1 and len(fake_osrm) == 1
    assert "Server-Timing" in response
    kinds = [f["properties"]["kind"] for f in body["map"]["geojson"]["features"]]
    assert kinds.count("route") == 1 and kinds.count("fuel_stop") == len(stops)


def test_second_request_is_served_from_cache(client, line_stations, fake_osrm):
    first = client.get(URL, TRIP).json()
    second = client.get(URL, TRIP).json()
    assert first["meta"]["routing"]["source"] == "osrm"
    assert second["meta"]["routing"]["source"] == "cache"
    assert second["meta"]["external_calls"] == 0
    assert len(fake_osrm) == 1
    assert first["fuel_stops"] == second["fuel_stops"]


def test_nocache_forces_a_live_call(client, line_stations, fake_osrm):
    client.get(URL, TRIP)
    body = client.get(URL, {**TRIP, "nocache": "1"}).json()
    assert body["meta"]["external_calls"] == 1 and len(fake_osrm) == 2


def test_short_trip_needs_no_stop(client, line_stations, fake_osrm):
    body = client.get(URL, {"start": "40.0,-100.0", "finish": "40.0,-92.0"}).json()
    assert body["fuel_stops"] == []
    assert body["totals"]["fuel_cost_usd"] == 0
    assert body["summary"].startswith("No stop needed")


def test_post_accepts_vehicle_overrides(client, line_stations, fake_osrm):
    response = client.post(URL, {**TRIP, "range_miles": 400, "mpg": 8}, format="json")
    vehicle = response.json()["vehicle"]
    assert vehicle["range_miles"] == 400 and vehicle["mpg"] == 8 and vehicle["tank_gallons"] == 50


def test_stop_penalty_zero_buys_at_more_stations(client, line_stations, fake_osrm):
    default = client.get(URL, TRIP).json()
    fuel_only = client.get(URL, {**TRIP, "stop_penalty_usd": 0}).json()
    assert len(fuel_only["fuel_stops"]) >= len(default["fuel_stops"])
    assert fuel_only["totals"]["fuel_cost_usd"] <= default["totals"]["fuel_cost_usd"] + 1e-9


@pytest.mark.parametrize(
    "params, status, code",
    [
        ({"start": "40.0,-100.0"}, 400, "invalid_request"),
        ({"start": "40.0,-100.0", "finish": "40.0,-100.0"}, 422, "same_location"),
        ({"start": "Anchorage, AK", "finish": "40.0,-100.0"}, 422, "outside_coverage"),
        ({**TRIP, "mpg": 0}, 400, "invalid_request"),
    ],
)
def test_bad_requests_get_one_error_shape(client, line_stations, fake_osrm, params, status, code):
    response = client.get(URL, params)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_a_gap_wider_than_the_tank_is_reported_not_faked(client, db, fake_osrm):
    make_station(1, -99.0)  # about 53 miles in, then nothing for 740 miles
    response = client.get(URL, TRIP)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "no_fuel_within_range" and error["gap"]["from_mile"] > 500


def test_osrm_failure_falls_back_to_valhalla(client, line_stations, monkeypatch):
    lon = np.linspace(-100.0, -85.0, 31)
    lat = np.full_like(lon, 40.0)
    miles = float(cumulative_miles(lat, lon)[-1])
    trip = {
        "legs": [{"shape": encode_polyline(lat, lon)}],
        "summary": {"length": miles, "time": miles / 60 * 3600},
    }

    def down(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("routing.client.requests.get", down)
    monkeypatch.setattr(
        "routing.client.requests.post", lambda *a, **k: FakeResponse({"trip": trip})
    )

    body = client.get(URL, TRIP).json()
    assert body["meta"]["routing"]["provider"] == "valhalla"
    assert [c["service"] for c in body["meta"]["calls"]] == ["osrm", "osrm", "valhalla"]
    assert body["meta"]["external_calls"] == 3
    assert body["route"]["distance_miles"] == pytest.approx(miles, abs=1)


def test_health_reports_loaded_stations(client, line_stations):
    body = client.get("/api/v1/health/").json()
    assert body == {"status": "ok", "stations_with_coordinates": 5}
