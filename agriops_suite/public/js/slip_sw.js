/* VAC स्लिप — service worker.
 *
 * Served by agriops_suite.slip.sw (an allow_guest endpoint) with
 * `Service-Worker-Allowed: /slip`, because Frappe's StaticPage blocks .js
 * files under www/ and /assets is proxy-cached immutable. Registered with
 * scope "/slip", and the fetch handler additionally path-filters, so desk
 * and API traffic are never intercepted.
 *
 * Strategy:
 *  - /slip shell  -> stale-while-revalidate (instant open, update next open)
 *  - manifest+icons -> cache-first
 *  - everything else -> untouched (network); offline writes live in the
 *    app's IndexedDB queue, not here.
 */
var CACHE = "vacslip-shell-v1";

self.addEventListener("install", function (e) {
	e.waitUntil(
		caches.open(CACHE).then(function (c) { return c.add("/slip"); }).then(function () { return self.skipWaiting(); })
	);
});

self.addEventListener("activate", function (e) {
	e.waitUntil(
		caches.keys().then(function (keys) {
			return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
		}).then(function () { return self.clients.claim(); })
	);
});

self.addEventListener("fetch", function (e) {
	if (e.request.method !== "GET") return;
	var url = new URL(e.request.url);
	if (url.origin !== self.location.origin) return;

	if (url.pathname === "/slip" || url.pathname === "/slip/") {
		e.respondWith(staleWhileRevalidate(e));
		return;
	}
	if (url.pathname === "/api/method/agriops_suite.slip.manifest" ||
		url.pathname.indexOf("/assets/agriops_suite/images/slip-icon") === 0) {
		e.respondWith(cacheFirst(e.request));
		return;
	}
	/* all other requests: not our business */
});

function staleWhileRevalidate(e) {
	var req = e.request;
	return caches.open(CACHE).then(function (c) {
		return c.match("/slip").then(function (hit) {
			var net = fetch(req).then(function (res) {
				if (res && res.ok) c.put("/slip", res.clone());
				return res;
			}).catch(function () { return null; });
			// keep the worker alive until the background refresh resolves, so the
			// cached shell is actually updated (was detached from the event lifetime)
			if (hit) { e.waitUntil(net); return hit; }
			return net.then(function (res) {
				return res || new Response("<h1>ऑफलाइन</h1>", { status: 503, headers: { "Content-Type": "text/html" } });
			});
		});
	});
}

function cacheFirst(req) {
	return caches.open(CACHE).then(function (c) {
		return c.match(req).then(function (hit) {
			if (hit) return hit;
			return fetch(req).then(function (res) {
				if (res && res.ok) c.put(req, res.clone());
				return res;
			});
		});
	});
}
