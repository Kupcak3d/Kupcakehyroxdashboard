"""Turn the static plan plus what actually happened into an adjusted plan.

Every rule here comes from the plan doc or standard load-management practice, and
each change records the reason so the dashboard can show why a session moved.
"""
from collections import defaultdict
from datetime import date, timedelta

from .plan import RUN_KINDS, fmt_time, parse_time, week_bounds

RUN_SPORTS = {"Run", "TrailRun", "VirtualRun"}
WORK_LAP_MAX_PACE = 330      # laps faster than 5:30/km count as interval reps
LOW_READINESS = 40
RHR_ELEVATED = 5             # bpm over the 7-day baseline
HRV_DROP = 0.85              # last-night HRV below 85% of the 7-day baseline
SLEEP_POOR = 50              # Garmin sleep score
PACE_STEP = 5                # s/km per calibration step
PACE_LIMIT = 10              # never move interval targets more than this from the plan
ACWR_HIGH, ACWR_CAUTION = 1.5, 1.3
FATIGUE_FACTOR = 1.10        # fresh station time -> race-day estimate


def pace_s(dist_km, secs):
    return secs / dist_km if dist_km else None


# ---------- session status ----------

def match_status(sessions, activities, today):
    by_day = defaultdict(list)
    for a in activities:
        by_day[a["date"]].append(a)
    for s in sessions:
        acts = by_day.get(s["date"], [])
        if s["kind"] in RUN_KINDS - {"sim", "race"}:
            acts = [a for a in acts if a["sport"] in RUN_SPORTS]
        s["activities"] = [a["id"] for a in acts]
        s["actual_km"] = round(sum(a["distance_km"] for a in acts if a["sport"] in RUN_SPORTS), 1)
        d = s["date"]
        if s["kind"] == "rest":
            s["status"] = "rest"
        elif s.get("completed"):
            s["status"] = "done"
        elif acts:
            s["status"] = "done"
        elif d < today.isoformat():
            s["status"] = "missed" if activities else "no_data"
        elif d == today.isoformat():
            s["status"] = "today"
        else:
            s["status"] = "upcoming"
        s.setdefault("notes", [])
    return by_day


# ---------- interval pace calibration ----------

def interval_paces(sessions, by_day):
    """Attach actual rep pace (s/km) and delta vs target to completed interval sessions."""
    for s in sessions:
        if s["kind"] != "intervals" or s["status"] != "done":
            continue
        laps = [l for a in by_day[s["date"]] for l in (a.get("laps") or [])
                if l["distance_m"] >= 300 and l["moving_s"]
                and l["moving_s"] / (l["distance_m"] / 1000) < WORK_LAP_MAX_PACE]
        if not laps:
            continue
        dist = sum(l["distance_m"] for l in laps) / 1000
        actual = sum(l["moving_s"] for l in laps) / dist
        target = parse_time(s["intervals"]["pace"])
        s["actual_pace"] = fmt_time(actual)
        s["pace_delta"] = round(actual - target)
        s["reps_done"] = len(laps)


def calibrate_intervals(sessions, today, changes):
    done = [s for s in sessions if s.get("pace_delta") is not None]
    if len(done) < 2:
        return 0
    last2 = [s["pace_delta"] for s in done[-2:]]
    if all(d <= -PACE_STEP for d in last2):
        offset, why = -PACE_STEP, "beat target pace by 5+ s/km in the last two interval sessions"
    elif all(d >= PACE_STEP + 3 for d in last2):
        offset, why = PACE_STEP, "missed target pace by 8+ s/km in the last two interval sessions"
    else:
        return 0
    for s in sessions:
        if s["kind"] != "intervals" or s["date"] <= today.isoformat() or s["week"] >= 10:
            continue
        plan_pace = parse_time(s["intervals"]["pace"])
        new = max(plan_pace - PACE_LIMIT, min(plan_pace + PACE_LIMIT, plan_pace + offset))
        s["adjusted_pace"] = fmt_time(new)
        s["notes"].append(f"Target pace {s['intervals']['pace']} → {fmt_time(new)}/km")
        changes.append({"date": s["date"], "session": s["title"],
                        "change": f"Rep pace {s['intervals']['pace']} → {fmt_time(new)}/km", "reason": why})
    return offset


