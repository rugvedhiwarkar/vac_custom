import frappe


def extend_bootinfo(bootinfo):
	"""Per-site switch for the VAC Claude-style desk theme (staging-first).

	Reads `vac_theme_enabled` from the site's site_config.json, so the theme
	can be piloted on staging and later promoted to production without a
	redeploy: bench --site <site> set-config vac_theme_enabled 1
	"""
	bootinfo.vac_theme_enabled = frappe.conf.get("vac_theme_enabled") or 0
	# which palette: "1"/"claude" (default), "leaf", or "nature" (website-matched)
	bootinfo.vac_theme_variant = frappe.conf.get("vac_theme_variant") or "1"
	# Standard ledger reports (e.g. "General Ledger") to augment IN-PLACE with
	# FinScope features, per-site so it can be piloted on staging then promoted
	# without a redeploy — and toggled off by clearing the list:
	#   bench --site <site> set-config finscope_ledger_reports '["General Ledger"]' --parse
	bootinfo.finscope_ledger_reports = frappe.conf.get("finscope_ledger_reports") or []
