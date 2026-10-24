const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const parseDate = (s) => new Date(s + "T12:00:00");
const shortDate = (s) => { const d = parseDate(s); return `${DOW[d.getDay()]} ${d.toLocaleString("en", { month: "short" })} ${d.getDate()}`; };
const addDays = (s, n) => { const d = parseDate(s); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
const STATUS = { done: "done", missed: "missed", today: "today", upcoming: "", no_data: "", rest: "rest" };

fetch("data.json", { cache: "no-store" }).then((r) => r.json()).then(render).catch((e) => {
  $("sub").textContent = "Couldn't load data.json: " + e.message;
});

function render(d) {
  const cur = d.sessions.find((s) => s.date >= d.today) || d.sessions[d.sessions.length - 1];
  renderHero(d, cur);
  renderBuddy(d);

  $("alerts").innerHTML = d.alerts.map((a) =>
    `<div class="alert ${a.level}"><b>${a.level === "serious" ? "⚠ Act" : "△ Note"}</b><span>${esc(a.text)}</span></div>`).join("");

  renderToday(d);
  renderUpcoming(d);
  renderTiles(d);
  lineChart($("load-chart"), d.load, d.today);
  barChart($("km-chart"), d.weeks, d.today);
  renderStations(d);
  renderRecovery(d);
  renderChanges(d);
  renderPlan(d);

  const src = [];
  const actSrc = { garmin: "Garmin", strava: "Strava" }[d.sources.activities];
  src.push(actSrc ? `Workouts from ${actSrc} ✓` : "No workout data yet");
  src.push(d.sources.garmin ? "Recovery from Garmin ✓" : "Garmin not connected");
  src.push(`${d.sources.station_logs} station logs`);
  $("footer").innerHTML = `Updated ${esc(d.generated_at.replace("T", " "))} · ${src.join(" · ")} · <a href="${esc(d.plan.source)}">Plan doc</a>`;
}

// ---------- hero ----------

const pad2 = (n) => String(n).padStart(2, "0");

function renderHero(d, cur) {
  const race = d.plan.race;
  // Count down to the start of race day in Vancouver (PST in December).
  const start = new Date(race.date + "T00:00:00-08:00").getTime();
  const tick = () => {
    const ms = Math.max(0, start - Date.now());
    $("days").textContent = Math.floor(ms / 864e5);
    $("hrs").textContent = pad2(Math.floor(ms / 36e5) % 24);
    $("mins").textContent = pad2(Math.floor(ms / 6e4) % 60);
    $("secs").textContent = pad2(Math.floor(ms / 1e3) % 60);
  };
  tick();
  setInterval(tick, 1000);

  $("goal").textContent = race.target.replace(/^0/, "");
  $("goal-meta").textContent = `${race.division} · ${shortDate(race.date)}`;
  $("sub").innerHTML = `Week <b>${cur.week}</b> of ${d.weeks.length} · <b>${esc(cur.phase)}</b> phase`;

  $("track").innerHTML = d.plan.phases.map((p, pi) =>
    `<div class="phase p${pi}" style="flex:${p.weeks.length}"><span class="phase-name">${esc(p.name)}</span><div class="weeks">${
      p.weeks.map((wk) => {
        const state = wk < cur.week ? "past" : wk === cur.week ? "now" : "";
        return `<span class="wk ${state}${wk === d.weeks.length ? " race" : ""}" title="Week ${wk}">W${wk}</span>`;
      }).join("")}</div></div>`).join("");
}

// ---------- bison ----------

const MOODS = ["exhausted", "tired", "ready", "fired_up"];
const MOOD_LABEL = { exhausted: "Exhausted", tired: "Tired", ready: "Ready", fired_up: "Fired up" };
const ACTION_LABEL = {
  sprint: "Intervals", jog: "Easy run", sled: "Sleds + strength", skill: "Wall balls + burpees",
  sim: "Hyrox sim", race: "Race day", rest: "Rest day", recover: "Done for today",
};

function renderBuddy(d) {
  const a = d.avatar;
  if (!a || !window.Bison) { $("buddy").hidden = true; return; }
  // ?mood=tired&action=sled previews any combination
  const q = new URLSearchParams(location.search);
  const mood = MOODS.includes(q.get("mood")) ? q.get("mood") : a.mood;
  const action = ACTION_LABEL[q.get("action")] ? q.get("action") : a.action;
  Bison.mount($("buddy-canvas"), { mood, action, gear: a.gear });

  $("buddy").dataset.mood = mood;
  const chip = $("mood-chip");
  chip.textContent = MOOD_LABEL[mood];
  chip.title = a.factors.length
    ? a.factors.map((f) => `${f.label} (${f.score}/100)`).join("\n")
    : "No Garmin or load data yet";
  $("meter").innerHTML = MOODS.map((m, i) => `<i class="${i <= MOODS.indexOf(mood) ? "on" : ""}"></i>`).join("");
  $("meter").title = a.score == null ? "No score yet" : `Score ${a.score}/100` +
    (a.readiness_score != null ? ` · readiness ${a.readiness_score}` : "") + (a.load_score != null ? ` · load ${a.load_score}` : "");
  $("buddy-today").innerHTML = `<b>${ACTION_LABEL[action]}</b>${action === a.action && !["rest", "race"].includes(action) ? ` · ${esc(a.session)}` : ""}`;
  $("gear").innerHTML = a.gear.map((g) => `<li class="${g.earned ? "earned" : ""}" title="${esc(g.note)}">${g.earned ? "✓ " : ""}${esc(g.name)}</li>`).join("");
  $("buddy-canvas").setAttribute("aria-label", `Bison avatar: ${MOOD_LABEL[mood]}, ${ACTION_LABEL[action]}`);

  const preview = mood !== a.mood || action !== a.action;
  const lines = preview ? [`Preview: ${MOOD_LABEL[mood].toLowerCase()}, ${ACTION_LABEL[action].toLowerCase()}. Remove ?mood / ?action from the URL to see today.`] : a.lines;
  let i = 0, timer = 0;
  const say = () => { $("bubble").textContent = lines[i % lines.length]; };
  const auto = () => {
    clearInterval(timer);
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) timer = setInterval(() => { i++; say(); }, 9000);
  };
  say();
  auto();
  $("buddy-btn").addEventListener("click", () => { i++; say(); auto(); });
}

