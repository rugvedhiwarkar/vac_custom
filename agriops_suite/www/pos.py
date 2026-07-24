import frappe


def get_context(context):
	"""VAC POS PWA shell (/pos).

	Self-contained single-file counter app (inline CSS+JS, Marathi-first) for
	billing at the shop counter: local catalog, offline outbox, cash/UPI/udhaar
	checkout, 80 mm receipt print. Guest-viewable: with no session it shows only
	the login screen (same contract as /count).

	Staging-first gate: the app's dynamic surface is the vac_pos_* Server
	Scripts, which exist only on sites where POS PWA Phase 1 was installed.
	Where they are absent (production until promotion) the page renders a
	plain "not enabled" notice — shipping this code in a shared-bench deploy
	surfaces nothing there.

	Served no_cache so edits reach devices on their next online open (the
	service worker layers stale-while-revalidate on top).
	"""
	context.no_cache = 1
	context.show_sidebar = 0
	context.pos_enabled = 1 if frappe.db.exists("Server Script", "vac_pos_catalog") else 0
	context.csrf_token = ""
	if frappe.session.user and frappe.session.user != "Guest":
		try:
			context.csrf_token = frappe.sessions.get_csrf_token()
		except Exception:
			context.csrf_token = ""
	return context
