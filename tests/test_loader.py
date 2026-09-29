from decimal import Decimal

from stations.geo import norm_place, parse_state
from stations.loader import load_stations

CSV = """OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price
20,PILOT TRAVEL CENTER #1243,"I-8, EXIT 119",Gila Bend                     ,AZ,930,3.899
20,PILOT #1243,"I-8, EXIT 119",Gila Bend                     ,AZ,930,3.899
20,PILOT TRAVEL CENTER #1243,"I-8, EXIT 119",Gila Bend                     ,AZ,930,3.899
105,TA SAGINAW,"I-75,  EXIT 144-B",Bridgeport,MI,260,3.269
105,TA SAGINAW,"I-75,  EXIT 144-B",Bridgeport,MI,260,3.429
105,TA SAGINAW,"I-75,  EXIT 144-B",Bridgeport,MI,260,3.299
900,TIM HORTONS TRUCK,"HWY 401",Ayr,ON,1,3.10
"""

COORDINATES = """city,state,lat,lon,source,matched_name
Gila Bend,AZ,32.94,-112.71,census,Gila Bend town
Bridgeport,MI,43.36,-83.88,census,Bridgeport CDP
Ayr,ON,,,unmatched,
"""


def load(tmp_path, strategy="median"):
    prices, coordinates = tmp_path / "p.csv", tmp_path / "c.csv"
    prices.write_text(CSV)
    coordinates.write_text(COORDINATES)
    records, stats = load_stations(prices, coordinates, strategy)
    return {r.opis_id: r for r in records}, stats


def test_exact_duplicates_are_dropped_and_names_reconciled(tmp_path):
    stations, stats = load(tmp_path)
    assert stats["rows_read"] == 7 and stats["exact_duplicates_dropped"] == 1
    assert stations[20].name == "PILOT TRAVEL CENTER #1243"  # most frequent row wins
    assert stations[20].city == "Gila Bend"  # padding removed
    assert stations[20].price_rows == 2  # one exact duplicate removed, two names remain


def test_price_strategy_reduces_several_prices(tmp_path):
    for strategy, expected in [
        ("median", "3.2990"),
        ("min", "3.2690"),
        ("max", "3.4290"),
        ("mean", "3.3323"),
    ]:
        stations, _ = load(tmp_path, strategy)
        assert stations[105].price == Decimal(expected)
        assert stations[105].price_min == Decimal("3.2690")
        assert stations[105].price_max == Decimal("3.4290")


def test_country_and_missing_coordinates(tmp_path):
    stations, stats = load(tmp_path)
    assert stations[900].country == "CA" and stations[900].latitude is None
    assert stations[20].latitude == 32.94 and stations[20].geo_source == "census"
    assert stats["with_coordinates"] == 2 and stats["canadian"] == 1


def test_place_names_normalize_like_the_census_file():
    assert norm_place("St. Louis") == norm_place("Saint Louis") == "ST LOUIS"
    assert norm_place("Bay City city", strip_suffix=True) == "BAY CITY"
    assert norm_place("Bay City") == "BAY CITY"  # input keeps its words
    assert norm_place("Cañon City") == "CANON CITY"
    assert (
        parse_state("texas") == "TX"
        and parse_state("TX.") == "TX"
        and parse_state("Narnia") is None
    )
