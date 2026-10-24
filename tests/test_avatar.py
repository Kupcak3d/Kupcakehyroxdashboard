from datetime import date, timedelta

from hyrox.adapt import adapt
from hyrox.avatar import avatar
from hyrox.load import daily_loads, series
from hyrox.plan import expand_sessions, load_plan

from .test_adapt import act

PLAN = load_plan()


def run(activities=(), wellness=None, today="2026-10-27"):
    t = date.fromisoformat(today)
    activities = list(activities)
    rows = series(daily_loads(activities, 190, 55), t - timedelta(days=60), t)
    res = adapt(PLAN, expand_sessions(PLAN), activities, wellness or {}, [], rows, t)
    days = (t - date.fromisoformat(min(a["date"] for a in activities))).days if activities else 0
    return avatar(PLAN, res["sessions"], wellness or {}, rows, days, t)


def week_of(today, **today_row):
    """Seven steady baseline days, then today's numbers."""
    t = date.fromisoformat(today)
    w = {(t - timedelta(days=i)).isoformat(): {"hrv": 60, "resting_hr": 50, "sleep_score": 75,
                                               "body_battery_high": 70} for i in range(1, 8)}
    w[today] = {"hrv": 60, "resting_hr": 50, "sleep_score": 75, "body_battery_high": 70, **today_row}
    return w


def test_no_data_defaults_to_ready():
    a = run()
    assert a["mood"] == "ready" and a["score"] is None
    assert any("No Garmin data" in line for line in a["lines"])


def test_great_recovery_is_fired_up_and_bad_recovery_is_exhausted():
    good = run(wellness=week_of("2026-10-27", hrv=70, resting_hr=48, sleep_score=92, body_battery_high=95))
    assert good["mood"] == "fired_up"
    bad = run(wellness=week_of("2026-10-27", hrv=45, resting_hr=57, sleep_score=40, body_battery_high=30))
    assert bad["mood"] == "exhausted"
    assert any("HRV" in line for line in bad["lines"])


def test_load_spike_drags_mood_down():
    t = date.fromisoformat("2026-10-27")
    light = [act((t - timedelta(days=i)).isoformat(), km=5) for i in range(10, 40, 3)]
    heavy = [act((t - timedelta(days=i)).isoformat(), km=16, secs=16 * 330) for i in range(0, 7)]
    w = week_of("2026-10-27", hrv=66, sleep_score=85, body_battery_high=85)
    rested = run(light, w)
    spiked = run(light + heavy, w)
    assert spiked["load_score"] < rested["load_score"]
    assert spiked["mood"] in ("exhausted", "tired")


def test_action_follows_todays_session():
    assert run(today="2026-10-27")["action"] == "sprint"     # Tuesday intervals
    assert run(today="2026-10-28")["action"] == "sled"       # Wednesday strength + sleds
    assert run(today="2026-10-29")["action"] == "skill"      # Thursday wall balls / burpees
    assert run(today="2026-10-31")["action"] == "sim"        # Saturday sim
    assert run(today="2026-11-01")["action"] == "jog"        # Sunday long run
    assert run(today="2026-10-30")["action"] == "rest"       # Friday


def test_gear_unlocks_by_week_and_needs_consistency():
    g = {x["key"]: x for x in run(today="2026-11-04")["gear"]}   # week 4, no activity data
    assert g["headband"]["earned"] and g["wraps"]["earned"] and not g["bib"]["earned"]
    # Week 4 with only one run logged: most past sessions missed, so gear stays locked
    lazy = {x["key"]: x for x in run([act("2026-10-13")], today="2026-11-04")["gear"]}
    assert not lazy["wraps"]["earned"] and "%" in lazy["wraps"]["note"]
