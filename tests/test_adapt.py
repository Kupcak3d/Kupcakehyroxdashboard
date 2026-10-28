from datetime import date, timedelta

from hyrox.adapt import adapt
from hyrox.load import daily_loads, series
from hyrox.plan import expand_sessions, load_plan
from hyrox.stations import parse_issue_body, to_log

PLAN = load_plan()


def run(activities, wellness=None, logs=None, today="2026-10-30"):
    t = date.fromisoformat(today)
    rows = series(daily_loads(activities, 190, 55), t - timedelta(days=60), t)
    return adapt(PLAN, expand_sessions(PLAN), activities, wellness or {}, logs or [], rows, t)


def act(d, km=8, secs=None, sport="Run", laps=None, i=[0]):
    i[0] += 1
    return {"id": i[0], "date": d, "start": d + "T07:00:00", "sport": sport, "name": "",
            "distance_km": km, "moving_s": secs or int(km * 380), "avg_hr": 140,
            "max_hr": 160, "suffer_score": None, "laps": laps}


def rep_laps(n, dist_m, pace):
    return [{"distance_m": dist_m, "moving_s": dist_m / 1000 * pace, "avg_hr": 170}] * n


def steady_history(until="2026-10-19"):
    end = date.fromisoformat(until)
    return [act((end - timedelta(days=i)).isoformat()) for i in range(0, 40, 2)]


def test_two_low_days_swaps_next_hard_session():
    w = {"2026-10-26": {"readiness": 30}, "2026-10-27": {"readiness": 25}}
    res = run(steady_history(), w, today="2026-10-27")
    tue = next(s for s in res["sessions"] if s["date"] == "2026-10-27")
    assert tue["kind"] == "easy" and tue["original_title"].startswith("8 x 800")
    assert any(a["level"] == "serious" for a in res["alerts"])


def test_one_low_day_only_warns():
    w = {"2026-10-27": {"readiness": 25}}
    res = run(steady_history(), w, today="2026-10-27")
    tue = next(s for s in res["sessions"] if s["date"] == "2026-10-27")
    assert tue["kind"] == "intervals" and tue["notes"]


def test_fast_intervals_tighten_future_targets():
    acts = steady_history() + [
        act("2026-10-13", laps=rep_laps(6, 1000, 292)),  # 4:52 vs 5:00 target
        act("2026-10-20", laps=rep_laps(5, 1200, 293)),
    ]
    res = run(acts, today="2026-10-23")
    wk3 = next(s for s in res["sessions"] if s["date"] == "2026-10-27")
    assert wk3["adjusted_pace"] == "4:45"
    race_week = next(s for s in res["sessions"] if s["date"] == "2026-12-15")
    assert "adjusted_pace" not in race_week


def test_load_spike_trims_easy_volume():
    acts = steady_history("2026-10-10") + [act(f"2026-10-{d}", km=20) for d in range(20, 24)]
    res = run(acts, today="2026-10-23")
    sun = next(s for s in res["sessions"] if s["date"] == "2026-10-25")
    assert sun["run_km"] == 8.8 and any("Load spike" in a["text"] for a in res["alerts"])


def test_station_logs_drive_focus_and_projection():
    logs = [{"issue": 1, "date": "2026-10-24", "station": "sled_pull", "seconds": 330,
             "fresh": False, "full_distance": True, "notes": ""}]
    res = run(steady_history(), logs=logs, today="2026-10-25")
    assert res["focus"][0] == "wall_balls" and "sled_pull" in res["focus"]
    assert res["projection"]["total_s"] > 4800


def test_running_row_leads_stations_and_uses_logged_time():
    res = run(steady_history(), today="2026-10-25")
    row = res["stations"][0]
    assert (row["key"], row["target"], row["estimate"]) == ("runs", "41:20", "41:20")
    assert "runs" not in res["focus"] and res["projection"]["runs"] == "41:20"
    logs = [{"issue": 2, "date": "2026-10-24", "station": "runs", "seconds": 2580,
             "fresh": False, "full_distance": True, "notes": ""}]
    res = run(steady_history(), logs=logs, today="2026-10-25")
    assert res["stations"][0]["estimate"] == "43:00" and res["projection"]["runs"] == "43:00"
    assert res["stations"][0]["gap_pct"] == 4.0


def test_issue_form_parsing():
    body = ("### Station\n\nWall balls\n\n### Time (m:ss)\n\n5:42\n\n### Date\n\n2026-10-22\n\n"
            "### Distance\n\nFull race distance\n\n### Conditions\n\nTired (in a sim or after running)\n\n"
            "### Notes\n\n_No response_")
    assert parse_issue_body(body)["notes"] is None
    log = to_log({"number": 7, "body": body, "created_at": "2026-10-23T00:00:00Z"})
    assert log == {"issue": 7, "date": "2026-10-22", "station": "wall_balls", "seconds": 342,
                   "fresh": False, "full_distance": True, "notes": ""}


