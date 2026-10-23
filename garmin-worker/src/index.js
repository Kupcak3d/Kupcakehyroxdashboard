// Garmin Health API receiver (Cloudflare Worker).
//
//   GET  /connect?token=…  start OAuth 2.0 PKCE consent for your Garmin account
//   GET  /callback         OAuth redirect target; stores tokens, requests a 30-day backfill
//   POST /garmin/push      Garmin webhook for push or ping notifications (all summary types)
//   GET  /export?token=…   wellness rows by calendar date, read by the GitHub Action
//
// Storage (KV binding GARMIN): "tokens" -> OAuth tokens, "day:YYYY-MM-DD" -> {dailies, sleeps, hrv, ...}.

const AUTH_URL = "https://connect.garmin.com/oauth2Confirm";
const TOKEN_URL = "https://diauth.garmin.com/di-oauth2-service/oauth/token";
const API = "https://apis.garmin.com/wellness-api/rest";
const BACKFILL_TYPES = ["dailies", "sleeps", "hrv"];
const KEEP_DAYS = 120;

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    try {
      if (req.method === "GET" && url.pathname === "/connect") return connect(url, env);
      if (req.method === "GET" && url.pathname === "/callback") return await callback(url, env, ctx);
      if (req.method === "POST" && url.pathname === "/garmin/push") return await webhook(req, env, ctx);
      if (req.method === "GET" && url.pathname === "/export") return await exportDays(url, env);
      if (req.method === "GET" && url.pathname === "/") return text("Hyrox Garmin receiver is running.");
      return text("Not found", 404);
    } catch (e) {
      console.error(e.stack || e);
      return text("Error: " + e.message, 500);
    }
  },
};

const text = (body, status = 200) => new Response(body, { status, headers: { "content-type": "text/plain" } });
const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });

// ---------- OAuth 2.0 PKCE ----------

function b64url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function connect(url, env) {
  // Only you may link an account; otherwise anyone could replace your Garmin connection.
  if (!env.EXPORT_TOKEN || url.searchParams.get("token") !== env.EXPORT_TOKEN) return text("Forbidden", 403);
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(48)));
  const state = b64url(crypto.getRandomValues(new Uint8Array(16)));
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  await env.GARMIN.put(`pkce:${state}`, verifier, { expirationTtl: 900 });
  const q = new URLSearchParams({
    response_type: "code", client_id: env.GARMIN_CLIENT_ID, code_challenge: challenge,
    code_challenge_method: "S256", redirect_uri: `${url.origin}/callback`, state,
  });
  return Response.redirect(`${AUTH_URL}?${q}`, 302);
}

async function tokenRequest(env, params) {
  const r = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: env.GARMIN_CLIENT_ID, client_secret: env.GARMIN_CLIENT_SECRET, ...params }),
  });
  if (!r.ok) throw new Error(`token request failed: ${r.status} ${await r.text()}`);
  const t = await r.json();
  const now = Math.floor(Date.now() / 1000);
  // Refresh 10 minutes early, as Garmin recommends.
  return { ...t, expires_at: now + (t.expires_in || 86400) - 600 };
}

async function callback(url, env, ctx) {
  const state = url.searchParams.get("state");
  const code = url.searchParams.get("code");
  const verifier = state && (await env.GARMIN.get(`pkce:${state}`));
  if (!code || !verifier) return text("Missing or expired authorization. Open /connect?token=… again.", 400);
  await env.GARMIN.delete(`pkce:${state}`);
  const tokens = await tokenRequest(env, {
    grant_type: "authorization_code", code, code_verifier: verifier, redirect_uri: `${url.origin}/callback`,
  });
  const who = await fetch(`${API}/user/id`, { headers: { authorization: `Bearer ${tokens.access_token}` } });
  tokens.user_id = who.ok ? (await who.json()).userId : null;
  await env.GARMIN.put("tokens", JSON.stringify(tokens));
  ctx.waitUntil(backfill(env, tokens.access_token));
  return text("Garmin connected. Your last 30 days are being requested; they arrive over the next few minutes. You can close this tab.");
}

