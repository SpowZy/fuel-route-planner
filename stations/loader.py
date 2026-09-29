"""Turn the raw price file into one clean record per station. No Django imports."""

from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .geo import country_of

PRICE_STRATEGIES = {
    "min": min,
    "max": max,
    "median": statistics.median,
    "mean": lambda values: sum(values) / len(values),
}
FOUR_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class StationRecord:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    country: str
    rack_id: int
    price: Decimal
    price_min: Decimal
    price_max: Decimal
    price_rows: int
    latitude: float | None
    longitude: float | None
    geo_source: str


def read_city_coordinates(path: Path) -> dict[tuple[str, str], tuple[float, float, str]]:
    coordinates = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["lat"] and row["lon"]:
                coordinates[(row["city"], row["state"])] = (
                    float(row["lat"]),
                    float(row["lon"]),
                    row["source"],
                )
    return coordinates


def load_stations(csv_path: Path, coordinates_path: Path, strategy: str = "median"):
    """Return (records, stats).

    The price file repeats stations: 26 identical rows, and 597 stations with several
    different prices (median spread 0.09 dollars). Identical rows are dropped, then the
    remaining prices of a station are reduced with `strategy`. Names vary per row for 227
    stations; the most frequent one wins, the longest breaking ties.
    """
    reduce_prices = PRICE_STRATEGIES[strategy]
    coordinates = read_city_coordinates(coordinates_path)

    with open(csv_path, newline="", encoding="utf-8") as handle:
        raw_rows = [
            tuple(value.strip() for value in row.values()) for row in csv.DictReader(handle)
        ]
    rows = list(dict.fromkeys(raw_rows))  # exact duplicates out, order kept

    grouped = defaultdict(list)
    for opis_id, name, address, city, state, rack, price in rows:
        grouped[int(opis_id)].append(
            (name, " ".join(address.split()), city, state, int(rack), Decimal(price))
        )

    records = []
    for opis_id, entries in sorted(grouped.items()):
        names = Counter(entry[0] for entry in entries)
        name = max(names, key=lambda n: (names[n], len(n)))
        _, address, city, state, rack, _ = entries[0]
        prices = [entry[5] for entry in entries]
        place = coordinates.get((city, state))
        records.append(
            StationRecord(
                opis_id=opis_id,
                name=name,
                address=address,
                city=city,
                state=state,
                country=country_of(state),
                rack_id=rack,
                price=Decimal(reduce_prices(prices)).quantize(FOUR_PLACES),
                price_min=min(prices).quantize(FOUR_PLACES),
                price_max=max(prices).quantize(FOUR_PLACES),
                price_rows=len(prices),
                latitude=place[0] if place else None,
                longitude=place[1] if place else None,
                geo_source=place[2] if place else "",
            )
        )
    stats = {
        "rows_read": len(raw_rows),
        "exact_duplicates_dropped": len(raw_rows) - len(rows),
        "stations": len(records),
        "with_coordinates": sum(1 for r in records if r.latitude is not None),
        "canadian": sum(1 for r in records if r.country == "CA"),
        "multi_price": sum(1 for r in records if r.price_min != r.price_max),
    }
    return records, stats