def test_hrv_drop_and_poor_sleep_count_as_low_recovery():
    base = {f"2026-10-{d}": {"hrv": 60, "resting_hr": 50} for d in range(19, 26)}
    base["2026-10-26"] = {"hrv": 48, "resting_hr": 50}
    base["2026-10-27"] = {"hrv": 59, "resting_hr": 50, "sleep_score": 41}
    res = run(steady_history(), base, today="2026-10-27")
    tue = next(s for s in res["sessions"] if s["date"] == "2026-10-27")
    assert tue["kind"] == "easy"
    assert any("HRV 48" in r for f in res["readiness"] for r in f["reasons"])


def test_personal_api_mapping():
    from datetime import date
    from hyrox.garmin import fetch

    class Fake:
        def get_daily_summaries(self, s, e):
            return [{"calendarDate": "2026-10-22", "heartRate": {"minValue": 45, "restingValue": 49},
                     "bodyBattery": {"minValue": 20, "maxValue": 88}, "stress": {"avgLevel": 31}}]

        def get_daily_sleep_summaries(self, s, e):
            return {"dailySleepSummaries": [{"calendarDate": "2026-10-22", "sleepTimeSeconds": 27000,
                                              "sleepScores": {"overall": {"value": 81}}}]}

        def get_daily_hrv_summaries(self, s, e):
            return {"hrvSummaries": [{"calendarDate": "2026-10-22", "lastNightAvg": 58, "status": "balanced"}]}

    rows = fetch(Fake(), date(2026, 10, 20), date(2026, 10, 22))
    r = rows["2026-10-22"]
    assert r["stress_avg"] == 31
    assert (r["resting_hr"], r["body_battery_high"], r["sleep_score"], r["sleep_h"], r["hrv"], r["hrv_status"]) == \
        (49, 88, 81, 7.5, 58, "BALANCED")


def test_swaps_move_sessions_between_days():
    by_date = {s["date"]: s for s in expand_sessions(PLAN)}
    assert by_date["2026-10-22"]["kind"] == "sim"
    sat = by_date["2026-10-24"]
    assert sat["kind"] == "easy_skill" and sat["moved"]
    assert sat["notes"][0].startswith("Moved from Thu Oct 22")


def test_garmin_activities_normalize_and_laps():
    from datetime import date
    from hyrox.garmin import sync_activities

    class Fake:
        def search_activities(self, start, limit, start_date, end_date):
            return [{"activityId": 11, "activityName": "Intervals", "startTimeLocal": "2026-10-20 07:05:00",
                     "activityType": {"typeKey": "running"}, "distance": 10000.0, "duration": 3100.5,
                     "movingDuration": 3050.0, "averageHR": 152, "maxHR": 178},
                    {"activityId": 12, "startTimeLocal": "2026-10-21 18:00:00",
                     "activityType": {"typeKey": "strength_training"}, "duration": 3900.0}]

        def get(self, path):
            assert path == "/activity-service/activity/11/splits"
            return {"lapDTOs": [{"distance": 1200.0, "movingDuration": 352.0, "averageHR": 170}]}

    acts = sync_activities(Fake(), {}, date(2026, 9, 1), date(2026, 10, 23), {"2026-10-20"})
    run_, lift = acts["g11"], acts["g12"]
    assert (run_["sport"], run_["date"], run_["distance_km"], run_["moving_s"]) == ("Run", "2026-10-20", 10.0, 3050)
    assert run_["laps"] == [{"distance_m": 1200.0, "moving_s": 352.0, "avg_hr": 170}]
    assert (lift["sport"], lift["distance_km"], lift["laps"]) == ("WeightTraining", 0.0, None)


def test_vo2max_form_logs_feed_the_series():
    from hyrox.build import vo2max_series
    from hyrox.stations import to_vo2

    issue = lambda n, body, created: {"number": n, "body": body, "created_at": created}
    logs = [l for l in [
        to_vo2(issue(1, "### VO2 max\n\n51\n\n### Date\n\n2026-09-20", "2026-09-20T00:00:00Z")),
        to_vo2(issue(2, "### VO2 max\n\n52.4\n\n### Date\n\n_No response_", "2026-10-27T00:00:00Z")),
        to_vo2(issue(3, "### VO2 max\n\nfifty\n\n### Date\n\n_No response_", "2026-10-27T00:00:00Z")),
        to_vo2(issue(4, "### VO2 max\n\n47\n\n### Date\n\n2026-06-01", "2026-06-01T00:00:00Z")),
    ] if l]
    assert logs[1] == {"issue": 2, "date": "2026-10-27", "value": 52.4}
    assert vo2max_series(logs, date(2026, 10, 27)) == [
        {"date": "2026-09-20", "value": 51.0}, {"date": "2026-10-27", "value": 52.4}]
