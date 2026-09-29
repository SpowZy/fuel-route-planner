import numpy as np
import pytest
from django.conf import settings
from django.core.cache import cache

from planner.geometry import METERS_PER_MILE, cumulative_miles
from stations.index import clear_index
from stations.models import Station


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    """Fresh cache and station index per test, and no artificial pause between routing calls."""
    monkeypatch.setitem(settings.ROUTING, "MIN_INTERVAL_SECONDS", 0)
    cache.clear()
    clear_index()
    yield
    cache.clear()
    clear_index()


def osrm_payload(lat, lon):
    """What OSRM answers for a route along the given vertices."""
    miles = cumulative_miles(np.asarray(lat), np.asarray(lon))[-1]
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": miles * METERS_PER_MILE,
                "duration": miles / 60 * 3600,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[x, y] for x, y in zip(lon, lat, strict=True)],
                },
            }
        ],
    }


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@pytest.fixture
def fake_osrm(monkeypatch):
    """Answer with a straight line between the requested points and record each request."""
    sent = []

    def fake_get(url, params=None, headers=None, timeout=None):
        sent.append(url)
        (lon1, lat1), (lon2, lat2) = (
            (float(v) for v in pair.split(",")) for pair in url.rsplit("/", 1)[1].split(";")
        )
        return FakeResponse(osrm_payload(np.linspace(lat1, lat2, 31), np.linspace(lon1, lon2, 31)))

    monkeypatch.setattr("routing.client.requests.get", fake_get)
    return sent


def make_station(opis_id, lon, lat=40.0, price="3.0000", city="Testville", state="NE"):
    return Station.objects.create(
        opis_id=opis_id, name=f"STOP {opis_id}", address="I-80, EXIT 1", city=city, state=state,
        country="US", rack_id=1, price=price, price_min=price, price_max=price, price_rows=1,
        latitude=lat, longitude=lon, geo_source="census",
    )  # fmt: skip


@pytest.fixture
def line_stations(db):
    """Five stations along the fake route, about 106, 238, 424, 583 and 715 miles in."""
    for opis_id, (lon, price) in enumerate(
        [
            (-98.0, "3.5000"),
            (-95.5, "3.0000"),
            (-92.0, "3.4000"),
            (-89.0, "2.9000"),
            (-86.5, "3.2000"),
        ],
        1,
    ):
        make_station(opis_id, lon, price=price)
