"""Load plan/plan.json and expand it into dated sessions."""
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAY_OFFSET = {"mon": -1, "tue": 0, "wed": 1, "thu": 2, "fri": 3, "sat": 4, "sun": 5}
HARD_KINDS = {"intervals", "sim", "race", "benchmark"}
RUN_KINDS = {"intervals", "easy_skill", "long", "easy", "sim", "race"}


def parse_time(s):
    """'5:05' -> 305 seconds, '1:20:00' -> 4800."""
    secs = 0
    for part in str(s).split(":"):
        secs = secs * 60 + float(part)
    return int(round(secs))


def fmt_time(secs):
    secs = int(round(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def load_plan(path=None):
    return json.loads(Path(path or ROOT / "plan" / "plan.json").read_text())


def phase_for(plan, week):
    for p in plan["phases"]:
        if week in p["weeks"]:
            return p["name"]
    return None


def expand_sessions(plan):
    """Every planned session with a concrete date, sorted by date."""
    out = []
    for wk in plan["weeks"]:
        tue = date.fromisoformat(wk["tuesday"])
        for s in wk["sessions"]:
            d = tue + timedelta(days=DAY_OFFSET[s["day"]])
            out.append({
                **s,
                "date": d.isoformat(),
                "week": wk["week"],
                "phase": phase_for(plan, wk["week"]),
                "hard": s["kind"] in HARD_KINDS,
            })
    return sorted(out, key=lambda s: s["date"])


def week_bounds(plan):
    """[(week, monday, sunday)] using Mon–Sun weeks around each Tuesday."""
    res = []
    for wk in plan["weeks"]:
        mon = date.fromisoformat(wk["tuesday"]) - timedelta(days=1)
        res.append((wk["week"], mon, mon + timedelta(days=6)))
    return res
