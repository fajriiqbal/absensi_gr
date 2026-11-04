const CACHE_NAME = 'presensi-static-v3';
const APP_ASSETS = [
	'/static/app/manifest.json?v=3',
	'/static/app/images/logo-madrasah.png',
	'/static/app/logomada-icon-64-v3.png',
	'/static/app/logomada-icon-180-v3.png',
	'/static/app/logomada-icon-192-v3.png',
	'/static/app/logomada-icon-512-v3.png',
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