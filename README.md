# Hyrox training dashboard

A live dashboard for the [Hyrox Vancouver training plan](https://claude.ai/artifact/7MtfjqtKx9qpbiJo3CGBQ5)
(Open Men, Sat Dec 19 2026, target 1:20). Twice a day, a GitHub Action pulls your runs from
Strava and your recovery data from Garmin, adjusts upcoming sessions, and publishes the page to
GitHub Pages.

**Dashboard:** https://kupcak3d.github.io/Kupcakehyroxdashboard/

## What adapts, and why

| Signal | Rule | Source |
|---|---|---|
| Garmin HRV under 85% of your 7-day baseline or HRV status low/poor, resting HR 5+ bpm over baseline, or sleep score under 50 | One low day: a caution on the next hard session. **Two in a row:** the next hard session within 2 days becomes an easy run. | Plan: "If legs feel heavy two days running, swap Tuesday intervals for an easy run." |
| Interval rep pace (Strava laps faster than 5:30/km) | Beat target by 5+ s/km two sessions running → future rep targets 5 s faster. Missed by 8+ s → 5 s slower. Capped at ±10 s from the plan, never in race week. | Keeps Tuesdays hard but achievable |
| Acute:chronic load ratio | Above 1.5 → next 7 days of easy and long runs trimmed 20%. Above 1.3 → warning. | Standard load management |
| Weekly km vs plan | Under 80% or over 115% → a note not to chase or overshoot the ramp | Plan's 30 → 40 km ramp |
| Easy-run pace | Last 3 easy runs faster than 6:05/km → warning | Plan: easy = 6:15–6:45/km |
| Missed hard session | A note not to stack it onto the next hard day | Plan: no back-to-back hard days |
| Station logs | Race estimate per station. The two furthest behind target become Thursday's skill focus. | Plan: Thursday fixes the weakest station |

The projected finish adds 8 km at your run target pace (nudged by interval results), each
station's estimate (latest full-distance log, or your fresh Oct 16 benchmark + 10%), and 5:30
of Roxzone.

Every change appears under **Why the plan changed** with its reason.

## The bison

The pixel bison in the header acts out today's session (intervals, sled push, wall balls and
burpees, sim, long run, or lounging on rest days), then switches to a pose that shows how
recovered you are:

| Mood | Score | Looks like |
|---|---|---|
| Exhausted | under 35 | Hoodie on, dozing on his feet, zzz, wall balls fall short |
| Tired | 35–54 | Hoodie on, slumped, yawning, sweating |
| Ready | 55–74 | Standing tall, shaking out his arms |
| Fired up | 75+ | Flexing, steam from the nostrils |

The score (0–100) is an even blend of **readiness** (last night's HRV and resting HR against
their 7-day baselines, sleep score, Body Battery) and **load** (acute:chronic ratio and form).
Load only counts after 3 weeks of activity history. Hover the mood chip to see each factor.
Gear unlocks with the plan: headband in week 2, wrist wraps in week 4, race bib in week 8, but
only while at least 70% of past sessions are done. Click him for another tip. To preview any
combination, add `?mood=tired&action=sled` to the URL (moods: `exhausted`, `tired`, `ready`,
`fired_up`; actions: `sprint`, `jog`, `sled`, `skill`, `sim`, `race`, `rest`, `recover`).

## Logging station results

Click **Log a result** on the dashboard. It opens a short GitHub issue form, and submitting it
triggers a rebuild. Only issues you open count. Close the issue whenever you like, since closed
issues still count.

## One-time setup

1. **Pages:** repo Settings → Pages → Source: **GitHub Actions**.
2. **Strava:** create an API app at https://www.strava.com/settings/api with callback domain
   `localhost`. Then run `pip install requests && python scripts/strava_auth.py <client_id> <client_secret>`
   and add the three printed values as repository secrets (Settings → Secrets and variables →
   Actions): `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_REFRESH_TOKEN`.
3. **Garmin:** create a Personal API key at
   https://connect.garmin.com/app/settings/personalApiToken (pick the 1-year expiry) and save it
   as the `GARMIN` repository secret. It brings in resting heart rate, HRV, sleep and Body
   Battery. Garmin emails you a week before the key expires; make a new one and replace the secret.
4. Actions → **Update dashboard** → **Run workflow**.

## Privacy

Synced data is stored in the Actions cache, not committed to the repo. The published page *does*
show your training and recovery numbers, and anyone with its URL can see them.

## Changing the plan

Edit `plan/plan.json` (sessions, paces, `run_km`, station targets) and push. Adaptation
thresholds are constants at the top of `hyrox/adapt.py`.

## Local development

```sh
pip install -r requirements.txt
python -m pytest -q
python -m hyrox.build --offline          # rebuild from cached data/ without network
python -m http.server -d site 8000       # open http://localhost:8000
```
