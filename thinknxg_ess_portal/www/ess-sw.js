/* thinkNXG ESS service worker. Scope: /ess
 * - Versioned, content-hashed static assets: cache-first.
 * - SPA navigations: network-first with an offline page fallback.
 * - API, files and private documents are NEVER cached (payslips, letters, personal data).
 */
const VERSION = "25077f11ab";
const STATIC = `ess-static-${VERSION}`;
const ASSET_PREFIX = "/assets/thinknxg_ess_portal/ess/";
const OFFLINE = ASSET_PREFIX + "offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC).then((c) => c.addAll([OFFLINE, ASSET_PREFIX + "icons/icon-192.png"])).catch(() => null));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key.startsWith("ess-") && key !== STATIC) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("message", (e) => { if (e.data && e.data.type === "skip-waiting") self.skipWaiting(); });

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/private/") || url.pathname.startsWith("/files/")) return;

  if (req.mode === "navigate" && url.pathname.startsWith("/ess")) {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
    return;
  }
  if (url.pathname.startsWith(ASSET_PREFIX)) {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok && res.type === "basic") { const copy = res.clone(); caches.open(STATIC).then((c) => c.put(req, copy)); }
      return res;
    })));
  }
});

self.addEventListener("push", (event) => {
  let data = { title: "thinkNXG ESS", body: "", route: "/ess" };
  try { data = Object.assign(data, event.data.json()); } catch (e) { /* ignore */ }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body, icon: ASSET_PREFIX + "icons/icon-192.png", badge: ASSET_PREFIX + "icons/icon-192.png",
    data: { route: data.route },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const route = (event.notification.data && event.notification.data.route) || "/ess";
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) { if (c.url.includes("/ess")) { c.focus(); c.postMessage({ type: "navigate", url: route }); return; } }
    await self.clients.openWindow(route);
  })());
});