async function accessToken(env) {
  const raw = await env.GARMIN.get("tokens");
  if (!raw) throw new Error("Garmin not connected yet: open /connect?token=…");
  let t = JSON.parse(raw);
  if (Math.floor(Date.now() / 1000) >= t.expires_at) {
    const fresh = await tokenRequest(env, { grant_type: "refresh_token", refresh_token: t.refresh_token });
    t = { ...t, ...fresh };
    await env.GARMIN.put("tokens", JSON.stringify(t));
  }
  return t.access_token;
}

// Backfill is asynchronous: Garmin answers 202 and later delivers the data to the webhook.
async function backfill(env, token) {
  const end = Math.floor(Date.now() / 1000);
  const start = end - 30 * 86400;
  for (const type of BACKFILL_TYPES) {
    const r = await fetch(`${API}/backfill/${type}?summaryStartTimeInSeconds=${start}&summaryEndTimeInSeconds=${end}`,
      { headers: { authorization: `Bearer ${token}` } });
    console.log(`backfill ${type}: ${r.status}`);
    await new Promise((res) => setTimeout(res, 2000));
  }
}

// ---------- webhooks ----------

async function webhook(req, env, ctx) {
  const body = await req.json();
  // Answer fast; Garmin times out after 30 s and retries.
  ctx.waitUntil(handleNotification(body, env));
  return new Response(null, { status: 200 });
}

async function handleNotification(body, env) {
  const tokens = JSON.parse((await env.GARMIN.get("tokens")) || "{}");
  if (!tokens.user_id) return; // not connected yet
  for (const [type, items] of Object.entries(body)) {
    if (!Array.isArray(items)) continue;
    for (const item of items) {
      if (item.userId !== tokens.user_id) continue; // ignore anything not about your account
      if (type === "deregistrations" || type === "userPermissionsChange") {
        console.log(`${type}`, JSON.stringify(item));
        continue;
      }
      if (item.callbackURL) {
        // Ping: fetch the summaries from the callback URL.
        const r = await fetch(item.callbackURL, { headers: { authorization: `Bearer ${await accessToken(env)}` } });
        if (!r.ok) { console.error(`ping fetch ${type} ${r.status}`); continue; }
        for (const s of await r.json()) await store(env, type, s);
      } else {
        await store(env, type, item); // Push: the summary is the item itself.
      }
    }
  }
}

function summaryDate(s) {
  if (s.calendarDate) return s.calendarDate;
  if (s.startTimeInSeconds) return new Date((s.startTimeInSeconds + (s.startTimeOffsetInSeconds || 0)) * 1000).toISOString().slice(0, 10);
  return null;
}

async function store(env, type, s) {
  const date = summaryDate(s);
  if (!date) return;
  const key = `day:${date}`;
  const day = JSON.parse((await env.GARMIN.get(key)) || "{}");
  if (type === "activities") {
    (day.activities ||= {})[s.summaryId || s.activityId] = s;
  } else {
    // Garmin resends updated summaries for the same day; keep the newest.
    day[type] = s;
  }
  await env.GARMIN.put(key, JSON.stringify(day), { expirationTtl: KEEP_DAYS * 86400 });
}

// ---------- export ----------

async function exportDays(url, env) {
  if (!env.EXPORT_TOKEN || url.searchParams.get("token") !== env.EXPORT_TOKEN) return text("Forbidden", 403);
  const days = Math.min(Number(url.searchParams.get("days")) || 60, KEEP_DAYS);
  const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
  const out = {};
  let cursor;
  do {
    const page = await env.GARMIN.list({ prefix: "day:", cursor });
    for (const k of page.keys) {
      const date = k.name.slice(4);
      if (date >= since) out[date] = JSON.parse(await env.GARMIN.get(k.name));
    }
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);
  const connected = Boolean(await env.GARMIN.get("tokens"));
  return json({ connected, days: out });
}
