"""VO2 max: an estimate from run pace and heart rate, calibrated to watch readings.

Garmin's Personal API doesn't expose VO2 max, so the dashboard combines two sources:
values Jeff logs from his watch (the VO2 max issue form) and an estimate from each
steady run. The estimate uses the ACSM running equation for the oxygen cost of the
run's pace and assumes %VO2 reserve ~ %heart-rate reserve (Swain 1997). Watch readings
then scale the estimate so it lines up with Garmin's number.
"""
from datetime import date, timedelta
from statistics import median

RUN_SPORTS = {"Run", "TrailRun", "VirtualRun"}
MIN_SECONDS = 20 * 60        # short runs are dominated by HR lag
HRR_RANGE = (0.5, 0.95)      # outside this, HR says little about aerobic effort
SMOOTH_RUNS = 5              # median of the last few runs damps hills, heat and fatigue
SMOOTH_DAYS = 42
MATCH_DAYS = 7               # a watch reading calibrates against an estimate this close
CAL_LIMITS = (0.8, 1.25)


def run_estimate(a, max_hr, rest_hr):
    """Raw VO2 max estimate (ml/kg/min) from one run, or None if it isn't usable."""
    if a.get("sport") not in RUN_SPORTS or not a.get("avg_hr") or a.get("moving_s", 0) < MIN_SECONDS:
        return None
    hrr = (a["avg_hr"] - rest_hr) / (max_hr - rest_hr)
    if not HRR_RANGE[0] <= hrr <= HRR_RANGE[1] or not a.get("distance_km"):
        return None
    speed = a["distance_km"] * 1000 / (a["moving_s"] / 60)    # m/min
    vo2 = 0.2 * speed + 3.5                                    # ACSM, level running
    return (vo2 - 3.5) / hrr + 3.5


def raw_series(activities, max_hr, rest_hr):
    """Smoothed raw estimate per run day: median of the last SMOOTH_RUNS runs."""
    runs = [(a["date"], e) for a in sorted(activities, key=lambda a: a["start"])
            if (e := run_estimate(a, max_hr, rest_hr))]
    out = {}
    for i, (d, _) in enumerate(runs):
        since = (date.fromisoformat(d) - timedelta(days=SMOOTH_DAYS)).isoformat()
        window = [e for dd, e in runs[max(0, i - SMOOTH_RUNS + 1):i + 1] if dd >= since]
        out[d] = median(window)
    return out


def calibration(raw, watch):
    """Median watch/estimate ratio over the latest three watch readings with a nearby run."""
    ratios = []
    for w in reversed(watch):
        wd = date.fromisoformat(w["date"])
        near = [(abs((date.fromisoformat(d) - wd).days), d) for d in raw]
        near = [x for x in near if x[0] <= MATCH_DAYS]
        if near:
            ratios.append(w["value"] / raw[min(near)[1]])
        if len(ratios) == 3:
            break
    if not ratios:
        return None
    return max(CAL_LIMITS[0], min(CAL_LIMITS[1], median(ratios)))


def summary(activities, watch_logs, max_hr, rest_hr, today, days=84):
    since = (today - timedelta(days=days)).isoformat()
    by_day = {l["date"]: l["value"] for l in watch_logs}
    watch = [{"date": d, "value": by_day[d]} for d in sorted(by_day)]
    raw = raw_series(activities, max_hr, rest_hr)
    factor = calibration(raw, watch)
    estimate = [{"date": d, "value": round(v * (factor or 1), 1)} for d, v in sorted(raw.items()) if d >= since]
    return {"estimate": estimate, "watch": [w for w in watch if w["date"] >= since],
            "calibration": round(factor, 3) if factor else None}
