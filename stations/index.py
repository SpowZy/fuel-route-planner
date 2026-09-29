"""In-memory station arrays used at request time.

Loaded once per process (8k rows, a few milliseconds) so a request never touches the
database to find candidates. Clear it with clear_index() after reloading stations.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from django.conf import settings

from planner.geometry import to_xyz

from .models import Station


@dataclass(frozen=True)
class StationIndex:
    pk: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    xyz: np.ndarray
    price: np.ndarray  # dollars per gallon

    def __len__(self) -> int:
        return len(self.pk)


@lru_cache(maxsize=1)
def get_index() -> StationIndex:
    queryset = Station.objects.exclude(latitude__isnull=True)
    if not settings.FUEL["INCLUDE_CANADA"]:
        queryset = queryset.filter(country="US")
    rows = list(queryset.order_by("pk").values_list("pk", "latitude", "longitude", "price"))
    pk = np.array([r[0] for r in rows], dtype=np.int64)
    lat = np.array([r[1] for r in rows], dtype=float)
    lon = np.array([r[2] for r in rows], dtype=float)
    price = np.array([float(r[3]) for r in rows], dtype=float)
    return StationIndex(pk, lat, lon, to_xyz(lat, lon), price)


def clear_index() -> None:
    get_index.cache_clear()
