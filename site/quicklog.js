// Quick station log: pick the session, tap stations, type times on the number pad,
// and send them all as one prefilled GitHub issue (label station-log).
// Station names must match hyrox/stations.py STATION_KEYS.

const QL_STATIONS = [
  ["runs", "Running", "Running (8 x 1 km total)"],
  ["ski", "SkiErg"], ["sled_push", "Sled push"], ["sled_pull", "Sled pull"],
  ["bbj", "Burpee broad jumps", null, "BBJ"], ["row", "Row"], ["farmers", "Farmers carry", null, "Farmers"],
  ["lunges", "Sandbag lunges", null, "Lunges"], ["wall_balls", "Wall balls"],
].map(([key, name, , short]) => ({ key, name, short: short || name }));

const QL_TIRED_KINDS = ["sim", "race", "intervals", "long", "easy_skill", "easy"];
const QL_DRAFT = "hyrox-quicklog-draft";
const QL_TIME = /^(\d{1,2}:)?\d{1,2}:\d{2}$/;

// Number pads on phones have no colon, so build m:ss / h:mm:ss from the digits.
function qlFormatTime(raw) {
  const d = raw.replace(/\D/g, "").replace(/^0+(?=\d{3})/, "").slice(0, 6);
  if (d.length <= 2) return d;
  if (d.length <= 4) return `${d.slice(0, -2)}:${d.slice(-2)}`;
  return `${d.slice(0, -4)}:${d.slice(-4, -2)}:${d.slice(-2)}`;
}

function qlValid(t) {
  if (!QL_TIME.test(t)) return false;
  const parts = t.split(":").map(Number);
  return parts.slice(1).every((n) => n < 60) && parts.some((n) => n > 0);
}

function qlLoad() {
  try { return JSON.parse(localStorage.getItem(QL_DRAFT)) || {}; } catch { return {}; }
}
function qlSave(state) {
  try { localStorage.setItem(QL_DRAFT, JSON.stringify(state)); } catch { /* private mode */ }
}
function qlClear() {
  try { localStorage.removeItem(QL_DRAFT); } catch { /* ignore */ }
}

