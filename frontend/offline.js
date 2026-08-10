/* PlanWise offline layer (Phase 5f).

   Two capabilities, both deliberately modest:

     * READS are cached, so the job you had open stays readable in a basement
       or a metal building.
     * WRITES are queued, so an edit made with no signal isn't lost — it goes
       out when signal returns.

   What this is NOT is offline sync. Two people editing one look ahead with no
   connection needs real conflict resolution, and inventing that on a shared
   database (D9) would be worse than not offering it. Queued writes replay in
   the order they were made; if one is rejected by the server on replay, it is
   surfaced rather than silently dropped.

   The honesty rule from D2 applies with force here: cached data is always
   labelled with when it was taken. A stale cost figure presented as current
   is exactly the bug the whole app was rebuilt to avoid, and being offline is
   no excuse to start.

   Storage choices: the Cache API for responses (it's built for this), and
   localStorage for the queue. localStorage is synchronous and small, which
   suits a handful of field edits, and it survives a reload and a force-quit.
   A home-screen PWA is exempt from Safari's 7-day eviction, which is what
   makes that safe enough here. */

const OFFLINE = (() => {
  const CACHE = "planwise-api-v1";
  const QUEUE_KEY = "planwise.queue";
  const STAMP = "x-planwise-cached-at";

  const listeners = new Set();
  const notify = () => listeners.forEach((fn) => { try { fn(state()); } catch { /* ignore */ } });

  let lastServedFrom = null;    // ISO time of the cached copy currently on screen

  /* ---- read cache ------------------------------------------------------ */

  async function put(path, body) {
    if (!("caches" in window)) return;
    try {
      const cache = await caches.open(CACHE);
      await cache.put(path, new Response(JSON.stringify(body), {
        headers: { "Content-Type": "application/json", [STAMP]: new Date().toISOString() },
      }));
    } catch { /* a full or unavailable cache must never break a live read */ }
  }

  async function get(path) {
    if (!("caches" in window)) return null;
    try {
      const cache = await caches.open(CACHE);
      const res = await cache.match(path);
      if (!res) return null;
      return { body: await res.json(), at: res.headers.get(STAMP) };
    } catch { return null; }
  }

  async function clear() {
    if ("caches" in window) await caches.delete(CACHE);
    lastServedFrom = null;
    notify();
  }

  /* ---- write queue ------------------------------------------------------ */

  const readQueue = () => {
    try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]"); }
    catch { return []; }
  };
  const writeQueue = (q) => {
    try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q)); } catch { /* quota */ }
    notify();
  };

  /** Only plain JSON writes are queueable. A file upload can't be replayed
      from localStorage, and anything talking to the local companion is
      pointless without the network anyway. */
  function queueable(path, opts) {
    const method = (opts.method || "GET").toUpperCase();
    if (!["POST", "PATCH", "PUT", "DELETE"].includes(method)) return false;
    if (opts.body && typeof opts.body !== "string") return false;   // FormData
    return !/\/(share|package|draft|companion|vista\/workbook|auth)\b/.test(path);
  }

  function enqueue(path, opts) {
    const q = readQueue();
    q.push({ id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
             path, method: (opts.method || "GET").toUpperCase(),
             body: opts.body || null, at: new Date().toISOString() });
    writeQueue(q);
    return q.length;
  }

  /** Replay everything, oldest first, stopping at the first network failure
      so ordering is preserved. A server *rejection* (4xx) is different from a
      network failure: the change can never succeed, so it's dropped from the
      queue and reported, rather than blocking everything behind it forever. */
  async function flush() {
    let q = readQueue();
    if (!q.length) return { sent: 0, rejected: [] };
    const rejected = [];
    let sent = 0;

    while (q.length) {
      const item = q[0];
      let res;
      try {
        res = await fetch(item.path, {
          method: item.method,
          headers: item.body ? { "Content-Type": "application/json" } : {},
          body: item.body, credentials: "same-origin",
        });
      } catch {
        break;                                   // still offline; keep the rest
      }
      if (res.ok || res.status === 404) {
        // 404 counts as done: the thing it targeted is already gone, and
        // retrying forever would wedge the queue.
        sent += 1;
      } else {
        const detail = await res.json().catch(() => ({}));
        rejected.push({ ...item, status: res.status, detail: detail.detail || res.statusText });
      }
      q.shift();
      writeQueue(q);
    }
    notify();
    return { sent, rejected };
  }

  /* ---- state ------------------------------------------------------------ */

  function state() {
    return {
      online: navigator.onLine,
      pending: readQueue().length,
      servedFrom: lastServedFrom,
    };
  }

  function markServed(at) { lastServedFrom = at; notify(); }
  function markLive() { if (lastServedFrom) { lastServedFrom = null; notify(); } }

  window.addEventListener("online", () => { notify(); flushAndAnnounce(); });
  window.addEventListener("offline", notify);

  let announce = null;
  const onFlush = (fn) => { announce = fn; };
  async function flushAndAnnounce() {
    const out = await flush();
    if (announce && (out.sent || out.rejected.length)) announce(out);
    return out;
  }

  return { put, get, clear, queueable, enqueue, flush: flushAndAnnounce,
           state, markServed, markLive, onFlush,
           subscribe: (fn) => { listeners.add(fn); fn(state()); return () => listeners.delete(fn); },
           pending: () => readQueue().length,
           queued: readQueue };
})();
