"""Training load: per-activity load, fitness/fatigue curves and acute:chronic ratio."""
import math
from collections import defaultdict
from datetime import date, timedelta

# Rough load per minute when there is no heart rate, by sport.
NO_HR_RATE = {"Run": 1.0, "TrailRun": 1.1, "WeightTraining": 0.6, "Workout": 0.8,
              "Crossfit": 0.9, "Rowing": 0.9, "Ride": 0.7, "Walk": 0.2}


def activity_load(a, max_hr, rest_hr):
    """Strava's Relative Effort when present, else Banister TRIMP, else a duration estimate."""
    if a.get("suffer_score"):
        return float(a["suffer_score"])
    minutes = a["moving_s"] / 60
    if a.get("avg_hr") and max_hr > rest_hr:
        x = max(0.0, min(1.0, (a["avg_hr"] - rest_hr) / (max_hr - rest_hr)))
        return minutes * x * 0.64 * math.exp(1.92 * x)
    return minutes * NO_HR_RATE.get(a["sport"], 0.7)


def daily_loads(activities, max_hr, rest_hr):
    by_day = defaultdict(float)
    for a in activities:
        by_day[a["date"]] += activity_load(a, max_hr, rest_hr)
    return by_day


def series(by_day, start, end):
    """Daily rows with ATL (7-day EWMA, fatigue), CTL (42-day EWMA, fitness), TSB (form) and ACWR."""
    atl = ctl = 0.0
    ka, kc = 1 - math.exp(-1 / 7), 1 - math.exp(-1 / 42)
    rows, d = [], start
    while d <= end:
        load = by_day.get(d.isoformat(), 0.0)
        tsb = ctl - atl  # form going into the day
        atl += (load - atl) * ka
        ctl += (load - ctl) * kc
        acute = sum(by_day.get((d - timedelta(days=i)).isoformat(), 0) for i in range(7))
        chronic = sum(by_day.get((d - timedelta(days=i)).isoformat(), 0) for i in range(28)) / 4
        rows.append({"date": d.isoformat(), "load": round(load, 1), "atl": round(atl, 1),
                     "ctl": round(ctl, 1), "tsb": round(tsb, 1),
                     "acwr": round(acute / chronic, 2) if chronic > 0 else None})
        d += timedelta(days=1)
    return rows
