"""Daily recovery data from Garmin's official Personal API.

Create a key at https://connect.garmin.com/app/settings/personalApiToken and store it
as the `Garmin` repository secret (exposed to the build as GARMIN_PERSONAL_API_KEY).
The key is exchanged for a 24-hour bearer token on each run.
"""
import os
from datetime import timedelta

CHUNK_DAYS = 14   # keep each range request small; the API's maximum isn't documented

# Candidate field names per metric. The Personal API's response schemas aren't
# published outside Swagger, so match the names Garmin Connect uses elsewhere.
FIELDS = {
    "resting_hr": ("heartRate.restingValue", "restingHeartRate", "restingHeartRateValue", "restingHeartRateInBeatsPerMinute"),
    "body_battery_high": ("bodyBattery.maxValue", "bodyBatteryHighestValue", "bodyBatteryHigh", "highestBodyBattery"),
    "stress_avg": ("stress.avgLevel", "averageStressLevel", "avgStressLevel", "overallStressLevel"),
    "hrv": ("lastNightAvg", "lastNightAverage"),
    "hrv_status": ("status", "hrvStatus"),
    "sleep_score": ("overallSleepScore", "sleepScore", "overall", "value"),
    "sleep_s": ("sleepTimeSeconds", "totalSleepSeconds", "durationInSeconds", "sleepDurationInSeconds"),
}
DATE_KEYS = ("calendarDate", "date", "summaryDate")


def records(payload):
    """Yield dicts that carry a calendar date, wherever the response nests them."""
    if isinstance(payload, list):
        for x in payload:
            yield from records(x)
    elif isinstance(payload, dict):
        if any(k in payload for k in DATE_KEYS):
            yield payload
        else:
            for v in payload.values():
                if isinstance(v, (list, dict)):
                    yield from records(v)


def scalar(v):
    if isinstance(v, dict) and isinstance(v.get("value"), (int, float)):
        return v["value"]
    if isinstance(v, (int, float, str)) and not isinstance(v, bool):
        return v
    return None


def find(rec, names, depth=3):
    """First scalar under any of `names`: dotted names are exact paths, plain names
    are searched in nested dicts breadth-first."""
    for n in names:
        if "." in n:
            v = rec
            for part in n.split("."):
                v = v.get(part) if isinstance(v, dict) else None
            if scalar(v) is not None:
                return scalar(v)
    names = [n for n in names if "." not in n]
    level = [rec]
    for _ in range(depth):
        nxt = []
        for d in level:
            for n in names:
                if scalar(d.get(n)) is not None:
                    return scalar(d.get(n))
            nxt.extend(v for v in d.values() if isinstance(v, dict))
        level = nxt
    return None


def key_names(rec, prefix="", depth=2):
    """Field names in a record (never values), for diagnosing an unmapped schema."""
    out = []
    for k, v in rec.items():
        out.append(prefix + k)
        if isinstance(v, dict) and depth > 1:
            out.extend(key_names(v, prefix + k + ".", depth - 1))
    return out


def merge(rows, payload, metrics, label):
    n, unmapped = 0, set()
    for rec in records(payload):
        d = next(str(rec[k])[:10] for k in DATE_KEYS if k in rec)
        row = rows.setdefault(d, {"date": d})
        for m in metrics:
            v = find(rec, FIELDS[m])
            if v is not None:
                row[m] = v
            else:
                unmapped.add(m)
        if n == 0 and unmapped:
            print(f"garmin: {label} record has no {sorted(unmapped)}; fields: {key_names(rec)}")
        n += 1
    if n == 0:
        # Log the response's shape (key names only, never values) so the mapping can be fixed.
        shape = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
        print(f"garmin: no dated records in {label} response; top-level: {shape}")
    return n


def finish(row):
    sleep_s = row.pop("sleep_s", None)
    try:
        row["sleep_h"] = round(float(sleep_s) / 3600, 1) if sleep_s else None
    except (TypeError, ValueError):
        row["sleep_h"] = None
    for m in ("resting_hr", "body_battery_high", "stress_avg", "hrv", "sleep_score"):
        try:
            row[m] = round(float(row[m])) if row.get(m) is not None else None
        except (TypeError, ValueError):
            row[m] = None
    if isinstance(row.get("hrv_status"), str):
        row["hrv_status"] = row["hrv_status"].upper()
    else:
        row["hrv_status"] = None
    row.setdefault("readiness", None)  # training readiness isn't in the Personal API
    return row


def fetch(client, start, end):
    rows = {}
    calls = [
        ("daily summaries", client.get_daily_summaries, ("resting_hr", "body_battery_high", "stress_avg")),
        ("sleep", client.get_daily_sleep_summaries, ("sleep_score", "sleep_s")),
        ("hrv", client.get_daily_hrv_summaries, ("hrv", "hrv_status")),
    ]
    for label, fn, metrics in calls:
        s = start
        while s <= end:
            e = min(end, s + timedelta(days=CHUNK_DAYS - 1))
            try:
                merge(rows, fn(s, e), metrics, label)
            except Exception as ex:  # one failing endpoint shouldn't sink the sync
                print(f"garmin: {label} {s}..{e} failed: {ex}")
            s = e + timedelta(days=1)
    return {d: finish(r) for d, r in rows.items()}


def sync(cache, today, days=45):
    """cache: dict date -> wellness row. Refetches the last 3 days, fills gaps up to `days` back."""
    key = os.environ.get("GARMIN_PERSONAL_API_KEY")
    if not key:
        print("garmin: no GARMIN_PERSONAL_API_KEY, skipping")
        return cache
    from garmin_personal_api.auth import PersonalApiAuthenticator
    from garmin_personal_api.client import GarminPersonalApiClient

    missing = [d for d in (today - timedelta(days=i) for i in range(days))
               if cache.get(d.isoformat(), {}).get("resting_hr") is None]
    start = min(missing + [today - timedelta(days=2)])
    try:
        with PersonalApiAuthenticator() as auth:
            token = auth.obtain_token(key)
        with GarminPersonalApiClient(token.access_token) as client:
            fresh = fetch(client, start, today)
    except Exception as e:
        print(f"garmin: Personal API failed, keeping cached data: {e}")
        return cache
    cache.update(fresh)
    coverage = {m: sum(r.get(m) is not None for r in fresh.values())
                for m in ("resting_hr", "hrv", "hrv_status", "sleep_score", "sleep_h", "body_battery_high")}
    print(f"garmin: {len(fresh)} days from {start} to {today}; days with each metric: {coverage}")
    return cache
