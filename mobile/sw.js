const CACHE_NAME = 'law-search-mobile-1.0.1';
const CORE_FILES = [
  './',
  './index.html',
  './manifest.webmanifest',
  './app-version.json',
  './icon-512.png',
  './law_db.js'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(CORE_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  if (new URL(request.url).pathname.endsWith('/app-version.json')) {
    event.respondWith(fetch(request).catch(() => caches.match(request)));
    return;
  }
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).then(response => {
      const clone = response.clone();
      caches.open(CACHE_NAME).then(cache => cache.put('./index.html', clone));
      return response;
    }).catch(() => caches.match('./index.html')));
    return;
  }
  event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
    const clone = response.clone();
    caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
    return response;
  })));
});
