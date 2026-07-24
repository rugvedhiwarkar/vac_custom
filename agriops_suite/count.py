"""Stock Count PWA (/count) — static endpoints.

Same shape as agriops_suite/slip.py: the page itself is www/count.html and the
dynamic surface is the "Stock Count *" Server Script fixtures. Only two things
need app code, because they must be served as raw non-HTML responses from
stable URLs:

- the service worker: Frappe's StaticPage renderer refuses .js under www/, and
  /assets is proxy-cached immutable (an edit would never reach phones). A
  whitelisted method gives a stable, never-cached URL, and the
  `Service-Worker-Allowed: /count` header widens its scope to the page even
  though the script URL sits under /api/method/.
- the web-app manifest: same .json-under-www restriction.

Both are allow_guest: the browser fetches them without auth headers (service
worker registration and manifest fetches cannot carry our token), and they hold
nothing beyond public branding.
"""

import json

import frappe
from werkzeug.wrappers import Response

SCOPE = "/count"


@frappe.whitelist(methods=["GET"])
def csrf():
	"""Return the CSRF token for the CURRENT logged-in session.

	The /count app authenticates with the counter's own email + password
	(frappe's /api/method/login sets the session cookie). Every subsequent POST
	to a Stock Count endpoint then needs an X-Frappe-CSRF-Token header — a cookie
	session without it is rejected. The token is normally embedded in a
	server-rendered page, but the app's shell is cached by the service worker and
	would go stale, so the app fetches the token here right after login instead.

	Not allow_guest: a caller with no valid session gets 403, which is exactly
	how the app decides whether to show the login screen. Cross-site pages cannot
	read the response (same-origin), so returning the token here does not weaken
	the protection it provides.
	"""
	user = frappe.session.user
	return {
		"csrf_token": frappe.sessions.get_csrf_token(),
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name") or user,
		"is_office": frappe.db.get_value("User", user, "user_type") == "System User",
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def sw():
	"""Serve public/js/count_sw.js with the scope-widening header."""
	path = frappe.get_app_path("agriops_suite", "public", "js", "count_sw.js")
	with open(path, encoding="utf-8") as f:
		body = f.read()
	resp = Response(body, mimetype="text/javascript")
	resp.headers["Service-Worker-Allowed"] = SCOPE
	# no-cache (not immutable): the browser revalidates on each visit, so a
	# shipped SW change reaches phones on their next online open.
	resp.headers["Cache-Control"] = "no-cache"
	return resp


@frappe.whitelist(allow_guest=True, methods=["GET"])
def manifest():
	"""Web-app manifest so the page installs to the counter's home screen."""
	# English is the app's default language, so the home-screen name is English.
	# The manifest is fetched once and cached by the browser (and by the service
	# worker), so it cannot follow the in-app language switch.
	m = {
		"name": "VAC Stock Count",
		"short_name": "VAC Count",
		"start_url": SCOPE,
		"scope": SCOPE,
		"display": "standalone",
		"background_color": "#f6f5f0",
		"theme_color": "#b45309",
		"icons": [
			{
				"src": "/assets/agriops_suite/images/count-icon-192.png",
				"sizes": "192x192",
				"type": "image/png",
			},
			{
				"src": "/assets/agriops_suite/images/count-icon-512.png",
				"sizes": "512x512",
				"type": "image/png",
			},
		],
	}
	resp = Response(json.dumps(m, ensure_ascii=False), mimetype="application/manifest+json")
	resp.headers["Cache-Control"] = "no-cache"
	return resp
