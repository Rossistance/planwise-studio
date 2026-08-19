// PlanWise 2.0 — backend transport. Ported from 1.x's api() wrapper with its
// behaviour intact (LOGIC-MERGE: existing logic, kept): HttpOnly-cookie
// session rides same-origin, JSON in/out, 401 bounces to sign-in, and the
// pending gate keys on the RESPONSE FLAG, not on 403 — "Administrators only"
// is also a 403 and must not throw an approved user onto the waiting screen.
// The offline layer's hooks are guarded so the shell runs before OFFLINE
// lands (plan Phase 8).
"use strict";

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.body) headers["Content-Type"] = "application/json";
  const method = (opts.method || "GET").toUpperCase();
  const OFF = typeof OFFLINE !== "undefined" ? OFFLINE : null;

  let r;
  try {
    r = await fetch(path, { ...opts, headers, credentials: "same-origin" });
  } catch (netErr) {
    // No network. Reads fall back to the last copy we held — labelled with
    // when it was taken, never passed off as current (D2). Writes queue.
    if (OFF && method === "GET") {
      const cached = await OFF.get(path);
      if (cached) { OFF.markServed(cached.at); return cached.body; }
    }
    if (OFF && method !== "GET" && OFF.queueable(path, opts)) {
      OFF.enqueue(path, { ...opts, method });
      return { queued: true };
    }
    throw new Error(method === "GET"
      ? "You're offline and this hasn't been loaded before."
      : "You're offline — this one needs a connection.");
  }

  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    if (r.status === 401 && typeof App !== "undefined") App.onUnauthorized();
    if (body.pending === true && typeof App !== "undefined") App.onPending();
    const err = new Error(body.detail || `${r.status} ${r.statusText}`);
    err.status = r.status;
    err.body = body;
    throw err;
  }
  if (OFF && method === "GET") { OFF.put(path, body); OFF.markLive(); }
  return body;
}
