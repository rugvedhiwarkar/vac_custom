"""VAC POS PWA (/pos) — static endpoints.

Same shape as agriops_suite/count.py (the Stock Count PWA): the page itself is
www/pos.html and the dynamic surface is the "vac_pos_*" Server Scripts
(installer-managed on staging today; captured as fixtures at production
promotion). Only the raw non-HTML responses need app code:

- the service worker: StaticPage refuses .js under www/, /assets is
  proxy-cached immutable; a whitelisted method gives a stable no-cache URL and
  the `Service-Worker-Allowed: /pos` header widens its scope to the page.
- the web-app manifest: same .json-under-www restriction.
- csrf: hands the session's CSRF token to the app after an email+password
  login (the SW-cached shell cannot carry a fresh one).

NB: agriops_suite/pos.py is the DESK Point of Sale customization module
(get_items popularity override + zero-rate guard). This module is the
standalone counter PWA. Keep them separate.
"""

import json

import frappe
from werkzeug.wrappers import Response

SCOPE = "/pos"


@frappe.whitelist(methods=["GET"])
def csrf():
	"""CSRF token + identity for the CURRENT logged-in session.

	Not allow_guest: 403 here is exactly how the app decides to show the login
	screen (same contract as agriops_suite.count.csrf).
	"""
	user = frappe.session.user
	return {
		"csrf_token": frappe.sessions.get_csrf_token(),
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name") or user,
		"is_cashier": "POS Cashier" in frappe.get_roles(user),
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def sw():
	"""Serve public/js/pos_sw.js with the scope-widening header."""
	path = frappe.get_app_path("agriops_suite", "public", "js", "pos_sw.js")
	with open(path, encoding="utf-8") as f:
		body = f.read()
	resp = Response(body, mimetype="text/javascript")
	resp.headers["Service-Worker-Allowed"] = SCOPE
	resp.headers["Cache-Control"] = "no-cache"
	return resp


@frappe.whitelist(allow_guest=True, methods=["GET"])
def manifest():
	"""Web-app manifest so the counter device installs /pos to its home screen."""
	m = {
		"name": "VAC POS",
		"short_name": "VAC POS",
		"start_url": SCOPE,
		"scope": SCOPE,
		"display": "standalone",
		"background_color": "#f6f5f0",
		"theme_color": "#166b41",
		"icons": [
			{
				"src": "/assets/agriops_suite/images/pos-icon-192.png",
				"sizes": "192x192",
				"type": "image/png",
			},
			{
				"src": "/assets/agriops_suite/images/pos-icon-512.png",
				"sizes": "512x512",
				"type": "image/png",
			},
		],
	}
	resp = Response(json.dumps(m, ensure_ascii=False), mimetype="application/manifest+json")
	resp.headers["Cache-Control"] = "no-cache"
	return resp