function badges(s) {
  const b = [];
  if (STATUS[s.status]) b.push(`<span class="badge ${s.status}">${s.status}</span>`);
  if (s.adjusted || s.adjusted_pace) b.push(`<span class="badge adjusted">adjusted</span>`);
  if (s.moved) b.push(`<span class="badge adjusted">moved</span>`);
  return b.join(" ");
}

function sessionTitle(s) {
  let t = esc(s.title);
  if (s.adjusted_pace && s.intervals) t = t.replace(`@ ${s.intervals.pace}/km`, `@ <b>${s.adjusted_pace}</b>/km`);
  return t;
}

function renderToday(d) {
  const s = d.sessions.find((x) => x.date === d.today);
  if (!s) {
    const next = d.sessions.find((x) => x.date > d.today);
    $("today").innerHTML = `<p class="today-title">Rest day</p><p class="sub">A 20-minute walk or mobility work is fine.${
      next ? ` Next: <b>${shortDate(next.date)}</b>, ${sessionTitle(next)}.` : ""}</p>`;
    return;
  }
  $("today").innerHTML = `${badges(s)}
    <p class="today-title">${sessionTitle(s)}</p>
    ${s.original_title ? `<p class="was">${esc(s.original_title)}</p>` : ""}
    <p class="sub">${s.run_km ? `${s.run_km} km running · ` : ""}${esc(s.phase)}</p>
    ${s.notes.length ? `<ul class="notes">${s.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}`;
}

function renderUpcoming(d) {
  const end = addDays(d.today, 7);
  const list = d.sessions.filter((s) => s.date > d.today && s.date <= end);
  $("upcoming").innerHTML = list.map((s) => `<li><span class="when">${shortDate(s.date)}</span>
    <span class="what">${sessionTitle(s)} ${badges(s)}
    ${s.original_title ? `<small class="was">${esc(s.original_title)}</small>` : ""}
    ${s.notes.map((n) => `<small>${esc(n)}</small>`).join("")}</span></li>`).join("") || "<li>Nothing scheduled.</li>";
}

function renderTiles(d) {
  const p = d.projection;
  const l = d.load[d.load.length - 1] || {};
  const w = d.wellness[d.wellness.length - 1] || {};
  const delta = p.delta_s;
  const fmtDelta = `${delta <= 0 ? "−" : "+"}${Math.floor(Math.abs(delta) / 60)}:${String(Math.abs(delta) % 60).padStart(2, "0")}`;
  const tiles = [
    ["Projected finish", p.total, `<span class="${delta <= 0 ? "ok" : "bad"}">${fmtDelta}</span> vs ${p.target} · runs ${p.runs} @ ${p.run_pace}/km`],
    ["Form", l.tsb ?? "–", l.tsb == null ? "" : l.tsb < -20 ? "Heavy fatigue" : l.tsb < -5 ? "Training hard (normal)" : "Fresh"],
    ["Load ratio", l.acwr ?? "–", "Acute:chronic. Aim 0.8–1.3"],
    ["Readiness", w.readiness ?? "–", w.date ? `HRV ${w.hrv ?? "–"} · sleep ${w.sleep_score ?? "–"} · RHR ${w.resting_hr ?? "–"}` : "Connect Garmin"],
  ];
  $("tiles").innerHTML = tiles.map(([label, value, foot]) =>
    `<div class="tile"><div class="label">${label}</div><div class="value">${esc(value)}</div><div class="foot">${foot}</div></div>`).join("");
}

// ---------- charts ----------

const tip = $("tip");
function showTip(e, html) {
  tip.innerHTML = html; tip.hidden = false;
  const x = Math.min(e.clientX + 12, window.innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + "px"; tip.style.top = (e.clientY + 12) + "px";
}
const hideTip = () => { tip.hidden = true; };

function axisY(max, h, pad, w) {
  const step = niceStep(max / 4);
  let out = "";
  for (let v = 0; v <= max + 1e-9; v += step) {
    const y = h - pad.b - (v / max) * (h - pad.t - pad.b);
    out += `<line class="gridline" x1="${pad.l}" x2="${w - pad.r}" y1="${y}" y2="${y}"/><text x="${pad.l - 6}" y="${y + 4}" text-anchor="end">${Math.round(v)}</text>`;
  }
  return out;
}
function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw || 1));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) || p * 10;
}

function lineChart(el, rows, today) {
  if (!rows.length || rows.every((r) => !r.ctl && !r.atl)) { el.innerHTML = `<p class="hint">No activity data yet.</p>`; return; }
  const w = 520, h = 220, pad = { l: 34, r: 56, t: 10, b: 22 };
  const max = niceStep(Math.max(...rows.map((r) => Math.max(r.ctl, r.atl))) / 4) * 4;
  const x = (i) => pad.l + (i / (rows.length - 1)) * (w - pad.l - pad.r);
  const y = (v) => h - pad.b - (v / max) * (h - pad.t - pad.b);
  const path = (k) => rows.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(r[k]).toFixed(1)}`).join("");
  const last = rows.length - 1;
  const ticks = rows.map((r, i) => (i % 14 === 0 ? `<text x="${x(i)}" y="${h - 6}" text-anchor="middle">${shortDate(r.date).slice(4)}</text>` : "")).join("");
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Fitness and fatigue, last 8 weeks">
    ${axisY(max, h, pad, w)}${ticks}
    <path d="${path("ctl")}" fill="none" stroke="var(--series-1)" stroke-width="2"/>
    <path d="${path("atl")}" fill="none" stroke="var(--series-2)" stroke-width="2"/>
    <text x="${x(last) + 6}" y="${y(rows[last].ctl) + 4}">Fitness</text>
    <text x="${x(last) + 6}" y="${y(rows[last].atl) + 4}">Fatigue</text>
    <line id="xh" class="today-line" y1="${pad.t}" y2="${h - pad.b}" visibility="hidden"/>
    <rect x="${pad.l}" y="0" width="${w - pad.l - pad.r}" height="${h}" fill="transparent"/>
  </svg>`;
  const svg = el.querySelector("svg"), xh = svg.querySelector("#xh");
  svg.addEventListener("pointermove", (e) => {
    const b = svg.getBoundingClientRect();
    const px = (e.clientX - b.left) * (w / b.width);
    const i = Math.max(0, Math.min(last, Math.round(((px - pad.l) / (w - pad.l - pad.r)) * last)));
    const r = rows[i];
    xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.setAttribute("visibility", "visible");
    showTip(e, `<b>${shortDate(r.date)}</b><br>Fitness ${r.ctl} · Fatigue ${r.atl}<br>Form ${r.tsb} · Load that day ${r.load}`);
  });
  svg.addEventListener("pointerleave", () => { hideTip(); xh.setAttribute("visibility", "hidden"); });
}

function barChart(el, weeks, today) {
  const w = 520, h = 220, pad = { l: 34, r: 8, t: 10, b: 22 };
  const max = niceStep(Math.max(...weeks.map((r) => Math.max(r.planned_km, r.actual_km || 0))) / 4) * 4;
  const band = (w - pad.l - pad.r) / weeks.length;
  const bw = Math.min(14, (band - 8) / 2);
  const y = (v) => h - pad.b - (v / max) * (h - pad.t - pad.b);
  const bar = (x, v, fill) => {
    const top = y(v), base = y(0), hh = Math.max(0, base - top), r = Math.min(4, hh);
    return `<path d="M${x},${base}V${top + r}q0,-${r} ${r},-${r}h${bw - 2 * r}q${r},0 ${r},${r}V${base}Z" fill="${fill}"/>`;
  };
  let marks = "";
  weeks.forEach((r, i) => {
    const cx = pad.l + band * i + band / 2;
    marks += bar(cx - bw - 1, r.planned_km, "var(--series-1-dim)");
    if (r.actual_km != null) marks += bar(cx + 1, r.actual_km, "var(--series-1)");
    marks += `<text x="${cx}" y="${h - 6}" text-anchor="middle">W${r.week}</text>`;
    marks += `<rect data-i="${i}" x="${cx - band / 2}" y="0" width="${band}" height="${h}" fill="transparent"/>`;
  });
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Weekly running km, planned vs actual">${axisY(max, h, pad, w)}${marks}</svg>`;
  el.querySelectorAll("rect[data-i]").forEach((rect) => {
    rect.addEventListener("pointermove", (e) => {
      const r = weeks[rect.dataset.i];
      showTip(e, `<b>Week ${r.week}</b> (from ${shortDate(r.start)})<br>Planned ${r.planned_km} km<br>Actual ${r.actual_km ?? "–"} km`);
    });
    rect.addEventListener("pointerleave", hideTip);
  });
}