# ---------- readiness ----------

def readiness_flags(wellness, today, days=14):
    """Per-day low-recovery flag with the reasons behind it."""
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        w = wellness.get(d.isoformat())
        if not w:
            continue
        reasons = []
        if w.get("readiness") is not None and w["readiness"] < LOW_READINESS:
            reasons.append(f"training readiness {w['readiness']}")
        if (w.get("hrv_status") or "").upper() in {"LOW", "POOR"}:
            reasons.append(f"HRV status {w['hrv_status'].lower()}")
        base = [wellness[x]["resting_hr"] for x in
                ((d - timedelta(days=k)).isoformat() for k in range(1, 8))
                if x in wellness and wellness[x].get("resting_hr")]
        if w.get("resting_hr") and len(base) >= 4 and w["resting_hr"] >= sum(base) / len(base) + RHR_ELEVATED:
            reasons.append(f"resting HR {w['resting_hr']} (baseline {round(sum(base) / len(base))})")
        hrv_base = [wellness[x]["hrv"] for x in
                    ((d - timedelta(days=k)).isoformat() for k in range(1, 8))
                    if x in wellness and wellness[x].get("hrv")]
        if w.get("hrv") and len(hrv_base) >= 4 and w["hrv"] < HRV_DROP * sum(hrv_base) / len(hrv_base):
            reasons.append(f"HRV {w['hrv']} ms (baseline {round(sum(hrv_base) / len(hrv_base))})")
        if w.get("sleep_score") is not None and w["sleep_score"] < SLEEP_POOR:
            reasons.append(f"sleep score {w['sleep_score']}")
        out.append({"date": d.isoformat(), "low": bool(reasons), "reasons": reasons})
    return out


def apply_readiness(sessions, flags, today, changes, alerts):
    by_date = {f["date"]: f for f in flags}
    t, y = by_date.get(today.isoformat()), by_date.get((today - timedelta(days=1)).isoformat())
    if not t or not t["low"]:
        return
    window = {(today + timedelta(days=i)).isoformat() for i in range(3)}
    nxt = next((s for s in sessions if s["date"] in window and s["hard"]
                and s["kind"] != "race" and s["status"] in ("today", "upcoming")), None)
    if y and y["low"]:
        alerts.append({"level": "serious", "text": "Two low-recovery days in a row: " + "; ".join(t["reasons"])})
        if nxt:
            nxt["original_title"] = nxt["title"]
            nxt["title"] = "Easy run 40–50 min @ 6:15–6:45/km"
            nxt["kind"], nxt["hard"], nxt["adjusted"] = "easy", False, True
            nxt["run_km"] = 7
            nxt["notes"].append("Swapped to easy: two low-recovery days running (plan rule)")
            changes.append({"date": nxt["date"], "session": nxt["original_title"],
                            "change": "Swapped for an easy run",
                            "reason": "Low recovery two days running: " + "; ".join(t["reasons"])})
    else:
        alerts.append({"level": "warning", "text": "Low recovery today: " + "; ".join(t["reasons"])})
        if nxt:
            nxt["notes"].append("Recovery is low today. Hold the slow end of the target and cut reps if HR drifts.")


# ---------- load ----------

def apply_load(sessions, load_rows, today, history_days, changes, alerts):
    if not load_rows or history_days < 21:
        return
    cur = load_rows[-1]
    acwr = cur.get("acwr")
    if acwr is None:
        return
    if acwr > ACWR_HIGH:
        alerts.append({"level": "serious", "text": f"Load spike: acute:chronic ratio {acwr} (keep under {ACWR_CAUTION})."})
        end = (today + timedelta(days=7)).isoformat()
        for s in sessions:
            if s["kind"] in ("long", "easy_skill") and today.isoformat() < s["date"] <= end:
                new = round(s["run_km"] * 0.8, 1)
                s["notes"].append(f"Run trimmed {s['run_km']} → {new} km (load spike)")
                changes.append({"date": s["date"], "session": s["title"],
                                "change": f"Run distance {s['run_km']} → {new} km",
                                "reason": f"Acute:chronic load ratio {acwr} is above {ACWR_HIGH}"})
                s["run_km"], s["adjusted"] = new, True
    elif acwr > ACWR_CAUTION:
        alerts.append({"level": "warning", "text": f"Load is climbing fast (acute:chronic {acwr}). Keep easy days truly easy."})


