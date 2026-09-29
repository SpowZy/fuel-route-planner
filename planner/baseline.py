"""The strategy the optimizer is measured against.

"Drive to the farthest station you can still reach, fill the tank, repeat." Fuel is bought
only when the tank is nearly empty and always topped up, except at the last stop, where it
buys just enough to finish. Same stations, same detours, same tank as the optimizer.
"""

from __future__ import annotations

import numpy as np

EPS = 1e-7  # miles, kept equal to planner.optimizer.EPS


def baseline_cost(
    total_miles: float,
    miles,
    price,
    detour=None,
    *,
    range_miles: float = 500.0,
    mpg: float = 10.0,
    start_range: float | None = None,
    reserve: float = 0.0,
) -> float | None:
    """Dollars spent by the naive strategy, or None when it cannot reach the end."""
    miles = np.asarray(miles, dtype=float)
    price = np.asarray(price, dtype=float)
    detour = np.zeros_like(miles) if detour is None else np.asarray(detour, dtype=float)
    frontier = range_miles if start_range is None else min(float(start_range), range_miles)
    goal = total_miles + reserve
    position, spent = 0.0, 0.0
    while frontier < goal - EPS:
        reachable = np.flatnonzero(
            (miles > position + EPS)
            & (miles <= total_miles + EPS)
            & (miles + reserve + detour / 2 <= frontier + EPS)
        )
        if reachable.size == 0:
            return None
        j = reachable[np.argmax(miles[reachable])]
        room = miles[j] + range_miles - detour[j] / 2 - frontier
        bought = min(room, goal - frontier)
        spent += price[j] / mpg * (bought + detour[j])
        frontier += bought
        position = miles[j]
    return spent