// ---------- tables ----------

function renderStations(d) {
  const maxGap = Math.max(10, ...d.stations.map((s) => Math.abs(s.gap_pct)));
  $("stations").innerHTML = `<tr><th>Station</th><th class="num">Race estimate</th><th>vs target</th><th class="num">Target</th><th class="num">Latest</th><th class="wide">Standard</th><th class="wide">Based on</th></tr>` +
    d.stations.map((s) => {
      const behind = s.gap_pct > 0, even = s.gap_pct === 0;
      const width = Math.round((Math.abs(s.gap_pct) / maxGap) * 60);
      const vs = even ? `<span class="muted">on target</span>`
        : `<span class="gapbar" style="width:${width}px;background:var(${behind ? "--critical" : "--good"})"></span><span class="${behind ? "bad" : "ok"}">${behind ? "▲ +" : "▼ "}${s.gap_pct}%</span>`;
      return `<tr class="${d.focus.includes(s.key) ? "focus" : ""}"><td>${esc(s.name)}</td><td class="num">${s.estimate}</td><td>${vs}</td>
        <td class="num">${s.target}</td><td class="num">${s.latest ?? "–"}</td><td class="wide">${esc(s.standard)}</td><td class="wide">${esc(s.basis)}</td></tr>`;
    }).join("");
  const link = $("log-link");
  if (d.repo) link.href = `https://github.com/${d.repo}/issues/new?template=station-log.yml`;
  else link.setAttribute("aria-disabled", "true");
}

