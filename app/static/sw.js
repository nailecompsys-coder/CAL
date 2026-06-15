// Service Worker — Mid Florida Surgical Scheduler
// Only cache /static/* — never cache /surgeon/* or other HTML (avoids stale PWA UI after deploy).
const CACHE_NAME = 'cal-1-3-5-beta-1-20260615T222646Z-static';

const OFFLINE_URLS = [
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/apple-touch-icon.png',
];

self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(OFFLINE_URLS).catch(() => {}))
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isStaticAsset(pathname) {
  return pathname.startsWith('/static/');
}

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  if (event.request.method !== 'GET' || url.origin !== location.origin) return;

  // API — pass through (browser handles; no SW cache)
  if (url.pathname.startsWith('/api/')) return;

  // HTML, API, auth: never use HTTP cache (fixes stale PWA shell after deploy on iOS/Safari).
  if (!isStaticAsset(url.pathname)) {
    event.respondWith(
      fetch(event.request, { cache: 'no-store', redirect: 'follow' })
    );
    return;
  }

  // Static assets: network-first, cache for offline
  event.respondWith(
    fetch(event.request, { cache: 'no-store' })
      .then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

self.addEventListener('push', event => {
  let data = { title: 'Northstar Surgical', body: 'You have an update.', url: '/surgeon/schedule' };
  try { data = { ...data, ...event.data.json() }; } catch {}

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png',
      data: { url: data.url },
      vibrate: [100, 50, 100],
      requireInteraction: false,
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = event.notification.data?.url || '/surgeon/schedule';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const client of list) {
        if (client.url.includes(location.origin) && 'focus' in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return clients.openWindow(target);
    })
  );
});
