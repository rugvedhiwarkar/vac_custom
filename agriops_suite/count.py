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

import io
import json

import frappe
from werkzeug.wrappers import Response

SCOPE = "/count"
ROLE = "Stock Counter"


def _assert_may_issue(user):
	"""Guard the one genuinely dangerous thing this module does.

	`pairing_card` decrypts and returns a User's API secret, so without a fence
	it would be an API-key exfiltration hole for ANY account on the site. Three
	conditions, all required:

	  1. the CALLER can administer users (System Manager);
	  2. the TARGET holds the Stock Counter role — you can only ever lift a
	     counting credential, never an accountant's or an owner's;
	  3. the TARGET is a Website User with no desk access, so even a counter
	     account that someone later promotes stops being printable.
	"""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(frappe._("Only a System Manager can issue a counting card."))

	target = frappe.db.get_value("User", user, ["name", "enabled", "user_type", "full_name"], as_dict=1)
	if not target:
		frappe.throw(frappe._("No such user: {0}").format(user))

	if ROLE not in frappe.get_roles(user):
		frappe.throw(frappe._(
			"{0} does not have the {1} role, so there is no counting card to issue."
		).format(user, ROLE))
	if target.user_type != "Website User":
		frappe.throw(frappe._(
			"{0} is a {1}. A counting card is only ever issued for a Website User "
			"- a desk account's key must never be printed onto a card."
		).format(user, target.user_type))
	return target


@frappe.whitelist()
def pairing_card(user, regenerate=0):
	"""QR + code for pairing one counter's phone with /count.

	Returns the EXISTING secret by default so a lost card can be reprinted
	without breaking a phone that is already paired. `regenerate=1` issues a
	new key pair, which deliberately invalidates every card handed out before.
	"""
	target = _assert_may_issue(user)
	regenerate = frappe.utils.cint(regenerate)

	from frappe.utils.password import get_decrypted_password

	secret = None
	if not regenerate:
		key = frappe.db.get_value("User", user, "api_key")
		if key:
			try:
				secret = get_decrypted_password("User", user, "api_secret",
				                                raise_exception=False)
			except Exception:
				secret = None
	if not secret:
		from frappe.core.doctype.user.user import generate_keys
		secret = generate_keys(user).get("api_secret")
		frappe.db.commit()

	key = frappe.db.get_value("User", user, "api_key")
	token = "%s:%s" % (key, secret)
	url = frappe.utils.get_url(SCOPE) + "#pair=" + token

	import pyqrcode
	buf = io.BytesIO()
	# SVG, not PNG: these get printed and taped to a wall, and it stays crisp at
	# any size without shipping PIL into the response.
	pyqrcode.create(url, error="M").svg(
		buf, scale=7, quiet_zone=2, xmldecl=False, svgns=True,
		background="#ffffff", module_color="#111111")

	return {
		"user": user,
		"full_name": target.full_name or user,
		"enabled": target.enabled,
		"token": token,
		"url": url,
		"svg": buf.getvalue().decode("utf-8"),
		"site": frappe.utils.get_url(),
		"regenerated": bool(regenerate) or not bool(key),
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
