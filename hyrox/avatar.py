"""The bison avatar: today's mood, what he's doing, and the gear he has earned.

Mood is an even blend of two 0-100 scores:
  readiness  last night's HRV and resting HR against their 7-day baselines, sleep score
             and Body Battery
  load       acute:chronic ratio and form (TSB) from the training-load curves
Either half can be missing (no Garmin yet, or under 3 weeks of activities); the other
then decides alone. With neither, he defaults to "ready".
"""
from datetime import date, timedelta

MOODS = [(35, "exhausted"), (55, "tired"), (75, "ready"), (101, "fired_up")]
MOOD_LABEL = {"exhausted": "Exhausted", "tired": "Tired", "ready": "Ready", "fired_up": "Fired up"}

ACTION = {"intervals": "sprint", "strength": "sled", "easy_skill": "skill", "long": "jog",
          "easy": "jog", "sim": "sim", "benchmark": "sim", "race": "race", "rest": "rest"}

# (key, name, week it unlocks)
GEAR = [("headband", "Headband", 2), ("wraps", "Wrist wraps", 4), ("bib", "Race bib", 8)]
GEAR_COMPLIANCE = 0.7        # share of past sessions done to keep earning gear
MIN_LOAD_HISTORY = 21        # days of activities before the load half counts


def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def baseline(wellness, d, key):
    vals = [wellness[x][key] for x in ((d - timedelta(days=k)).isoformat() for k in range(1, 8))
            if x in wellness and wellness[x].get(key)]
    return sum(vals) / len(vals) if len(vals) >= 4 else None


def readiness_score(wellness, today):
    """(score or None, factors). Uses today's row, or yesterday's if today hasn't synced."""
    d = next((x for x in (today, today - timedelta(days=1)) if x.isoformat() in wellness), None)
    if d is None:
        return None, []
    w, parts = wellness[d.isoformat()], []
    hrv_base = baseline(wellness, d, "hrv")
    if w.get("hrv") and hrv_base:
        ratio = w["hrv"] / hrv_base
        # 80% of baseline or below -> 0, 110% or above -> 100
        parts.append(("hrv", f"HRV {round(ratio * 100)}% of normal", clamp((ratio - 0.8) / 0.3 * 100), ratio))
    rhr_base = baseline(wellness, d, "resting_hr")
    if w.get("resting_hr") and rhr_base:
        delta = w["resting_hr"] - rhr_base
        # 2 bpm under baseline -> 100, on baseline -> 75, 6 bpm over -> 0
        parts.append(("rhr", f"Resting HR {delta:+.0f} bpm", clamp(75 - delta * 12.5), delta))
    if w.get("sleep_score") is not None:
        parts.append(("sleep", f"Sleep score {w['sleep_score']}", clamp((w["sleep_score"] - 40) * 2), w["sleep_score"]))
    if w.get("body_battery_high") is not None:
        bb = w["body_battery_high"]
        parts.append(("battery", f"Body Battery {bb}", clamp((bb - 30) / 60 * 100), bb))
    if not parts:
        return None, []
    return sum(p[2] for p in parts) / len(parts), parts


def load_score(load_rows, history_days):
    if not load_rows or history_days < MIN_LOAD_HISTORY:
        return None, []
    cur, parts = load_rows[-1], []
    if cur.get("acwr") is not None:
        # 1.0 or lower -> 80+, 1.3 -> 35, 1.5 -> 5
        parts.append(("acwr", f"Load ratio {cur['acwr']}", clamp(80 - (cur["acwr"] - 1.0) * 150), cur["acwr"]))
    if cur.get("tsb") is not None:
        # form +5 or fresher -> 100, -30 -> 0
        parts.append(("form", f"Form {cur['tsb']:+.0f}", clamp((cur["tsb"] + 30) / 35 * 100), cur["tsb"]))
    if not parts:
        return None, []
    return sum(p[2] for p in parts) / len(parts), parts


def mood_for(score):
    return next(m for limit, m in MOODS if score < limit)


def gear(sessions, today, week):
    past = [s for s in sessions if s["date"] < today.isoformat() and s["status"] in ("done", "missed")]
    done = sum(s["status"] == "done" for s in past)
    compliance = done / len(past) if past else None
    out = []
    for key, name, wk in GEAR:
        if week < wk:
            earned, note = False, f"Unlocks week {wk}"
        elif compliance is not None and compliance < GEAR_COMPLIANCE:
            earned, note = False, f"Needs {round(GEAR_COMPLIANCE * 100)}% of sessions done (now {round(compliance * 100)}%)"
        else:
            earned, note = True, f"Earned week {wk}"
        out.append({"key": key, "name": name, "week": wk, "earned": earned, "note": note})
    race = next((s for s in sessions if s["kind"] == "race"), None)
    if race and (race["status"] == "done" or race["date"] < today.isoformat()):
        out.append({"key": "medal", "name": "Finisher medal", "week": None, "earned": True, "note": "Race done"})
    return out, {"done": done, "due": len(past), "compliance": None if compliance is None else round(compliance, 2)}


