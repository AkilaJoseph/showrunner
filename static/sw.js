// ═══════════════════════════════════════════════
// ShowRunner — Service Worker
// ═══════════════════════════════════════════════

const CACHE_NAME  = 'showrunner-v1';
const SHELL_URLS  = [
    '/static/css/style.css',
    '/static/js/app.js',
    '/offline',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
];

// ── Install: pre-cache the app shell ─────────────────────────
self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(SHELL_URLS.map(u => new Request(u, { cache: 'reload' }))))
            .catch(() => {}) // tolerate missing icons at first install
            .then(() => self.skipWaiting())
    );
});

// ── Activate: purge stale caches ─────────────────────────────
self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
            ))
            .then(() => self.clients.claim())
    );
});

// ── Fetch strategy ───────────────────────────────────────────
self.addEventListener('fetch', e => {
    const { request } = e;
    const url = new URL(request.url);

    // Only handle same-origin GET requests
    if (request.method !== 'GET' || url.origin !== self.location.origin) return;

    // API calls: network only, no caching
    if (url.pathname.startsWith('/api/')) return;

    // Static assets: cache-first, populate cache on miss
    if (url.pathname.startsWith('/static/')) {
        e.respondWith(
            caches.match(request).then(cached => {
                if (cached) return cached;
                return fetch(request).then(resp => {
                    if (resp.ok) {
                        caches.open(CACHE_NAME).then(c => c.put(request, resp.clone()));
                    }
                    return resp;
                });
            })
        );
        return;
    }

    // Navigation requests (HTML pages): network-first, offline fallback
    if (request.mode === 'navigate') {
        e.respondWith(
            fetch(request)
                .then(resp => {
                    if (resp.ok) {
                        caches.open(CACHE_NAME).then(c => c.put(request, resp.clone()));
                    }
                    return resp;
                })
                .catch(() =>
                    caches.match(request)
                        .then(cached => cached || caches.match('/offline'))
                )
        );
        return;
    }
});

// ── Push notifications ────────────────────────────────────────
self.addEventListener('push', e => {
    let data = { title: 'ShowRunner', body: 'You have a new update.', url: '/' };
    try { data = Object.assign(data, e.data.json()); } catch (_) {}

    e.waitUntil(
        self.registration.showNotification(data.title, {
            body:    data.body,
            icon:    '/static/icons/icon-192.png',
            badge:   '/static/icons/icon-badge.png',
            tag:     data.tag || 'showrunner',
            data:    { url: data.url },
            vibrate: [200, 100, 200],
            actions: data.actions || [],
        })
    );
});

self.addEventListener('notificationclick', e => {
    e.notification.close();
    const target = e.notification.data?.url || '/';
    e.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(wins => {
                for (const win of wins) {
                    if (win.url.includes(target) && 'focus' in win) return win.focus();
                }
                return clients.openWindow(target);
            })
    );
});
