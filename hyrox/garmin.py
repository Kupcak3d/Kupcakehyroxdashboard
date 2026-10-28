"""Recovery data and activities from Garmin's official Personal API.

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


# Garmin activity type keys -> the Strava-style sport names the rest of the code uses.
SPORTS = {
    "running": "Run", "street_running": "Run", "track_running": "Run", "treadmill_running": "Run",
    "indoor_running": "Run", "virtual_run": "VirtualRun", "trail_running": "TrailRun",
    "strength_training": "WeightTraining", "indoor_rowing": "Rowing", "rowing": "Rowing",
    "hiit": "Workout", "indoor_cardio": "Workout", "fitness_equipment": "Workout",
    "cycling": "Ride", "indoor_cycling": "Ride", "walking": "Walk", "hiking": "Walk",
}


def normalize_activity(a):
    type_key = ((a.get("activityType") or {}).get("typeKey") or "other").lower()
    start = str(a.get("startTimeLocal") or "").replace(" ", "T")
    moving = a.get("movingDuration") or a.get("duration") or 0
    return {
        "id": f"g{a['activityId']}",
        "garmin_id": a["activityId"],
        "source": "garmin",
        "date": start[:10],
        "start": start,
        "sport": SPORTS.get(type_key, type_key),
        "name": a.get("activityName") or "",
        "distance_km": round((a.get("distance") or 0) / 1000, 2),
        "moving_s": int(moving),
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "suffer_score": None,
        # Garmin's running VO2 max estimate, recorded on each outdoor run with heart rate.
        "vo2max": next((a[k] for k in ("vO2MaxValue", "vo2MaxValue", "vo2Max") if a.get(k)), None),
    }


def laps_from(payload):
    """Laps from an activity's splits response, in the shape adapt.py expects."""
    laps = (payload or {}).get("lapDTOs") if isinstance(payload, dict) else payload
    out = []
    for l in laps or []:
        dist = l.get("distance") or 0
        secs = l.get("movingDuration") or l.get("duration") or 0
        if dist and secs:
            out.append({"distance_m": dist, "moving_s": secs, "avg_hr": l.get("averageHR")})
    return out


def sync_activities(client, cache, since, today, interval_dates):
    new, start = [], 0
    while True:
        page = client.search_activities(start=start, limit=100, start_date=since, end_date=today)
        if not page:
            break
        new.extend(page)
        if len(page) < 100:
            break
        start += 100
    if new and "activityType" not in new[0]:
        print(f"garmin: activity records have unexpected fields: {sorted(new[0])}")
    for raw in new:
        a = normalize_activity(raw)
        a["laps"] = (cache.get(a["id"]) or {}).get("laps")
        cache[a["id"]] = a
    lap_failures = 0
    for a in cache.values():
        if a["sport"] in ("Run", "TrailRun", "VirtualRun") and a["date"] in interval_dates and a.get("laps") is None:
            try:
                a["laps"] = laps_from(client.get(f"/activity-service/activity/{a['garmin_id']}/splits"))
            except Exception as e:
                lap_failures += 1
                if lap_failures == 1:
                    print(f"garmin: lap splits unavailable ({e}); interval paces will be skipped")
    print(f"garmin: {len(new)} activities since {since}, {len(cache)} cached")
    return cache


VO2_KEYS = ("userData.vo2MaxRunning", "vo2MaxRunning", "vo2MaxValue", "vo2Max", "vO2MaxValue", "vo2max")


def vo2_from(payload):
    v = find(payload, VO2_KEYS, depth=4) if isinstance(payload, dict) else None
    try:
        return round(float(v), 1) if v else None
    except (TypeError, ValueError):
        return None


def maxmet_points(payload):
    """(date, value) pairs from a metrics-service maxmet response."""
    out = []
    for rec in payload if isinstance(payload, list) else [payload]:
        if not isinstance(rec, dict):
            continue
        g = rec.get("generic") or rec
        d = g.get("calendarDate") or rec.get("calendarDate")
        v = vo2_from({"vo2MaxValue": g.get("vo2MaxPreciseValue") or g.get("vo2MaxValue")})
        if d and v:
            out.append((str(d)[:10], v))
    return out


def sync_vo2max(client, cache, today, weeks=12):
    """Running VO2 max into the wellness rows. The activity list doesn't carry it, so try
    the metrics service, then the profile settings (today's value only)."""
    start = (today - timedelta(weeks=weeks)).isoformat()
    found = []
    for path in (f"/metrics-service/metrics/maxmet/daily/{start}/{today.isoformat()}",
                 f"/metrics-service/metrics/maxmet/latest/{today.isoformat()}"):
        try:
            payload = client.get(path)
        except Exception as e:
            print(f"garmin: {path.split('/')[4]} maxmet unavailable: {e}")
            continue
        found = maxmet_points(payload)
        if found:
            break
        sample = payload[0] if isinstance(payload, list) and payload else payload
        print(f"garmin: no VO2 max in {path.split('/')[4]} maxmet; fields: "
              f"{key_names(sample) if isinstance(sample, dict) else type(payload).__name__}")
    if not found:
        try:
            profile = client.get_user_profile_settings()
            v = vo2_from(profile)
            if v:
                found = [(today.isoformat(), v)]
            elif isinstance(profile, dict):
                print(f"garmin: no VO2 max in profile settings; fields: {key_names(profile, depth=3)}")
        except Exception as e:
            print(f"garmin: profile settings failed: {e}")
    for d, v in found:
        cache.setdefault(d, {"date": d})["vo2max"] = v
    points = sum(1 for r in cache.values() if r.get("vo2max"))
    print(f"garmin: {len(found)} VO2 max readings fetched; {points} days cached")
    return cache


def client_session():
    """Context manager yielding a Personal API client, or None without a key."""
    from contextlib import contextmanager

    @contextmanager
    def session():
        key = os.environ.get("GARMIN_PERSONAL_API_KEY")
        if not key:
            print("garmin: no GARMIN_PERSONAL_API_KEY, skipping")
            yield None
            return
        from garmin_personal_api.auth import PersonalApiAuthenticator
        from garmin_personal_api.client import GarminPersonalApiClient

        with PersonalApiAuthenticator() as auth:
            token = auth.obtain_token(key)
        with GarminPersonalApiClient(token.access_token) as client:
            yield client
    return session()


def sync(client, cache, today, days=45):
    """cache: dict date -> wellness row. Refetches the last 3 days, fills gaps up to `days` back."""
    missing = [d for d in (today - timedelta(days=i) for i in range(days))
               if cache.get(d.isoformat(), {}).get("resting_hr") is None]
    start = min(missing + [today - timedelta(days=2)])
    fresh = fetch(client, start, today)
    cache.update(fresh)
    coverage = {m: sum(r.get(m) is not None for r in fresh.values())
                for m in ("resting_hr", "hrv", "hrv_status", "sleep_score", "sleep_h", "body_battery_high")}
    print(f"garmin: {len(fresh)} days from {start} to {today}; days with each metric: {coverage}")
    return cache
