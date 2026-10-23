"""Pull activities from the Strava API using a long-lived refresh token."""
import os
import time

import requests

API = "https://www.strava.com/api/v3"
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def access_token():
    r = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def normalize(a):
    return {
        "id": a["id"],
        "source": "strava",
        "date": a["start_date_local"][:10],
        "start": a["start_date_local"],
        "sport": a.get("sport_type") or a.get("type"),
        "name": a.get("name", ""),
        "distance_km": round(a.get("distance", 0) / 1000, 2),
        "moving_s": a.get("moving_time", 0),
        "avg_hr": a.get("average_heartrate"),
        "max_hr": a.get("max_heartrate"),
        "suffer_score": a.get("suffer_score"),
    }


def fetch_activities(after_epoch, token):
    out, page = [], 1
    while True:
        r = requests.get(f"{API}/athlete/activities", headers={"Authorization": f"Bearer {token}"},
                         params={"after": int(after_epoch), "per_page": 100, "page": page}, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            return out
        out.extend(normalize(a) for a in batch)
        page += 1


def fetch_laps(activity_id, token):
    r = requests.get(f"{API}/activities/{activity_id}/laps",
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return [{"distance_m": l.get("distance", 0), "moving_s": l.get("moving_time", 0),
             "avg_hr": l.get("average_heartrate")} for l in r.json()]


def sync(cache, since_date, interval_dates):
    """Merge new activities into cache (dict keyed by id) and attach laps for interval-day runs."""
    if not os.environ.get("STRAVA_REFRESH_TOKEN"):
        print("strava: no credentials, skipping")
        return cache
    token = access_token()
    latest = max((a["start"] for a in cache.values()), default=None)
    after = time.mktime(time.strptime(latest[:10] if latest else since_date, "%Y-%m-%d")) - 3 * 86400
    new = fetch_activities(after, token)
    for a in new:
        old = cache.get(str(a["id"]), {})
        cache[str(a["id"])] = {**a, "laps": old.get("laps")}
    for a in cache.values():
        if a["sport"] in RUN_TYPES and a["date"] in interval_dates and a.get("laps") is None:
            a["laps"] = fetch_laps(a["id"], token)
    print(f"strava: {len(new)} new/updated activities, {len(cache)} cached")
    return cache
