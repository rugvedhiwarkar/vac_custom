import frappe

# Standard ERPNext reports we run LIVE (prepared_report=0) so Reload shows
# CURRENT data instead of a cached "generated X ago" snapshot with a Rebuild
# step. ERPNext ships some of these as prepared/background reports; a core
# upgrade re-imports the standard report JSON and would flip them back, so we
# re-assert after every migrate. Idempotent and guarded for fresh sites.
#
# To make another report live, just add its exact name here.
#
# ⚠️ CHECK IT CAN ACTUALLY RUN LIVE FIRST. Some reports ship prepared because they
# genuinely cannot finish inside the gateway timeout — forcing those live gives a
# report that 504s instead of one that is fresh. Verify with:
#   /api/method/frappe.desk.query_report.run?report_name=X&filters=...&ignore_prepared_report=1
# "Accounts Receivable Summary" is deliberately NOT here: it returned HTTP 504 on
# exactly that check (2026-07-15), so it stays prepared (use its Rebuild button).
LIVE_REPORTS = [
    # measured live on PROD 2026-07-15 — all far under Frappe's 15s watcher:
    "General Ledger",             # 1.38s / 1848 rows
    "Item-wise Sales Register",   # 0.62s /  711 rows
    "Stock Ledger",               # 0.39s /  614 rows
    "Stock Balance",              # 1.28s /  732 rows
    "Stock Ageing",               # 0.88s
]


def ensure_live_reports():
    """after_migrate hook: keep LIVE_REPORTS running live.

    prepared_report=0 ALONE IS NOT ENOUGH. Frappe's Report.execute_script_report
    arms a threading.Timer for `threshold = 15` seconds on every live Script Report
    run and, if the run overruns, calls enable_prepared_report() which silently sets
    prepared_report back to 1:

        if not self.prepared_report and not self.disable_prepared_report_automation:
            prepared_report_watcher = threading.Timer(interval=threshold,
                function=enable_prepared_report, ...)

    So ONE slow run (wide date range, or a noisy-neighbour spike) permanently flips
    the report back to prepared, and this hook flips it live again on the next
    migrate — a tug-of-war the user sees as "it keeps reverting". Setting
    disable_prepared_report_automation=1 stops the watcher being armed at all.

    TRADEOFF: that watcher is a safety valve. With it off, a genuinely heavy run
    won't auto-protect — it just runs slow and can hit the ~60s gateway timeout.
    Only put reports here that are VERIFIED fast (see timings above), and re-measure
    with query_report.run?...&ignore_prepared_report=1 before adding new ones.
    """
    for name in LIVE_REPORTS:
        if not frappe.db.exists("Report", name):
            continue
        cur = frappe.db.get_value(
            "Report", name, ["prepared_report", "disable_prepared_report_automation"], as_dict=True
        )
        if cur and (cur.prepared_report or not cur.disable_prepared_report_automation):
            frappe.db.set_value(
                "Report", name, {"prepared_report": 0, "disable_prepared_report_automation": 1}
            )
            frappe.logger().info("agriops_suite: Report %r pinned live (prepared=0, automation off)" % name)
