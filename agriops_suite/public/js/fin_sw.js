/* Financial Cockpit service worker — offline = last snapshot.
 *
 * Strategy: network-first for both the shell (/fin) and the read-only data
 * GETs, falling back to the last cached copy when the shop wifi drops. The
 * page stamps "as of" from the payload itself, so a stale-served snapshot is
 * visibly stale, never silently wrong. Bump VERSION to invalidate.
 */
var VERSION = "fin-v2";  // bumped: cache is now partitioned per user (see userCache)
var DATA_PREFIX = "/api/method/agriops_suite.fin_api.";
var CACHEABLE = ["snapshot", "acct", "tree", "bootstrap", "outstanding", "stock_balance"];

// Per-user cache name so a SHARED browser never serves one user's financials to
// the next. user_id is a non-HttpOnly Frappe cookie readable from the worker; on
// logout it clears -> "anon" bucket -> the previous user's data is unreachable.
function userCache() {
	if (!(self.cookieStore && self.cookieStore.get)) return Promise.resolve(VERSION + ":anon");
	return self.cookieStore.get("user_id").then(function (c) {
		return VERSION + ":" + ((c && c.value) ? decodeURIComponent(c.value) : "anon");
	}).catch(function () { return VERSION + ":anon"; });
}

self.addEventListener("install", function (e) {
	self.skipWaiting();
});

self.addEventListener("activate", function (e) {
	e.waitUntil(
		caches.keys().then(function (keys) {
			return Promise.all(keys.filter(function (k) {
				return k.indexOf(VERSION + ":") !== 0;  // drop old versions + any global cache
			}).map(function (k) { return caches.delete(k); }));
		}).then(function () { return self.clients.claim(); })
	);
});

function cacheable(url) {
	var u = new URL(url);
	if (u.pathname === "/fin") return true;
	if (u.pathname.indexOf(DATA_PREFIX) === 0) {
		var method = u.pathname.slice(DATA_PREFIX.length);
		return CACHEABLE.some(function (m) { return method.indexOf(m) === 0; });
	}
	return false;
}

self.addEventListener("fetch", function (e) {
	if (e.request.method !== "GET" || !cacheable(e.request.url)) return;
	e.respondWith(
		fetch(e.request).then(function (resp) {
			if (resp && resp.ok) {
				var copy = resp.clone();
				// tie the write to the event lifetime (was fire-and-forget) and store
				// it ONLY in the current user's cache
				e.waitUntil(userCache().then(function (name) {
					return caches.open(name).then(function (c) { return c.put(e.request, copy); });
				}));
			}
			return resp;
		}).catch(function () {
			// offline: serve only from THIS user's cache, never a shared one
			return userCache().then(function (name) {
				return caches.open(name).then(function (c) {
					return c.match(e.request).then(function (hit) {
						return hit || new Response(
							JSON.stringify({ offline: true }),
							{ status: 503, headers: { "Content-Type": "application/json" } }
						);
					});
				});
			});
		})
	);
});
