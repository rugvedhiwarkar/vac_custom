/* VAC POS — service worker.
 *
 * Served by agriops_suite.pos_pwa.sw (allow_guest) with
 * `Service-Worker-Allowed: /pos` — same mechanism as count_sw.js (Frappe's
 * StaticPage blocks .js under www/, /assets is proxy-cached immutable).
 * Registered with scope "/pos"; the fetch handler additionally path-filters,
 * so desk and API traffic are never intercepted.
 *
 * Strategy:
 *  - /pos shell        -> stale-while-revalidate (instant open, update next open)
 *  - manifest + icons  -> cache-first (shell cache)
 *  - item photos (/files/*, destination image) -> cache-first in a separate
 *    image cache; ~90 optimized tile JPEGs ≈ 3 MB, so no eviction cap yet.
 *  - everything else   -> untouched (network). Offline SALES live in the
 *    app's IndexedDB outbox, never here.
 *
 * NB: bump SHELL to evict an old shell after structural changes.
 */
var SHELL = "vacpos-shell-v1";
var IMGS = "vacpos-img-v1";

self.addEventListener("install", function (e) {
	e.waitUntil(
		caches.open(SHELL).then(function (c) { return c.add("/pos"); }).then(function () { return self.skipWaiting(); })
	);
});

self.addEventListener("activate", function (e) {
	e.waitUntil(
		caches.keys().then(function (keys) {
			return Promise.all(keys.filter(function (k) {
				return k.indexOf("vacpos-") === 0 && k !== SHELL && k !== IMGS;
			}).map(function (k) { return caches.delete(k); }));
		}).then(function () { return self.clients.claim(); })
	);
});

self.addEventListener("fetch", function (e) {
	if (e.request.method !== "GET") return;
	var url = new URL(e.request.url);
	if (url.origin !== self.location.origin) return;

	if (url.pathname === "/pos" || url.pathname === "/pos/") {
		e.respondWith(staleWhileRevalidate(e));
		return;
	}
	if (url.pathname === "/api/method/agriops_suite.pos_pwa.manifest" ||
		url.pathname.indexOf("/assets/agriops_suite/images/pos-icon") === 0) {
		e.respondWith(cacheFirst(e.request, SHELL));
		return;
	}
	if (url.pathname.indexOf("/files/") === 0 && e.request.destination === "image") {
		e.respondWith(cacheFirst(e.request, IMGS));
		return;
	}
	/* all other requests: not our business */
});

function staleWhileRevalidate(e) {
	var req = e.request;
	return caches.open(SHELL).then(function (c) {
		return c.match("/pos").then(function (hit) {
			var net = fetch(req).then(function (res) {
				if (res && res.ok) c.put("/pos", res.clone());
				return res;
			}).catch(function () { return null; });
			if (hit) { e.waitUntil(net); return hit; }
			return net.then(function (res) {
				return res || new Response("<h1>Offline</h1>", { status: 503, headers: { "Content-Type": "text/html" } });
			});
		});
	});
}

function cacheFirst(req, name) {
	return caches.open(name).then(function (c) {
		return c.match(req).then(function (hit) {
			if (hit) return hit;
			return fetch(req).then(function (res) {
				if (res && res.ok) c.put(req, res.clone());
				return res;
			});
		});
	});
}