function initQuickLog(d) {
  const dlg = $("quicklog"), btn = $("log-btn");
  $("ql-single").href = `https://github.com/${d.repo}/issues/new?template=station-log.yml`;
  if (typeof dlg.showModal !== "function") {
    // Very old browser: fall back to the issue form.
    btn.replaceWith(Object.assign(document.createElement("a"), {
      className: "button", textContent: "Log a result", href: $("ql-single").href, target: "_blank", rel: "noopener",
    }));
    return;
  }

  // The last few trainable sessions up to today, newest first.
  const recent = d.sessions.filter((s) => s.date <= d.today && s.kind !== "rest").slice(-3).reverse();
  const dayLabel = (date) => (date === d.today ? "Today" : date === addDays(d.today, -1) ? "Yesterday" : shortDate(date));

  let state;
  const fresh = () => {
    const s = recent[0];
    return { session: s ? s.date : "other", date: s ? s.date : d.today,
      cond: s && !QL_TIRED_KINDS.includes(s.kind) ? "fresh" : "tired", picked: [], times: {}, partial: {}, notes: "" };
  };

  const sessionFor = (date) => recent.find((s) => s.date === date);

  function renderSessions() {
    $("ql-sessions").innerHTML = recent.map((s) =>
      `<button type="button" class="chip${state.session === s.date ? " on" : ""}" data-date="${s.date}" aria-pressed="${state.session === s.date}">
        <b>${dayLabel(s.date)}</b><span>${esc(s.title)}</span></button>`).join("") +
      `<button type="button" class="chip${state.session === "other" ? " on" : ""}" data-date="other" aria-pressed="${state.session === "other"}"><b>Other day</b></button>`;
    $("ql-date").hidden = state.session !== "other";
    $("ql-date").value = state.date;
    $("ql-date").max = d.today;
    document.querySelector(`input[name="ql-cond"][value="${state.cond}"]`).checked = true;
  }

  function renderStations() {
    $("ql-stations").innerHTML = QL_STATIONS.map((s) => {
      const on = state.picked.includes(s.key);
      return `<button type="button" class="chip${on ? " on" : ""}" data-key="${s.key}" aria-pressed="${on}">${esc(s.short)}</button>`;
    }).join("");
  }

  function renderRows() {
    $("ql-rows").innerHTML = state.picked.map((key) => {
      const s = QL_STATIONS.find((x) => x.key === key), t = state.times[key] || "";
      const bad = t && !qlValid(t);
      return `<li data-key="${key}">
        <label for="ql-t-${key}">${esc(s.name)}</label>
        <input id="ql-t-${key}" class="field time${bad ? " bad" : ""}" inputmode="numeric" enterkeyhint="next" autocomplete="off"
          placeholder="${key === "runs" ? "h:mm:ss" : "m:ss"}" value="${esc(t)}" aria-invalid="${bad}">
        <label class="partial"><input type="checkbox"${state.partial[key] ? " checked" : ""}><span>Partial</span></label>
      </li>`;
    }).join("");
    updateSend();
  }

  function updateSend() {
    const n = state.picked.filter((k) => qlValid(state.times[k] || "")).length;
    const missing = state.picked.length - n;
    $("ql-send").disabled = !n || missing > 0;
    $("ql-send").textContent = n ? `Send ${n} result${n > 1 ? "s" : ""}` : "Send";
  }

  function renderAll() { renderSessions(); renderStations(); renderRows(); $("ql-notes").value = state.notes; }
  const save = () => qlSave({ ...state, saved: d.today });

  $("ql-sessions").addEventListener("click", (e) => {
    const b = e.target.closest("[data-date]");
    if (!b) return;
    state.session = b.dataset.date;
    if (state.session !== "other") {
      state.date = state.session;
      state.cond = QL_TIRED_KINDS.includes(sessionFor(state.date).kind) ? "tired" : "fresh";
    }
    renderSessions(); save();
    if (state.session === "other") $("ql-date").focus();
  });
  $("ql-date").addEventListener("change", (e) => { state.date = e.target.value || d.today; save(); });
  document.querySelectorAll('input[name="ql-cond"]').forEach((r) =>
    r.addEventListener("change", () => { state.cond = r.value; save(); }));

  $("ql-stations").addEventListener("click", (e) => {
    const b = e.target.closest("[data-key]");
    if (!b) return;
    const key = b.dataset.key, i = state.picked.indexOf(key);
    if (i >= 0) state.picked.splice(i, 1);
    else state.picked.push(key);
    renderStations(); renderRows(); save();
    if (i < 0) $(`ql-t-${key}`).focus();
  });

  $("ql-rows").addEventListener("input", (e) => {
    const li = e.target.closest("li");
    if (!li || !e.target.classList.contains("time")) return;
    const v = qlFormatTime(e.target.value);
    e.target.value = v;
    state.times[li.dataset.key] = v;
    const bad = v.length >= 4 && !qlValid(v);
    e.target.classList.toggle("bad", bad);
    e.target.setAttribute("aria-invalid", bad);
    updateSend(); save();
  });
  $("ql-rows").addEventListener("change", (e) => {
    const li = e.target.closest("li");
    if (li && e.target.type === "checkbox") { state.partial[li.dataset.key] = e.target.checked; save(); }
  });
  $("ql-rows").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !e.target.classList.contains("time")) return;
    e.preventDefault();
    const inputs = [...$("ql-rows").querySelectorAll("input.time")];
    const next = inputs[inputs.indexOf(e.target) + 1];
    if (next) next.focus(); else e.target.blur();
  });
  $("ql-notes").addEventListener("input", (e) => { state.notes = e.target.value; save(); });

  $("ql-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if ($("ql-send").disabled) return;
    const sess = state.session === "other" ? null : sessionFor(state.date);
    const results = state.picked.map((k) => {
      const s = QL_STATIONS.find((x) => x.key === k);
      return { name: s.name, short: s.short, time: state.times[k], partial: !!state.partial[k] };
    });
    const body = [
      "### Date", state.date,
      "### Session", sess ? sess.title : "_No response_",
      "### Conditions", state.cond === "fresh" ? "Fresh (rested)" : "Tired (in a sim or after running)",
      "### Results", results.map((r) => `- ${r.name}: ${r.time}${r.partial ? " (partial)" : ""}`).join("\n"),
      "### Notes", state.notes.trim() || "_No response_",
    ].join("\n\n");
    const title = `Station log ${shortDate(state.date)}: ` +
      results.map((r) => `${r.short} ${r.time}${r.partial ? "*" : ""}`).join(", ");
    const url = `https://github.com/${d.repo}/issues/new?` +
      new URLSearchParams({ labels: "station-log", title, body }).toString();
    qlClear();
    state = fresh();
    dlg.close();
    window.open(url, "_blank", "noopener");
  });

  const close = () => dlg.close();
  $("ql-close").addEventListener("click", close);
  dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); }); // tap the backdrop

  btn.disabled = false;
  btn.addEventListener("click", () => {
    const draft = qlLoad();
    // Keep an unsent draft from the last two days; otherwise start from the latest session.
    state = draft.saved >= addDays(d.today, -2) && Array.isArray(draft.picked)
      ? { ...fresh(), ...draft } : fresh();
    if (state.session !== "other" && !sessionFor(state.session)) state.session = "other";
    renderAll();
    dlg.showModal();
  });
}
