"""Sync data sources, adapt the plan, and write site/data.json.

    python -m hyrox.build            # sync + build
    python -m hyrox.build --offline  # rebuild from cached data only
"""
import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import garmin, stations, strava, vo2
from .adapt import adapt
from .avatar import avatar
from .load import daily_loads, series
from .plan import ROOT, expand_sessions, load_plan

DATA = ROOT / "data"


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD) for testing")
    args = ap.parse_args(argv)

    plan = load_plan()
    tz = ZoneInfo(plan["timezone"])
    today = date.fromisoformat(args.today) if args.today else datetime.now(tz).date()
    sessions = expand_sessions(plan)
    plan_start = date.fromisoformat(sessions[0]["date"])
    history_start = plan_start - timedelta(days=60)

    acts = read_json(DATA / "activities.json", {})
    well = read_json(DATA / "wellness.json", {})
    logs = read_json(DATA / "station_logs.json", [])
    vo2_logs = read_json(DATA / "vo2max_logs.json", [])
    if not args.offline:
        interval_dates = {s["date"] for s in sessions if s["kind"] == "intervals"}
        use_strava = bool(os.environ.get("STRAVA_REFRESH_TOKEN"))
        if use_strava:
            acts = {k: a for k, a in acts.items() if a.get("source") == "strava"}
            acts = strava.sync(acts, history_start.isoformat(), interval_dates)
        try:
            with garmin.client_session() as client:
                if client:
                    well = garmin.sync(client, well, today)
                    if not use_strava:
                        # Garmin is the activity source unless Strava is configured.
                        acts = {k: a for k, a in acts.items() if a.get("source") == "garmin"}
                        acts = garmin.sync_activities(client, acts, history_start, today, interval_dates)
        except Exception as e:
            print(f"garmin: sync failed, keeping cached data: {e}")
        logs = stations.fetch_logs() or logs
        vo2_logs = stations.fetch_vo2max() or vo2_logs
        write_json(DATA / "activities.json", acts)
        write_json(DATA / "wellness.json", well)
        write_json(DATA / "station_logs.json", logs)
        write_json(DATA / "vo2max_logs.json", vo2_logs)

    activities = sorted(acts.values(), key=lambda a: a["start"])
    athlete = plan["athlete"]
    rest_hrs = [w["resting_hr"] for w in well.values() if w.get("resting_hr")]
    rest_hr = round(sum(rest_hrs[-14:]) / len(rest_hrs[-14:])) if rest_hrs else athlete["resting_hr"]
    load_rows = series(daily_loads(activities, athlete["max_hr"], rest_hr), history_start, today)

    result = adapt(plan, sessions, activities, well, logs, load_rows, today)
    history_days = (today - date.fromisoformat(activities[0]["date"])).days if activities else 0
    recent = {a["id"]: a for a in activities if a["date"] >= (today - timedelta(days=21)).isoformat()}
    out = {
        "generated_at": datetime.now(tz).isoformat(timespec="minutes"),
        "today": today.isoformat(),
        "plan": {k: plan[k] for k in ("name", "source", "race", "phases", "roxzone_target")},
        "repo": os.environ.get("GITHUB_REPOSITORY"),
        "sources": {"activities": activities[-1]["source"] if activities else None,
                    "garmin": bool(well), "station_logs": len(logs)},
        **result,
        "avatar": avatar(plan, result["sessions"], well, load_rows, history_days, today),
        "load": load_rows[-56:],
        "wellness": [well[d] for d in sorted(well) if d >= (today - timedelta(days=28)).isoformat()],
        "vo2max": vo2.summary(activities, vo2_logs, athlete["max_hr"], rest_hr, today),
        "recent_activities": sorted(recent.values(), key=lambda a: a["start"], reverse=True)[:15],
    }
    for a in out["recent_activities"]:
        a.pop("laps", None)
    write_json(ROOT / "site" / "data.json", out)
    print(f"built site/data.json for {today}: {len(result['changes'])} changes, {len(result['alerts'])} alerts")


if __name__ == "__main__":
    main()