def lines(mood, action, session, factors, gear_rows, week, total_weeks, plan_race):
    out = []
    hard = bool(session and session.get("hard"))
    title = session["title"] if session else None
    out.append({
        "exhausted": "Running on fumes today. Everything easy, nothing heroic.",
        "tired": "Bit heavy-legged today. Hold the slow end of every target.",
        "ready": "Feeling good. Let's get today done properly.",
        "fired_up": "Fully charged. Let me at it!",
    }[mood])
    f = {k: v for k, _, _, v in factors}
    if "hrv" in f and f["hrv"] < 0.85:
        out.append(f"HRV is {round(f['hrv'] * 100)}% of normal. My nervous system wants a quiet day.")
    if "rhr" in f and f["rhr"] >= 5:
        out.append(f"Resting HR is up {round(f['rhr'])} bpm. Something's taxing me.")
    if "sleep" in f and f["sleep"] < 50:
        out.append(f"Sleep score {f['sleep']}. A nap would be a training session today.")
    if "battery" in f and f["battery"] >= 85:
        out.append(f"Body Battery hit {f['battery']}. Charged up!")
    if "acwr" in f and f["acwr"] > 1.3:
        out.append(f"Load ratio is {f['acwr']}. That's a spike, so easy days stay easy.")
    if not factors:
        out.append("No Garmin data yet, so I'm guessing how I feel.")

    if action == "race":
        out.append(f"Race day. {plan_race['target'].removesuffix(':00')} is out there. Go get it.")
    elif action == "recover":
        out.append(f"{title} is done. Refuel and put the feet up.")
    elif action == "rest" or not session:
        out.append("Rest day. Feet up, a good book, maybe a nap. That's where the gains land.")
    elif hard and mood in ("exhausted", "tired"):
        out.append(f"Today is {title}, but my legs are toast. Cut reps if HR drifts.")
    else:
        out.append({
            "sprint": f"Intervals: {title}. Hit the pace, not a hero pace.",
            "sled": f"Sled day: {title}. Low hips, short fast steps.",
            "skill": "Wall balls in sets of 25 with 10 s breaks. No long stall at 75 this time.",
            "jog": f"{title}. Conversational pace, nose breathing if you can.",
            "sim": f"Sim day: {title}. Practise the transitions, not just the stations.",
        }.get(action, f"Today: {title}."))
    nxt = next((g for g in gear_rows if not g["earned"]), None)
    progress = f"Week {week} of {total_weeks}."
    if nxt:
        progress += f" Next gear: {nxt['name'].lower()} ({nxt['note'][0].lower() + nxt['note'][1:]})."
    out.append(progress)
    return out


def avatar(plan, sessions, wellness, load_rows, history_days, today):
    r_score, r_parts = readiness_score(wellness, today)
    l_score, l_parts = load_score(load_rows, history_days)
    halves = [s for s in (r_score, l_score) if s is not None]
    score = sum(halves) / len(halves) if halves else None
    mood = mood_for(score) if score is not None else "ready"

    session = next((s for s in sessions if s["date"] == today.isoformat()), None)
    if session is None:
        action = "rest"
    elif session["status"] == "done" and session["kind"] != "race":
        action = "recover"
    else:
        action = ACTION.get(session["kind"], "jog")
    cur = next((s for s in sessions if s["date"] >= today.isoformat()), sessions[-1])
    total_weeks = max(s["week"] for s in sessions)
    gear_rows, progress = gear(sessions, today, cur["week"])
    factors = r_parts + l_parts
    return {
        "mood": mood,
        "mood_label": MOOD_LABEL[mood],
        "score": None if score is None else round(score),
        "readiness_score": None if r_score is None else round(r_score),
        "load_score": None if l_score is None else round(l_score),
        "factors": [{"key": k, "label": label, "score": round(s)} for k, label, s, _ in factors],
        "action": action,
        "session": session["title"] if session else "Rest day",
        "hard": bool(session and session["hard"]),
        "gear": gear_rows,
        "progress": progress,
        "lines": lines(mood, action, session, factors, gear_rows, cur["week"], total_weeks, plan["race"]),
    }
