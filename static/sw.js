/*
 * sw.js  –  ProELD Service Worker
 * Strategy:
 *   - App shell (HTML, CSS, JS, fonts) → Cache First, network fallback
 *   - API calls (/auth /hos /dot /dvir /calculate) → Network First, no cache
 *   - Static CDN assets → Cache First with long TTL
 *   - Offline fallback page shown when navigation fails
 */

const CACHE_NAME    = 'proeld-v1';
const SHELL_CACHE   = 'proeld-shell-v1';
const STATIC_CACHE  = 'proeld-static-v1';

// App shell — cached on install
const SHELL_ASSETS = [
    '/',
    '/static/manifest.json',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
];

// CDN assets to cache on first fetch
const CDN_ORIGINS = [
    'cdn.tailwindcss.com',
    'unpkg.com',
    'fonts.googleapis.com',
    'fonts.gstatic.com',
    'tile.openstreetmap.org',
];

// API prefixes — always network first, never cache
const API_PREFIXES = [
    '/auth/', '/hos/', '/dot/', '/dvir/', '/calculate',
    '/ws/', '/health',
];

// ── Install: pre-cache shell ──────────────────────────────────
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(SHELL_CACHE)
            .then(cache => cache.addAll(SHELL_ASSETS).catch(() => {}))
            .then(() => self.skipWaiting())
    );
});

// ── Activate: clean up old caches ────────────────────────────
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys
                    .filter(k => k !== SHELL_CACHE && k !== STATIC_CACHE)
                    .map(k => caches.delete(k))
            )
        ).then(() => self.clients.claim())
    );
});

// ── Fetch: routing strategy ───────────────────────────────────
self.addEventListener('fetch', event => {
    const { request } = event;
    const url = new URL(request.url);

    // Skip non-GET and WebSocket upgrades
    if (request.method !== 'GET') return;
    if (request.headers.get('upgrade') === 'websocket') return;

    // API calls — network only (never serve stale HOS data)
    if (API_PREFIXES.some(p => url.pathname.startsWith(p))) {
        event.respondWith(
            fetch(request).catch(() =>
                new Response(
                    JSON.stringify({ error: 'Offline', detail: 'No network connection.', status: 503 }),
                    { status: 503, headers: { 'Content-Type': 'application/json' } }
                )
            )
        );
        return;
    }

    // CDN / tile assets — cache first, then network
    if (CDN_ORIGINS.some(o => url.hostname.includes(o))) {
        event.respondWith(cacheFirst(request, STATIC_CACHE));
        return;
    }

    // App shell / navigation — cache first, network fallback
    event.respondWith(cacheFirst(request, SHELL_CACHE));
});

// ── Cache-first helper ────────────────────────────────────────
async function cacheFirst(request, cacheName) {
    const cached = await caches.match(request);
    if (cached) return cached;
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, response.clone());
        }
        return response;
    } catch {
        // Navigation offline fallback
        if (request.mode === 'navigate') {
            const shell = await caches.match('/');
            if (shell) return shell;
        }
        return new Response('Offline', { status: 503 });
    }
}

// ── Background sync: flush offline HOS events ────────────────
self.addEventListener('sync', event => {
    if (event.tag === 'sync-hos-events') {
        event.waitUntil(syncHOSEvents());
    }
});

async function syncHOSEvents() {
    // Notify all open clients to trigger their attemptSync()
    const clients = await self.clients.matchAll({ type: 'window' });
    clients.forEach(client => client.postMessage({ type: 'SYNC_REQUESTED' }));
}

// ── Push notifications: HOS violation alerts ─────────────────
self.addEventListener('push', event => {
    if (!event.data) return;
    const data = event.data.json();
    event.waitUntil(
        self.registration.showNotification(data.title || 'ProELD Alert', {
            body:    data.body  || 'Check your HOS clocks.',
            icon:    '/static/icons/icon-192.png',
            badge:   '/static/icons/icon-192.png',
            tag:     data.tag  || 'proeld-alert',
            data:    { url: data.url || '/' },
            actions: [{ action: 'open', title: 'Open App' }],
            vibrate: [200, 100, 200],
        })
    );
});

self.addEventListener('notificationclick', event => {
    event.notification.close();
    event.waitUntil(
        clients.matchAll({ type: 'window' }).then(list => {
            for (const client of list) {
                if (client.url === '/' && 'focus' in client) return client.focus();
            }
            if (clients.openWindow) return clients.openWindow('/');
        })
    );
});