# ---------- easy pace, missed sessions, volume ----------

def check_easy_pace(sessions, by_day, alerts, plan):
    floor = parse_time(plan["athlete"]["easy_pace"]["min"])
    paces = []
    for s in sessions:
        if s["kind"] in ("long", "easy_skill", "easy") and s["status"] == "done":
            runs = [a for a in by_day[s["date"]] if a["sport"] in RUN_SPORTS and a["distance_km"] >= 3]
            if runs:
                p = pace_s(sum(a["distance_km"] for a in runs), sum(a["moving_s"] for a in runs))
                s["actual_pace"] = fmt_time(p)
                paces.append(p)
    recent = paces[-3:]
    if len(recent) == 3 and sum(recent) / 3 < floor - 10:
        alerts.append({"level": "warning", "text": f"Easy runs are averaging {fmt_time(sum(recent) / 3)}/km. "
                       f"Slow to {plan['athlete']['easy_pace']['min']}–{plan['athlete']['easy_pace']['max']} so Tuesdays and Saturdays stay quality."})


def check_missed(sessions, today, alerts):
    recent = [s for s in sessions if s["status"] == "missed" and s["hard"]
              and (today - date.fromisoformat(s["date"])).days <= 3]
    for s in recent:
        alerts.append({"level": "warning", "text": f"Missed {s['title']} ({s['date']}). Don't stack it onto the next "
                       "hard day; carry on with the plan as written."})


def weekly_volume(plan, sessions, activities, today, alerts):
    rows = []
    for wk, mon, sun in week_bounds(plan):
        planned = round(sum(s["run_km"] for s in sessions if s["week"] == wk), 1)
        actual = round(sum(a["distance_km"] for a in activities if a["sport"] in RUN_SPORTS
                           and mon.isoformat() <= a["date"] <= sun.isoformat()), 1)
        rows.append({"week": wk, "start": mon.isoformat(), "planned_km": planned,
                     "actual_km": actual if mon <= today else None, "complete": sun < today})
    done = [r for r in rows if r["complete"]]
    if done and activities:
        last = done[-1]
        ratio = last["actual_km"] / last["planned_km"] if last["planned_km"] else 1
        if ratio < 0.8:
            alerts.append({"level": "warning", "text": f"Week {last['week']} ran {last['actual_km']} of {last['planned_km']} km. "
                           "Don't add the missing km to this week; resume the planned ramp."})
        elif ratio > 1.15:
            alerts.append({"level": "warning", "text": f"Week {last['week']} ran {last['actual_km']} km vs {last['planned_km']} planned. "
                           "Extra easy km raise injury risk more than they help."})
    return rows


# ---------- stations & projection ----------

def station_summary(plan, logs):
    rows = []
    for st in plan["stations"]:
        target = parse_time(st["target"])
        mine = [l for l in logs if l["station"] == st["key"] and l["full_distance"]]
        latest = mine[-1] if mine else None
        if latest:
            est = latest["seconds"] * (FATIGUE_FACTOR if latest["fresh"] else 1)
            basis = f"logged {latest['date']}" + (" (fresh, +10%)" if latest["fresh"] else "")
        elif st.get("benchmark"):
            est = parse_time(st["benchmark"]) * FATIGUE_FACTOR
            basis = "Oct 16 benchmark (fresh, +10%)"
        else:
            est, basis = target, "no data yet, using target"
        rows.append({"key": st["key"], "name": st["name"], "standard": st["standard"],
                     "target": st["target"], "benchmark": st.get("benchmark"),
                     "latest": fmt_time(latest["seconds"]) if latest else None,
                     "latest_date": latest["date"] if latest else None,
                     "best": fmt_time(min(l["seconds"] for l in mine)) if mine else None,
                     "estimate_s": round(est), "estimate": fmt_time(est), "basis": basis,
                     "gap_pct": round((est - target) / target * 100, 1), "logs": len(mine)})
    return rows


