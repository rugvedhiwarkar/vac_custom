import frappe

from agriops_suite.fin_api import ALLOWED_USERS


def get_context(context):
	"""Financial Cockpit shell (/fin) — owner-only.

	Guests bounce to login; logged-in users outside the allowlist (defined
	once, in fin_api.ALLOWED_USERS) get a clean Not Permitted page — the same
	fence every data endpoint enforces, so an employee can neither open the
	page nor call the API behind it. no_cache so shell edits reach the
	browser on the next open.
	"""
	user = (frappe.session.user or "").lower()
	if user == "guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/fin"
		raise frappe.Redirect
	if user not in ALLOWED_USERS:
		frappe.throw("The Financial Cockpit is restricted.", frappe.PermissionError)
	context.no_cache = 1
	context.show_sidebar = 0
	return context
