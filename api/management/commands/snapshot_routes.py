from django.core.management.base import BaseCommand

from routing.calls import CallLog
from routing.client import save_snapshot
from routing.locations import resolve_location

DEMO_ROUTES = [
    ("Chicago, IL", "Nashville, TN"),
    ("New York, NY", "Los Angeles, CA"),
    ("Houston, TX", "Denver, CO"),
]


class Command(BaseCommand):
    help = "Save the demo routes from OSRM to data/route_snapshots so the demo also works offline."

    def handle(self, *args, **options):
        for start, finish in DEMO_ROUTES:
            log = CallLog()
            a, b = resolve_location(start, log), resolve_location(finish, log)
            path = save_snapshot((a.lat, a.lon), (b.lat, b.lon), log)
            self.stdout.write(
                f"{start} -> {finish}: {path.name} ({path.stat().st_size // 1024} KB)"
            )
