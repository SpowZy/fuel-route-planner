"""Exact minimum-cost fuel purchasing along a fixed route.

Model
-----
The truck drives a fixed route of D miles. A tank holds C miles of range (500 miles at
10 mpg is 50 gallons). Candidate stations sit at known mileposts with a price per gallon
and a detour: the round-trip miles needed to leave the route and come back.

Track the frontier R = position + range left in the tank, in miles. Driving leaves R
unchanged. Buying y miles of range at a station raises R by y and costs y * price / mpg.
Stopping at station i is only possible when R has not fallen behind it, and the tank can
never hold more than C miles:

    reach:   R >= m_i + reserve + d_i / 2        (enough fuel to get to the pump)
    tank:    R_after <= m_i + C - d_i / 2        (the pump nozzle stops at a full tank)
    finish:  R >= D + reserve

A stop also burns d_i miles of range, which is bought at the same pump, so it adds a fixed
cost of d_i * price / mpg, plus an optional per-stop penalty for the driver's time. With
zero detours and no penalty this is the classic fixed-route gas station
problem and the "buy just enough to reach a cheaper station, otherwise fill up" rule is
optimal (Khuller, Malekian and Mestre, ACM TALG 2011, Lemma 2.1). Detours turn each stop into a
fixed-charge decision, where that rule is no longer optimal, so this module solves the
general problem exactly.

Exactness
---------
The problem is linear once the set of stops is fixed, and every constraint above bounds R by
a constant. A vertex solution therefore only ever puts R on one of those constants:
the starting range, D + reserve, m_i + reserve + d_i / 2 or m_i + C - d_i / 2. That is at most
3n + 2 values, so the dynamic program below runs over that finite grid with no rounding.
Each station is O(|grid|) numpy work.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EPS = 1e-7  # miles; same scale as the feasibility tolerance of the LP solver used in the tests


class InfeasibleRoute(Exception):
    """No sequence of stops gets the truck to the end within the tank range."""

    def __init__(self, gap_start_mile: float, gap_end_mile: float | None):
        self.gap_start_mile = gap_start_mile
        self.gap_end_mile = gap_end_mile
        end = "the destination" if gap_end_mile is None else f"mile {gap_end_mile:.0f}"
        super().__init__(f"No reachable fuel station between mile {gap_start_mile:.0f} and {end}")


@dataclass(frozen=True)
class Stop:
    index: int  # index into the candidate arrays passed to plan_fuel
    mile: float
    price: float  # dollars per gallon
    detour_miles: float
    gallons: float  # bought, includes the fuel burned on the detour
    tank_before: float  # gallons when the truck leaves the route
    tank_after: float  # gallons when it is back on the route

    @property
    def cost(self) -> float:
        return self.gallons * self.price


@dataclass(frozen=True)
class Plan:
    stops: tuple[Stop, ...]
    total_miles: float
    start_gallons: float
    mpg: float

    @property
    def cost(self) -> float:
        return sum(stop.cost for stop in self.stops)

    @property
    def gallons_bought(self) -> float:
        return sum(stop.gallons for stop in self.stops)

    @property
    def gallons_burned(self) -> float:
        return (self.total_miles + sum(s.detour_miles for s in self.stops)) / self.mpg

    @property
    def end_gallons(self) -> float:
        return self.start_gallons + self.gallons_bought - self.gallons_burned


def unreachable_gap(total_miles, miles, detour, range_miles, start_range, reserve):
    """Best case reach if the truck filled up at every station; returns the first gap."""
    reach = start_range
    for i in np.argsort(miles, kind="stable"):
        if miles[i] + reserve + detour[i] / 2 <= reach + EPS:
            reach = max(reach, miles[i] + range_miles - detour[i] / 2)
        else:
            return reach - reserve, float(miles[i])
    return reach - reserve, None


def plan_fuel(
    total_miles: float,
    miles,
    price,
    detour=None,
    *,
    range_miles: float = 500.0,
    mpg: float = 10.0,
    start_range: float | None = None,
    reserve: float = 0.0,
    stop_penalty: float = 0.0,
) -> Plan:
    """Cheapest way to buy fuel. Raises InfeasibleRoute when the tank cannot bridge a gap.

    miles         milepost of each candidate station, measured along the route
    price         dollars per gallon
    detour        round-trip miles off the route (0 for stations on the route)
    stop_penalty  dollars charged per stop for the driver's time. It steers the plan away from
                  stopping to save a few cents, and is not part of Plan.cost (the fuel bill).
    """
    miles = np.asarray(miles, dtype=float)
    price = np.asarray(price, dtype=float)
    detour = np.zeros_like(miles) if detour is None else np.asarray(detour, dtype=float)
    start_range = range_miles if start_range is None else min(float(start_range), range_miles)
    start_gallons = start_range / mpg
    goal = total_miles + reserve
    if start_range >= goal - EPS:
        return Plan((), total_miles, start_gallons, mpg)

    usable = np.flatnonzero(miles <= total_miles + EPS)
    order = usable[np.argsort(miles[usable], kind="stable")]
    m, p, d = miles[order], price[order], detour[order]
    q = p / mpg  # dollars per mile of range
    need = m + reserve + d / 2
    cap = m + range_miles - d / 2
    fixed = q * d + stop_penalty

    values = np.concatenate(([start_range, goal], need, cap))
    grid = np.unique(values[(values >= start_range - EPS) & (values <= goal + EPS)])
    size = len(grid)
    cost = np.full(size, np.inf)
    cost[np.searchsorted(grid, start_range - EPS)] = 0.0
    position = np.arange(size)

    took, came_from = [], []
    for i in range(len(m)):
        buyable = grid >= need[i] - EPS
        shifted = np.where(buyable, cost - q[i] * grid, np.inf)
        running = np.minimum.accumulate(shifted)
        after = running + q[i] * grid + fixed[i]
        after = np.where(grid <= cap[i] + EPS, after, np.inf)
        better = after < cost - 1e-12
        holder = np.maximum.accumulate(np.where(shifted <= running, position, 0))
        took.append(better)
        came_from.append(holder)
        cost = np.where(better, after, cost)

    finals = np.flatnonzero(grid >= goal - EPS)
    best = finals[np.argmin(cost[finals])]
    if not np.isfinite(cost[best]):
        raise InfeasibleRoute(
            *unreachable_gap(total_miles, m, d, range_miles, start_range, reserve)
        )

    stops, state = [], best
    for i in range(len(m) - 1, -1, -1):
        if took[i][state]:
            before = came_from[i][state]
            bought = grid[state] - grid[before]
            if bought > EPS:
                stops.append(
                    Stop(
                        index=int(order[i]),
                        mile=float(m[i]),
                        price=float(p[i]),
                        detour_miles=float(d[i]),
                        gallons=float((bought + d[i]) / mpg),
                        tank_before=float((grid[before] - m[i]) / mpg),
                        tank_after=float((grid[state] - m[i]) / mpg),
                    )
                )
            state = before
    stops.reverse()
    return Plan(tuple(stops), total_miles, start_gallons, mpg)
