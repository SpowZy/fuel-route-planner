"""Independent solvers the optimizer is checked against.

The linear program is the fixed-route problem written as plain constraints and solved by
HiGHS. It shares no code, no grid and no rule of thumb with planner.optimizer.
"""

from itertools import combinations

import numpy as np
from scipy.optimize import linprog

from planner.optimizer import EPS  # one tolerance for "reaches the end", in miles


def lp_cost(
    total, miles, price, detour=None, *, range_miles=500.0, mpg=10.0, start_range=None, reserve=0.0
):
    """Minimum dollars for the stations given, all of them used with their detour cost.

    Returns None when infeasible. Variables are miles of range bought at each station.
    """
    start = range_miles if start_range is None else min(start_range, range_miles)
    if start >= total + reserve - EPS:
        return 0.0
    order = np.argsort(miles, kind="stable")
    m = np.asarray(miles, dtype=float)[order]
    q = np.asarray(price, dtype=float)[order] / mpg
    d = np.zeros_like(m) if detour is None else np.asarray(detour, dtype=float)[order]
    n = len(m)
    if n == 0:
        return None
    rows, limits = [], []
    for j in range(n + 1):
        need = (m[j] + d[j] / 2 if j < n else total) + reserve
        row = np.zeros(n)
        row[:j] = -1.0
        rows.append(row)
        limits.append(start - need)
    for j in range(n):
        row = np.zeros(n)
        row[: j + 1] = 1.0
        rows.append(row)
        limits.append(m[j] + range_miles - d[j] / 2 - start)
    result = linprog(
        q, A_ub=np.array(rows), b_ub=np.array(limits), bounds=(0, None), method="highs"
    )
    if result.status != 0:
        return None
    return float(result.fun + np.sum(q * d))


def brute_force_cost(total, miles, price, detour, *, stop_penalty=0.0, **kwargs):
    """Try every subset of stops, each priced by the linear program. Small inputs only.

    Returns the objective the optimizer minimizes: fuel bill plus stop_penalty per stop.
    """
    miles, price, detour = (np.asarray(x, dtype=float) for x in (miles, price, detour))
    best = None
    for size in range(len(miles) + 1):
        for subset in combinations(range(len(miles)), size):
            idx = list(subset)
            cost = lp_cost(total, miles[idx], price[idx], detour[idx], **kwargs)
            if cost is not None:
                cost += stop_penalty * size
                if best is None or cost < best:
                    best = cost
    return best
