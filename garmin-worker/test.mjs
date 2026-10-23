// node garmin-worker/test.mjs — exercises the worker with an in-memory KV and a fake Garmin.
import assert from "node:assert/strict";
import worker from "./src/index.js";

class KV {
  m = new Map();
  async get(k) { return this.m.get(k) ?? null; }
  async put(k, v) { this.m.set(k, v); }
  async delete(k) { this.m.delete(k); }
  async list({ prefix }) { return { keys: [...this.m.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })), list_complete: true }; }
}

const env = { GARMIN: new KV(), GARMIN_CLIENT_ID: "cid", GARMIN_CLIENT_SECRET: "sec", EXPORT_TOKEN: "x" };
const pending = [];
const ctx = { waitUntil: (p) => pending.push(p) };
const call = async (path, init) => { const r = await worker.fetch(new Request("https://w.dev" + path, init), env, ctx); await Promise.all(pending.splice(0)); return r; };

const calls = [];
globalThis.fetch = async (url, init = {}) => {
  url = String(url); calls.push(url);
  if (url.includes("/oauth/token")) {
    const p = new URLSearchParams(init.body);
    return Response.json({ access_token: p.get("grant_type") === "refresh_token" ? "AT2" : "AT1", refresh_token: "RT", expires_in: 86400 });
  }
  if (url.endsWith("/user/id")) return Response.json({ userId: "U1" });
  if (url.includes("/backfill/")) return new Response(null, { status: 202 });
  if (url.startsWith("https://cb/")) {
    assert.equal(init.headers.authorization, "Bearer AT2");
    return Response.json([{ userId: "U1", calendarDate: "2026-10-22", overallSleepScore: { value: 81 }, durationInSeconds: 27000 }]);
  }
  throw new Error("unexpected fetch " + url);
};
globalThis.setTimeout = (fn) => fn();

assert.equal((await call("/connect")).status, 403);
const redirect = await call("/connect?token=x");
assert.equal(redirect.status, 302);
const loc = new URL(redirect.headers.get("location"));
assert.equal(loc.searchParams.get("code_challenge_method"), "S256");
const state = loc.searchParams.get("state");

// Before connecting, webhooks are ignored.
await call("/garmin/push", { method: "POST", body: JSON.stringify({ dailies: [{ userId: "U1", calendarDate: "2026-10-21" }] }) });
assert.equal(await env.GARMIN.get("day:2026-10-21"), null);

assert.equal((await call(`/callback?state=${state}&code=C`)).status, 200);
assert.equal(JSON.parse(await env.GARMIN.get("tokens")).user_id, "U1");
assert.equal(calls.filter((u) => u.includes("/backfill/")).length, 3);

// Push: stored by calendarDate; other users ignored.
await call("/garmin/push", { method: "POST", body: JSON.stringify({
  dailies: [{ userId: "U1", calendarDate: "2026-10-22", restingHeartRateInBeatsPerMinute: 49 },
            { userId: "SOMEONE", calendarDate: "2026-10-22", restingHeartRateInBeatsPerMinute: 99 }],
  hrv: [{ userId: "U1", calendarDate: "2026-10-22", lastNightAvg: 58 }] }) });

// Ping with an expired token: refreshes, then fetches the callback URL.
const t = JSON.parse(await env.GARMIN.get("tokens")); t.expires_at = 0; await env.GARMIN.put("tokens", JSON.stringify(t));
await call("/garmin/push", { method: "POST", body: JSON.stringify({ sleeps: [{ userId: "U1", callbackURL: "https://cb/sleeps" }] }) });

assert.equal((await call("/export")).status, 403);
const out = await (await call("/export?token=x")).json();
const day = out.days["2026-10-22"];
assert.equal(day.dailies.restingHeartRateInBeatsPerMinute, 49);
assert.equal(day.hrv.lastNightAvg, 58);
assert.equal(day.sleeps.overallSleepScore.value, 81);
assert.equal(out.connected, true);
console.log("worker tests passed");
