"""Plan one trip from the command line and print the plan.

uv run python scripts/try_route.py "New York, NY" "Los Angeles, CA" [--nocache]
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from api.service import plan_trip  # noqa: E402
from routing.calls import CallLog  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    params = {"start": args[0], "finish": args[1], "nocache": "--nocache" in sys.argv}
    for flag in sys.argv[1:]:
        if flag.startswith("--penalty="):
            params["stop_penalty_usd"] = float(flag.split("=")[1])
    log = CallLog()
    payload, timings = plan_trip(params, log)
    print(payload["summary"])
    print(f"route {payload['route']['distance_miles']} mi, {payload['route']['duration_hours']} h")
    for stop in payload["fuel_stops"]:
        s = stop["station"]
        print(
            f"  #{stop['order']:>2} mile {stop['mile_marker']:>7} off {stop['offset_miles']:>4} "
            f"${stop['price_per_gallon']:.4f} buy {stop['gallons_purchased']:>7.3f} gal "
            f"= ${stop['cost_usd']:>7.2f} | {s['name']}, {s['city']} {s['state']} | "
            f"{stop['decision']}"
        )
    print("totals", payload["totals"])
    print("calls", payload["meta"]["calls"], "| routing", payload["meta"]["routing"])
    print("candidates", payload["meta"]["candidates_in_corridor"], "| timings", timings)


if __name__ == "__main__":
    main()