function renderRecovery(d) {
  const rows = d.wellness.slice(-7).reverse();
  const low = Object.fromEntries(d.readiness.map((r) => [r.date, r]));
  if (!rows.length) { $("recovery").innerHTML = `<tr><td>No Garmin data yet.</td></tr>`; return; }
  $("recovery").innerHTML = `<tr><th>Day</th><th class="num">Readiness</th><th class="num">HRV</th><th class="num">Sleep</th><th class="num">RHR</th><th></th></tr>` +
    rows.map((w) => `<tr><td>${shortDate(w.date)}</td><td class="num">${w.readiness ?? "–"}</td><td class="num">${w.hrv ?? "–"}</td>
      <td class="num">${w.sleep_score ?? "–"}</td><td class="num">${w.resting_hr ?? "–"}</td>
      <td>${low[w.date]?.low ? `<span class="bad" title="${esc(low[w.date].reasons.join("; "))}">▼ low</span>` : ""}</td></tr>`).join("");
}

function renderChanges(d) {
  $("changes").innerHTML = d.changes.length
    ? d.changes.map((c) => `<li><b>${shortDate(c.date)}:</b> ${esc(c.change)}<small>${esc(c.reason)}</small></li>`).join("")
    : `<li>No changes. The plan is running as written.</li>`;
}

function renderPlan(d) {
  const byWeek = {};
  d.sessions.forEach((s) => (byWeek[s.week] ||= []).push(s));
  const cur = (d.sessions.find((s) => s.date >= d.today) || {}).week;
  $("plan").innerHTML = Object.entries(byWeek).map(([wk, list]) => {
    const vol = d.weeks.find((w) => w.week == wk);
    return `<details class="week" ${wk == cur ? "open" : ""}><summary>Week ${wk} <small>· ${esc(list[0].phase)} · ${vol.planned_km} km planned${vol.actual_km != null ? `, ${vol.actual_km} km run` : ""}</small></summary>
      <ol class="sessions">${list.map((s) => `<li><span class="when">${shortDate(s.date)}</span><span class="what">${sessionTitle(s)} ${badges(s)}
        ${s.actual_pace ? `<small>Ran ${s.actual_pace}/km${s.pace_delta != null ? ` (${s.pace_delta > 0 ? "+" : ""}${s.pace_delta} s vs target)` : ""}</small>` : ""}</span></li>`).join("")}</ol></details>`;
  }).join("");
}
