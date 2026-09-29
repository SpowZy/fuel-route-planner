"""Find the stations near a route and where along the route they sit."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from .geometry import Route, chord_to_miles, densify, miles_to_chord, to_xyz


@dataclass(frozen=True)
class Corridor:
    station_rows: np.ndarray  # indices into the station arrays
    mile: np.ndarray  # distance along the route from the start
    offset: np.ndarray  # straight-line miles from the station to the route

    def __len__(self) -> int:
        return len(self.station_rows)


def stations_along(
    route: Route,
    station_xyz: np.ndarray,
    max_offset_miles: float,
    step_miles: float = 0.25,
) -> Corridor:
    """Stations within max_offset_miles of the route, sorted by position along it.

    The route is densified to step_miles and indexed in a KD-tree; every station is then
    matched to its nearest route point in one vectorized query. Position resolution is
    step_miles, far below the precision of the station coordinates.
    """
    dense_lat, dense_lon, dense_cum = densify(route, step_miles)
    tree = cKDTree(to_xyz(dense_lat, dense_lon))
    dist, nearest = tree.query(station_xyz, distance_upper_bound=miles_to_chord(max_offset_miles))
    found = np.isfinite(dist)
    rows = np.flatnonzero(found)
    mile = dense_cum[nearest[found]]
    offset = chord_to_miles(dist[found])
    order = np.argsort(mile, kind="stable")
    return Corridor(rows[order], mile[order], offset[order])
