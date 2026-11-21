/* Flup service worker: keeps the app shell on the phone so it opens
   instantly and offline. Data is fetched fresh by app.js (and saved there). */
const VERSION = '52e2604569b8';
const SHELL = ['./', 'index.html', 'app.css', 'app.js', 'manifest.webmanifest',
  'icons/icon-192.png', 'icons/icon-512.png', 'icons/apple-touch-icon.png'];
const CACHE = 'flup-shell-' + VERSION;

self.addEventListener('install', (event) => {
  // 'reload' skips the browser's own cache, which can still hold the old files
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: 'reload' }))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith('flup-shell-') && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.includes('/data/')) return; // always from the network
  // Shell: answer from the phone's copy instantly, refresh it in the background
  // (an update shows up on the next open)
  event.respondWith(caches.open(CACHE).then((cache) => cache.match(event.request).then((hit) => {
    const update = fetch(event.request).then((resp) => {
      if (resp.ok) cache.put(event.request, resp.clone());
      return resp;
    });
    if (hit) { event.waitUntil(update.catch(() => {})); return hit; }
    return update.catch(() => cache.match('index.html'));
  })));
});
