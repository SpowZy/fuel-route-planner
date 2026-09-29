import numpy as np
import pytest
from scipy.spatial import cKDTree

from planner.corridor import stations_along
from planner.geometry import (
    EARTH_RADIUS_MILES,
    Route,
    cumulative_miles,
    decode_polyline,
    densify,
    haversine_miles,
    simplify_indices,
    to_xyz,
)


def line_route(lon_from=-100.0, lon_to=-90.0, lat=40.0, points=11, distance=None):
    lon = np.linspace(lon_from, lon_to, points)
    lat_arr = np.full(points, lat)
    length = float(haversine_miles(lat, lon_from, lat, lon_to))
    return Route.from_points(lat_arr, lon, distance or length, 8.0)


def test_haversine_new_york_to_los_angeles():
    miles = haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
    assert miles == pytest.approx(2445, abs=10)  # great circle, well known


def test_route_positions_are_scaled_to_the_router_distance():
    route = line_route(distance=900.0)
    assert route.cum_miles[-1] == pytest.approx(900.0)
    assert route.point_at(450.0)[1] == pytest.approx(-95.0, abs=0.01)


def test_densify_keeps_spacing_below_the_step():
    route = line_route()
    lat, lon, cum = densify(route, 0.25)
    assert np.diff(cum).max() <= 0.25 + 1e-9
    assert cum[0] == 0 and cum[-1] == pytest.approx(route.distance_miles)
    assert len(lat) == len(lon) == len(cum)


def test_simplify_keeps_the_ends_and_stays_within_tolerance():
    theta = np.linspace(0, np.pi, 400)
    lat, lon = 40 + 0.5 * np.sin(theta), -100 + 2 * theta
    keep = simplify_indices(lat, lon, 0.05)
    assert keep[0] == 0 and keep[-1] == len(lat) - 1
    assert 10 < len(keep) < 400
    # every dropped vertex sits within tolerance of the simplified line
    length = cumulative_miles(lat[keep], lon[keep])[-1]
    line = Route.from_points(lat[keep], lon[keep], length, 1.0)
    dense_lat, dense_lon, _ = densify(line, 0.01)
    dist, _ = cKDTree(to_xyz(dense_lat, dense_lon)).query(to_xyz(lat, lon))
    assert dist.max() * EARTH_RADIUS_MILES < 0.06


def test_decode_polyline_matches_the_published_example():
    lat, lon = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)
    assert lat == pytest.approx([38.5, 40.7, 43.252])
    assert lon == pytest.approx([-120.2, -120.95, -126.453])


def test_corridor_finds_position_and_offset():
    route = line_route()  # along 40N from -100 to -90, about 530 miles
    total = route.distance_miles
    stations = to_xyz(
        np.array([40.0, 40.05, 40.0, 41.0, 40.0]),
        np.array([-95.0, -92.0, -101.0, -95.0, -91.0]),
    )
    corridor = stations_along(route, stations, max_offset_miles=10)
    # station 2 is 1 degree north (69 miles off), station 3 is west of the start
    assert list(corridor.station_rows) == [0, 1, 4]
    assert corridor.mile[0] == pytest.approx(total * 0.5, abs=0.5)
    assert corridor.offset[0] == pytest.approx(0, abs=0.3)
    assert corridor.offset[1] == pytest.approx(3.45, abs=0.3)  # 0.05 degrees of latitude
    assert list(corridor.mile) == sorted(corridor.mile)
