import numpy as np
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from planner.baseline import baseline_cost
from planner.optimizer import InfeasibleRoute, plan_fuel

from .oracle import brute_force_cost, lp_cost

TOL = 1e-6


def simulate(plan, miles_unused=None, reserve=0.0):
    """Drive the plan and return the lowest tank level seen, the highest, and the final level."""
    fuel, position = plan.start_gallons, 0.0
    lowest, highest = fuel, fuel
    for stop in plan.stops:
        fuel -= (stop.mile - position) / plan.mpg
        lowest = min(lowest, fuel)
        assert fuel == pytest.approx(stop.tank_before, abs=1e-6)
        fuel -= stop.detour_miles / 2 / plan.mpg
        lowest = min(lowest, fuel)
        fuel += stop.gallons
        highest = max(highest, fuel)
        fuel -= stop.detour_miles / 2 / plan.mpg
        assert fuel == pytest.approx(stop.tank_after, abs=1e-6)
        position = stop.mile
    fuel -= (plan.total_miles - position) / plan.mpg
    lowest = min(lowest, fuel)
    return lowest, highest, fuel


instances = st.builds(
    lambda total, stations, start, reserve: (total, stations, start, reserve),
    total=st.floats(100, 2500),
    stations=st.lists(
        st.tuples(st.floats(0, 1), st.floats(2.0, 6.0), st.sampled_from([0.0, 0.0, 4.0, 12.0])),
        max_size=12,
    ),
    start=st.floats(0, 500),
    reserve=st.sampled_from([0.0, 0.0, 25.0]),
)


def unpack(instance):
    total, stations, start, reserve = instance
    miles = np.array([s[0] * total for s in stations])
    price = np.array([s[1] for s in stations])
    detour = np.array([s[2] for s in stations])
    return total, miles, price, detour, start, reserve


def test_buys_only_what_reaches_the_cheaper_station():
    # 600 miles, two stations at mile 200 ($4) and mile 450 ($3), full 500-mile tank at start.
    plan = plan_fuel(600, [200, 450], [4.0, 3.0], start_range=500)
    assert len(plan.stops) == 1
    stop = plan.stops[0]
    assert stop.mile == 450
    assert stop.gallons == pytest.approx(10.0)  # 100 miles short at mile 450 is all it needs
    assert plan.cost == pytest.approx(30.0)


def test_fills_the_tank_when_nothing_cheaper_is_ahead():
    # 1000 miles. Mile 100 is cheap ($3) and mile 550 is dear ($5), so fill up at mile 100
    # (range now reaches mile 600) and buy at 550 only the 400 miles still missing.
    plan = plan_fuel(1000, [100, 550], [3.0, 5.0], start_range=500)
    first, last = plan.stops
    assert first.mile == 100 and first.tank_after == pytest.approx(50.0)
    assert last.mile == 550 and last.gallons == pytest.approx(40.0)
    assert plan.cost == pytest.approx(first.gallons * 3.0 + 40.0 * 5.0)


def test_no_stop_when_the_starting_tank_reaches_the_end():
    plan = plan_fuel(420, [100, 300], [3.0, 3.0], start_range=500)
    assert plan.stops == () and plan.cost == 0.0


def test_infeasible_gap_is_reported():
    with pytest.raises(InfeasibleRoute) as info:
        plan_fuel(1500, [100, 800], [3.0, 3.0], start_range=500)
    assert info.value.gap_start_mile == pytest.approx(600)
    assert info.value.gap_end_mile == 800


@settings(max_examples=300, deadline=None)
@example(instance=(1001.0, [(0.625, 2.0, 0.0), (0.25, 2.0, 0.0), (1e-12, 2.0, 0.0)], 0.0, 0.0))
@given(instances)
def test_matches_the_linear_program_without_detours(instance):
    # The example is a station a nanomile from an empty tank at the start, found by hypothesis:
    # the LP solver accepts it within its tolerance, so the optimizer has to as well.
    total, miles, price, _, start, reserve = unpack(instance)
    no_detour = np.zeros_like(miles)
    expected = lp_cost(total, miles, price, no_detour, start_range=start, reserve=reserve)
    if expected is None:
        with pytest.raises(InfeasibleRoute):
            plan_fuel(total, miles, price, no_detour, start_range=start, reserve=reserve)
        return
    plan = plan_fuel(total, miles, price, no_detour, start_range=start, reserve=reserve)
    assert plan.cost == pytest.approx(expected, abs=TOL, rel=TOL)


@settings(max_examples=150, deadline=None)
@given(instances.filter(lambda i: len(i[1]) <= 7), st.sampled_from([0.0, 0.0, 3.0, 15.0]))
def test_matches_exhaustive_search_with_detours_and_stop_penalty(instance, penalty):
    total, miles, price, detour, start, reserve = unpack(instance)
    kwargs = {"start_range": start, "reserve": reserve}
    expected = brute_force_cost(total, miles, price, detour, stop_penalty=penalty, **kwargs)
    if expected is None:
        with pytest.raises(InfeasibleRoute):
            plan_fuel(total, miles, price, detour, stop_penalty=penalty, **kwargs)
        return
    plan = plan_fuel(total, miles, price, detour, stop_penalty=penalty, **kwargs)
    objective = plan.cost + penalty * len(plan.stops)
    assert objective == pytest.approx(expected, abs=TOL, rel=TOL)


def test_a_stop_penalty_removes_a_stop_that_saves_little():
    # 900 miles. Mile 100 sells at $2 and mile 450 at $3. Only the stop at 450 can finish the
    # trip (a tank bought at 100 reaches mile 600), so the early stop is optional: it saves $10.
    free = plan_fuel(900, [100, 450], [2.0, 3.0], start_range=500)
    assert [s.mile for s in free.stops] == [100, 450]
    assert free.cost == pytest.approx(10 * 2.0 + 30 * 3.0)
    for penalty, expected_stops in [(9.0, 2), (11.0, 1)]:
        plan = plan_fuel(900, [100, 450], [2.0, 3.0], stop_penalty=penalty, start_range=500)
        assert len(plan.stops) == expected_stops
    # the penalty steers the choice but never appears in the fuel bill
    assert plan.cost == pytest.approx(40 * 3.0)


@settings(max_examples=300, deadline=None)
@given(instances)
def test_plan_is_physically_valid_and_never_worse_than_the_baseline(instance):
    total, miles, price, detour, start, reserve = unpack(instance)
    try:
        plan = plan_fuel(total, miles, price, detour, start_range=start, reserve=reserve)
    except InfeasibleRoute:
        return
    lowest, highest, final = simulate(plan)
    assert lowest >= reserve / 10 - 1e-6  # never below the reserve
    assert highest <= 50.0 + 1e-6  # never above a full tank
    assert plan.gallons_bought == pytest.approx(
        plan.gallons_burned - plan.start_gallons + final, abs=1e-6
    )
    naive = baseline_cost(total, miles, price, detour, start_range=start, reserve=reserve)
    if naive is not None:
        assert plan.cost <= naive + 1e-6


def test_more_expensive_stations_never_lower_the_cost():
    rng = np.random.default_rng(7)
    for _ in range(50):
        miles = np.sort(rng.uniform(0, 2000, 15))
        price = rng.uniform(2.5, 5.0, 15)
        try:
            base = plan_fuel(2000, miles, price).cost
            worse = plan_fuel(2000, miles, price + 0.25).cost
        except InfeasibleRoute:
            continue
        assert worse >= base - 1e-9
