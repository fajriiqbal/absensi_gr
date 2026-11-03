const CACHE_NAME = 'presensi-static-v1';
const APP_ASSETS = [
	'/static/app/manifest.json',
	'/static/app/icon-192.png',
	'/static/app/icon-512.png',
	'/static/app/icon.svg',
];

self.addEventListener('install', event => {
	event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_ASSETS)));
	self.skipWaiting();
});

self.addEventListener('activate', event => {
	event.waitUntil(Promise.all([
		self.clients.claim(),
		caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('presensi-static-') && key !== CACHE_NAME).map(key => caches.delete(key)))),
	]));
});

self.addEventListener('fetch', event => {
	const requestUrl = new URL(event.request.url);
	if (event.request.method !== 'GET' || requestUrl.origin !== self.location.origin || !requestUrl.pathname.startsWith('/static/')) return;
	event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
});