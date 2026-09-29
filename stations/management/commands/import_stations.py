from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from stations.index import clear_index
from stations.loader import PRICE_STRATEGIES, load_stations
from stations.models import Station

UPDATE_FIELDS = [
    "name", "address", "city", "state", "country", "rack_id", "price", "price_min",
    "price_max", "price_rows", "latitude", "longitude", "geo_source",
]  # fmt: skip


class Command(BaseCommand):
    help = "Load the fuel price file, clean it and attach city coordinates."

    def add_arguments(self, parser):
        data = Path(settings.BASE_DIR) / "data"
        parser.add_argument("--csv", type=Path, default=data / "fuel-prices.csv")
        parser.add_argument("--coordinates", type=Path, default=data / "city_coordinates.csv")
        parser.add_argument(
            "--price-strategy",
            choices=sorted(PRICE_STRATEGIES),
            default=settings.FUEL["PRICE_STRATEGY"],
            help="How to reduce several prices for one station to a single planning price",
        )

    def handle(self, *args, csv, coordinates, price_strategy, **options):
        records, stats = load_stations(csv, coordinates, price_strategy)
        objects = [Station(**record.__dict__) for record in records]
        with transaction.atomic():
            Station.objects.bulk_create(
                objects,
                batch_size=1000,
                update_conflicts=True,
                unique_fields=["opis_id"],
                update_fields=UPDATE_FIELDS,
            )
        clear_index()
        for key, value in stats.items():
            self.stdout.write(f"{key}: {value}")
        self.stdout.write(
            self.style.SUCCESS(f"{len(objects)} stations loaded ({price_strategy} price)")
        )
