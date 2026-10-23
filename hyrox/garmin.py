"""Daily recovery data from Garmin.

Preferred: the official Garmin Health API. Garmin pushes summaries to the
garmin-worker receiver, and this reads them back from its /export endpoint
(GARMIN_EXPORT_URL + GARMIN_EXPORT_TOKEN).

Fallback: the unofficial garminconnect library, signed in with GARMIN_TOKENS
from scripts/garmin_auth.py.
"""
import os
from datetime import timedelta

import requests


def from_health_api(day, d):
    """Map one day of official Health API summaries to a wellness row."""
    dailies, sleeps, hrv = day.get("dailies") or {}, day.get("sleeps") or {}, day.get("hrv") or {}
    score = sleeps.get("overallSleepScore")
    return {
        "date": d,
        "resting_hr": dailies.get("restingHeartRateInBeatsPerMinute"),
        "body_battery_high": dailies.get("bodyBatteryHighestValue"),
        "stress_avg": dailies.get("averageStressLevel"),
        "hrv": hrv.get("lastNightAvg"),
        "hrv_status": None,
        "sleep_score": score.get("value") if isinstance(score, dict) else score,
        "sleep_h": round(sleeps["durationInSeconds"] / 3600, 1) if sleeps.get("durationInSeconds") else None,
        "readiness": None,  # not offered by the Health API; HRV/RHR/sleep rules cover it
    }


def sync_health_api(cache):
    r = requests.get(os.environ["GARMIN_EXPORT_URL"].rstrip("/") + "/export",
                     params={"token": os.environ["GARMIN_EXPORT_TOKEN"], "days": 60}, timeout=60)
    r.raise_for_status()
    body = r.json()
    if not body.get("connected"):
        print("garmin: receiver is up but no account connected yet (open /connect?token=...)")
    for d, day in body.get("days", {}).items():
        cache[d] = from_health_api(day, d)
    print(f"garmin: {len(body.get('days', {}))} days from Health API receiver")
    return cache


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
    if os.environ.get("GARMIN_EXPORT_URL") and os.environ.get("GARMIN_EXPORT_TOKEN"):
        try:
            return sync_health_api(cache)
        except Exception as e:
            print(f"garmin: Health API receiver failed, keeping cached data: {e}")
            return cache
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
