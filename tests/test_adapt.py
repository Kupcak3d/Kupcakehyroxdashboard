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
            return [{"calendarDate": "2026-10-22", "restingHeartRate": 49, "bodyBatteryHighestValue": 88}]

        def get_daily_sleep_summaries(self, s, e):
            return {"dailySleepSummaries": [{"calendarDate": "2026-10-22", "sleepTimeSeconds": 27000,
                                              "sleepScores": {"overall": {"value": 81}}}]}

        def get_daily_hrv_summaries(self, s, e):
            return {"hrvSummaries": [{"calendarDate": "2026-10-22", "lastNightAvg": 58, "status": "balanced"}]}

    rows = fetch(Fake(), date(2026, 10, 20), date(2026, 10, 22))
    r = rows["2026-10-22"]
    assert (r["resting_hr"], r["body_battery_high"], r["sleep_score"], r["sleep_h"], r["hrv"], r["hrv_status"]) == \
        (49, 88, 81, 7.5, 58, "BALANCED")
