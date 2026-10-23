"""Daily recovery data from Garmin Connect via the unofficial garminconnect library.

Garmin has no self-serve API, so this signs in with your Garmin account. To avoid
MFA prompts in CI, run scripts/garmin_auth.py once locally and store its output
as the GARMIN_TOKENS secret.
"""
import os
from datetime import date, timedelta


def _client():
    from garminconnect import Garmin

    tokens = os.environ.get("GARMIN_TOKENS")
    if tokens:
        g = Garmin()
        g.login(tokens)
        return g
    g = Garmin(os.environ["GARMIN_EMAIL"], os.environ["GARMIN_PASSWORD"])
    g.login()
    return g


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as e:  # one bad endpoint shouldn't sink the whole sync
        print(f"garmin: {fn.__name__} failed: {e}")
        return None


def day(g, d):
    ds = d.isoformat()
    stats = _safe(g.get_stats, ds) or {}
    hrv = (_safe(g.get_hrv_data, ds) or {}).get("hrvSummary") or {}
    sleep = ((_safe(g.get_sleep_data, ds) or {}).get("dailySleepDTO") or {})
    readiness = _safe(g.get_training_readiness, ds)
    if isinstance(readiness, list):
        readiness = readiness[0] if readiness else {}
    return {
        "date": ds,
        "resting_hr": stats.get("restingHeartRate"),
        "body_battery_high": stats.get("bodyBatteryHighestValue"),
        "hrv": hrv.get("lastNightAvg"),
        "hrv_status": hrv.get("status"),
        "sleep_score": ((sleep.get("sleepScores") or {}).get("overall") or {}).get("value"),
        "sleep_h": round(sleep["sleepTimeSeconds"] / 3600, 1) if sleep.get("sleepTimeSeconds") else None,
        "readiness": (readiness or {}).get("score"),
    }


def sync(cache, today, days=45):
    """cache: dict date -> wellness row. Refetches the last 2 days, fills gaps up to `days` back."""
    if not (os.environ.get("GARMIN_TOKENS") or os.environ.get("GARMIN_EMAIL")):
        print("garmin: no credentials, skipping")
        return cache
    try:
        g = _client()
    except Exception as e:
        print(f"garmin: login failed, keeping cached data: {e}")
        return cache
    fetched = 0
    for i in range(days):
        d = today - timedelta(days=i)
        if i < 2 or d.isoformat() not in cache:
            cache[d.isoformat()] = day(g, d)
            fetched += 1
    print(f"garmin: fetched {fetched} days")
    return cache