def focus_stations(rows, n=2):
    behind = sorted((r for r in rows if r["gap_pct"] > 0), key=lambda r: -r["gap_pct"])
    return behind[:n]


def apply_focus(sessions, focus, today, changes):
    if not focus:
        return
    nxt = next((s for s in sessions if s["kind"] == "easy_skill" and s["date"] >= today.isoformat()), None)
    if nxt:
        names = ", ".join(f"{r['name']} ({r['estimate']} vs {r['target']})" for r in focus)
        nxt["notes"].append(f"Skill focus: {names}")
        changes.append({"date": nxt["date"], "session": nxt["title"], "change": f"Skill focus on {names}",
                        "reason": "Furthest behind race target"})


def run_row(plan, logs, interval_deltas):
    """The race's 8 x 1 km as a stations-table row: a logged full 8 km run time if
    there is one, otherwise 8 km at target pace nudged by interval results."""
    base = (parse_time(plan["race"]["run_pace"]["min"]) + parse_time(plan["race"]["run_pace"]["max"])) / 2
    drift = 0
    if interval_deltas:
        drift = max(-10, min(15, sum(interval_deltas[-3:]) / len(interval_deltas[-3:])))
    target = 8 * base
    mine = [l for l in logs if l["station"] == "runs" and l["full_distance"]]
    latest = mine[-1] if mine else None
    if latest:
        est = latest["seconds"] * (FATIGUE_FACTOR if latest["fresh"] else 1)
        basis = f"logged {latest['date']}" + (" (fresh, +10%)" if latest["fresh"] else "")
    else:
        est = 8 * (base + drift)
        basis = f"8 km at {fmt_time(base + drift)}/km" + (" (from interval results)" if drift else " (target pace)")
    return {"key": "runs", "name": "Running", "standard": "8 x 1 km", "target": fmt_time(target),
            "latest": fmt_time(latest["seconds"]) if latest else None,
            "latest_date": latest["date"] if latest else None,
            "best": fmt_time(min(l["seconds"] for l in mine)) if mine else None,
            "estimate_s": round(est), "estimate": fmt_time(est), "basis": basis,
            "gap_pct": round((est - target) / target * 100, 1), "logs": len(mine)}


def projection(plan, stations, run):
    runs = run["estimate_s"]
    run_pace = runs / 8
    st = sum(r["estimate_s"] for r in stations)
    rox = parse_time(plan["roxzone_target"])
    total = runs + st + rox
    target = parse_time(plan["race"]["target"])
    return {"total": fmt_time(total), "total_s": round(total), "target": plan["race"]["target"],
            "delta_s": round(total - target), "runs": fmt_time(runs), "run_pace": fmt_time(run_pace),
            "stations": fmt_time(st), "roxzone": plan["roxzone_target"]}


# ---------- entry point ----------

def adapt(plan, sessions, activities, wellness, logs, load_rows, today):
    changes, alerts = [], []
    by_day = match_status(sessions, activities, today)
    interval_paces(sessions, by_day)
    offset = calibrate_intervals(sessions, today, changes)
    flags = readiness_flags(wellness, today)
    apply_readiness(sessions, flags, today, changes, alerts)
    days = (today - date.fromisoformat(min(a["date"] for a in activities))).days if activities else 0
    apply_load(sessions, load_rows, today, days, changes, alerts)
    check_easy_pace(sessions, by_day, alerts, plan)
    check_missed(sessions, today, alerts)
    weeks = weekly_volume(plan, sessions, activities, today, alerts)
    stations = station_summary(plan, logs)
    focus = focus_stations(stations)
    apply_focus(sessions, focus, today, changes)
    deltas = [s["pace_delta"] for s in sessions if s.get("pace_delta") is not None]
    run = run_row(plan, logs, deltas)
    return {
        "sessions": sessions, "changes": changes, "alerts": alerts, "readiness": flags,
        # Running leads the table like it leads the race, but isn't a Thursday skill focus.
        "weeks": weeks, "stations": [run] + stations, "focus": [f["key"] for f in focus],
        "projection": projection(plan, stations, run),
    }
