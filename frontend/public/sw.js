// Caches the static app shell only. API responses and private media are never cached.
const SHELL = "spatial-shell-v1";
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/icon.svg", "/manifest.webmanifest"])));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/_next/static/") || url.pathname === "/icon.svg") {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
  }
});
