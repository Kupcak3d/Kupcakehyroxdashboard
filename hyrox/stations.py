"""Station results logged as GitHub issues (label: station-log) via the issue form."""
import os
import re

import requests

from .plan import parse_time

STATION_KEYS = {
    "SkiErg": "ski", "Sled push": "sled_push", "Sled pull": "sled_pull",
    "Burpee broad jumps": "bbj", "Row": "row", "Farmers carry": "farmers",
    "Sandbag lunges": "lunges", "Wall balls": "wall_balls",
}


def parse_issue_body(body):
    """Issue forms render as '### Label\\n\\nvalue' blocks."""
    fields = {}
    for m in re.finditer(r"^### (.+?)\s*\n+(.*?)(?=^### |\Z)", body or "", re.S | re.M):
        val = m.group(2).strip()
        fields[m.group(1).strip().lower()] = None if val == "_No response_" else val
    return fields


def to_log(issue):
    f = parse_issue_body(issue.get("body"))
    station = STATION_KEYS.get((f.get("station") or "").strip())
    time_s = f.get("time (m:ss)")
    if not station or not time_s or not re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", time_s.strip()):
        return None
    return {
        "issue": issue["number"],
        "date": (f.get("date") or issue["created_at"][:10]).strip(),
        "station": station,
        "seconds": parse_time(time_s.strip()),
        "fresh": (f.get("conditions") or "").lower().startswith("fresh"),
        "full_distance": (f.get("distance") or "").lower().startswith("full"),
        "notes": f.get("notes") or "",
    }


def fetch_logs():
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        print("stations: no GITHUB_REPOSITORY/GITHUB_TOKEN, using cached logs only")
        return None
    logs, page = [], 1
    while True:
        r = requests.get(f"https://api.github.com/repos/{repo}/issues",
                         headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                         params={"labels": "station-log", "state": "all", "per_page": 100, "page": page}, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        # Public repos let anyone open an issue; only trust the repo owner's logs.
        owner = os.environ.get("GITHUB_REPOSITORY_OWNER", repo.split("/")[0]).lower()
        mine = [i for i in batch if (i.get("user") or {}).get("login", "").lower() == owner]
        logs.extend(l for l in map(to_log, mine) if l)
        page += 1
    print(f"stations: {len(logs)} logged results")
    return sorted(logs, key=lambda l: (l["date"], l["issue"]))
