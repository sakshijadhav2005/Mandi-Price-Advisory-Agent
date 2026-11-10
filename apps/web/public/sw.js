/* Offline support (plan phase 5).
 * - App shell: cache-first, so the app opens without a network.
 * - GET /meta, /prices: network-first with cache fallback, so the last prices
 *   stay visible offline (the UI shows their report dates and staleness).
 * - Everything else (chat, auth, voice): network only.
 */
const VERSION = "v1";
const SHELL = `shell-${VERSION}`;
const DATA = `data-${VERSION}`;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/index.html", "/manifest.webmanifest", "/icon.svg"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => ![SHELL, DATA].includes(k)).map((k) => caches.delete(k)))),
  );
  self.clients.claim();
});

function isData(url) {
  return /\/(meta|prices)$/.test(url.pathname);
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (isData(url)) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(DATA).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || Response.error())),
    );
    return;
  }

  if (url.origin !== self.location.origin) return;

  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/index.html")));
    return;
  }

  // Hashed build assets: cache-first.
  event.respondWith(
    caches.match(req).then(
      (hit) =>
        hit ||
        fetch(req).then((res) => {
          if (res.ok && url.pathname.startsWith("/assets/")) {
            const copy = res.clone();
            caches.open(SHELL).then((c) => c.put(req, copy));
          }
          return res;
        }),
    ),
  );
});
