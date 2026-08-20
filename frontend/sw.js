/* PlanWise service worker (Phase 5e).

   Two jobs, and deliberately only two for now:

     1. Hold the app shell so PlanWise opens with no signal. Opening to a
        browser error is what makes a home-screen icon feel like a bookmark
        instead of an app.
     2. Receive push notifications, so "your RFI got a reply" reaches a phone
        in the field. iOS has supported this for home-screen PWAs since 16.4.

   What it deliberately does NOT do is cache /api responses. Job data is
   shared and changes under you (D9), and a stale cost figure served
   confidently is exactly the class of bug D2 exists to prevent. Offline reads
   and queued writes live in offline.js instead — in the page, where the UI can
   say plainly that what you're looking at came from cache and when it was
   taken. A worker returning a cached response has no way to say that.

   The server sends `Cache-Control: no-store` on everything, which is about
   the HTTP cache; the Cache Storage API used here is separate and unaffected.
*/

// Bump when SHELL changes, so existing installs re-precache.
const VERSION = "planwise-shell-v11";     // mobile shell, real icons, longer splash
const SHELL = [
  "/",
  "/index.html",
  "/copy.js",
  "/offline.js",
  "/api.js",
  "/core.js",
  "/ui.js",
  "/pages.js",
  "/app.js",
  "/tokens.css",
  "/fonts.css",
  "/fonts/PlanWiseSans-400.woff2",
  "/fonts/PlanWiseSans-500.woff2",
  "/fonts/PlanWiseSans-600.woff2",
  "/fonts/PlanWiseSans-700.woff2",
  "/app.css",
  "/manifest.webmanifest",
  "/favicon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/vendor/morphdom-umd.min.js",
  "/vendor/pdfjs/pdf.min.js",
  "/vendor/pdfjs/pdf.worker.min.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(VERSION);
    // Individually, not addAll: one 404 must not throw away the whole
    // precache and leave the app with no offline shell at all.
    await Promise.all(SHELL.map((url) =>
      cache.add(new Request(url, { cache: "reload" })).catch(() => {})));
    self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;      // never cache job data

  // Navigations: try the network so a deploy is picked up, fall back to the
  // cached shell so the app still opens in a basement.
  if (request.mode === "navigate") {
    event.respondWith((async () => {
      try {
        return await fetch(request);
      } catch {
        return (await caches.match("/index.html")) || Response.error();
      }
    })());
    return;
  }

  // App code is network-FIRST, falling back to cache. Cache-first would be
  // faster, but it serves the previous app.js for one load after a deploy —
  // and a stale bundle talking to a new server is how API contracts break.
  // The vendored PDF.js never changes, so it keeps the fast path.
  const immutable = url.pathname.startsWith("/vendor/") || url.pathname.startsWith("/icons/");

  event.respondWith((async () => {
    if (immutable) {
      const hit = await caches.match(request);
      if (hit) return hit;
    }
    try {
      const res = await fetch(request);
      if (res && res.ok) {
        const copy = res.clone();
        caches.open(VERSION).then((c) => c.put(request, copy));
      }
      return res;
    } catch {
      const hit = await caches.match(request);
      if (hit) return hit;
      throw new Error("offline and not cached");
    }
  })());
});

/* ---- push ----------------------------------------------------------------
   The payload is small and already safe to show; the server decides the
   wording so a notification reads the same everywhere. */

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { /* keep defaults */ }
  const title = data.title || "PlanWise";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: data.tag || "planwise",
    data: { url: data.url || "/" },
    // Re-alert when a second reply lands on the same thread rather than
    // silently replacing the first.
    renotify: Boolean(data.tag),
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/", location.origin).href;
  event.waitUntil((async () => {
    const clientList = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    // Reuse an open PlanWise window if there is one — a phone shouldn't
    // accumulate a tab per notification.
    for (const client of clientList) {
      if (client.url.startsWith(location.origin)) {
        await client.focus();
        if ("navigate" in client) await client.navigate(target);
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});
