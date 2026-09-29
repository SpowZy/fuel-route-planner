import pytest

from routing.calls import CallLog
from routing.locations import LocationError, resolve_location

BIG_CITIES = """New York, NY|Los Angeles, CA|Chicago, IL|Houston, TX|Phoenix, AZ|Philadelphia, PA|
San Antonio, TX|San Diego, CA|Dallas, TX|Nashville, TN|Louisville, KY|Indianapolis, IN|Boise, ID|
Lexington, KY|Augusta, GA|Athens, GA|Washington, DC|Miami, FL|Atlanta, GA|Seattle, WA|Denver, CO|
Boston, MA|Detroit, MI|Buffalo, NY|St. Louis, MO|Saint Paul, MN|Salt Lake City, UT|Las Vegas, NV|
Portland, OR|Portland, ME|Charlotte, NC|Kansas City, MO|Oklahoma City, OK|Albuquerque, NM|Omaha, NE|
Memphis, TN|New Orleans, LA|Minneapolis, MN|Cleveland, OH|Pittsburgh, PA|Richmond, VA|
Sacramento, CA|San Francisco, CA|Milwaukee, WI|Jacksonville, FL|Columbus, OH|El Paso, TX|
Fort Worth, TX|Austin, TX|Bay City, MI|Carson City, NV|Cheyenne, WY|Billings, MT""".replace(
    "\n", ""
)


@pytest.mark.parametrize("city", [c.strip() for c in BIG_CITIES.split("|")])
def test_major_cities_resolve_offline(city):
    log = CallLog()
    place = resolve_location(city, log)
    assert place.source == "places"
    assert len(log) == 0  # no external call for "City, ST"


def test_state_names_and_trailing_country_are_accepted():
    log = CallLog()
    a = resolve_location("Dallas, Texas", log)
    b = resolve_location("dallas, tx, USA", log)
    assert (a.lat, a.lon) == (b.lat, b.lon)
    assert a.lat == pytest.approx(32.78, abs=0.1) and a.lon == pytest.approx(-96.8, abs=0.1)


def test_coordinates_pass_through_without_a_call():
    log = CallLog()
    place = resolve_location(" 41.8781 , -87.6298 ", log)
    assert place.source == "coordinates" and place.lat == 41.8781 and len(log) == 0


@pytest.mark.parametrize(
    "text", ["Anchorage, AK", "Honolulu, HI", "51.5,-0.12", "0,0", "10.0,-90.0"]
)
def test_places_outside_the_covered_area_are_rejected(text):
    with pytest.raises(LocationError) as info:
        resolve_location(text, CallLog())
    assert info.value.code == "outside_coverage"
