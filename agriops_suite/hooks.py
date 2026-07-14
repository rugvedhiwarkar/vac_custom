app_name = "agriops_suite"
app_title = "AgriOps Suite"
app_publisher = "Vijay Agro Centre"
app_description = (
    "Vijay Agro Centre ERPNext customizations captured as versioned fixtures "
    "(custom DocTypes, fields, scripts, workspaces) for reproducible "
    "staging <-> production."
)
app_email = "rugvedhiwarkar@gmail.com"
app_license = "mit"

# ---------------------------------------------------------------------------
# Desk page extensions
# ---------------------------------------------------------------------------
# "Log Payment" button on the Point of Sale screen (Cash Desk). The JS is
# self-gating: it renders only on sites where the `pos_cash_desk_flags`
# Server Script API exists and returns enabled=1, so shipping this code to
# the shared bench does NOT surface it on production until that site is
# explicitly switched on (staging-first).
page_js = {"point-of-sale": "public/js/pos_cash_desk.js"}

# FinScope ledger features (persistent column order/hide/rename + Summarize
# drill-down) for the "FinScope - *" report delegates. Loaded desk-wide but
# self-gating on the report-name prefix, so standard reports — and sites where
# no FinScope reports exist yet — are untouched (same staging-first contract
# as the POS Cash Desk JS above).
#
# vac_theme: Claude-style desk theme (warm ivory/charcoal + terracotta). The
# CSS is scoped under html[data-vac-theme]; vac_theme.js sets that attribute
# only when boot carries vac_theme_enabled (per-site site_config flag, see
# boot.py) — same staging-first contract as the other includes.
# core_fixes: targeted runtime wraps for upstream ERPNext v16 bugs (currently:
# horizontal Financial Report Templates rendering blank via is_blank_row) —
# see the file header; drop entries as upstream fixes ship.
# vac_desk: breadcrumb home icon -> the user's default workspace (self-gating
# on User.default_workspace being set; stock /desk behaviour otherwise).
app_include_js = [
    # content-hashed bundle so an edit busts the immutable /assets cache (a raw
    # /assets/.../finscope.js path stays cached max-age=1yr and never updates)
    "finscope.bundle.js",
    # vac_theme is a .bundle.js so esbuild content-hashes its URL — a theme
    # edit changes the hash and busts the immutable /assets cache (a raw
    # /assets path stays cached max-age=1yr and never updates).
    "vac_theme.bundle.js",
    # morning greeting banner on the VAC landing workspace (theme-gated)
    "vac_home.bundle.js",
    "/assets/agriops_suite/js/core_fixes.js",
    "/assets/agriops_suite/js/vac_desk.js",
    # POS order-summary: extra "Invoice A4" / "Delivery Slip" print buttons
    "/assets/agriops_suite/js/vac_pos_print.js",
    # POS: allow items with NO preset price to be billed (cashier types the rate)
    # instead of ERPNext's hard "Price is not set for the item." block. Paired
    # with the block_zero_rate_pos before_submit safeguard so nothing bills at 0.
    # Content-hashed .bundle.js so an edit busts the immutable /assets cache.
    "vac_pos.bundle.js",
    # Fast Journal dialog (window.__fast_journal_open) — global so the POS header
    # button (pos_cash_desk.js), a desk button, or a shortcut can open it. UI-only;
    # self-gates on the fast_voucher_config Server Script (staging-only), so it is
    # inert on production until that site is switched on. Content-hashed bundle.
    "fast_journal.bundle.js",
]
app_include_css = [
    # content-hashed bundle (see vac_theme.bundle.js note) — cache-busts on edit
    "vac_theme.bundle.css",
    # CSS sibling of core_fixes.js — upstream v16 workarounds (see file
    # header; new rules need a NEW file, /assets is proxy-cached immutable)
    "/assets/agriops_suite/css/core_fixes.css",
]

# copies the per-site vac_theme_enabled flag into desk boot info
extend_bootinfo = "agriops_suite.boot.extend_bootinfo"

# POS item grid: most-billed items first instead of A-Z (agriops_suite/pos.py
# — pinned copy of core get_items v16.25.0 with a popularity ORDER BY;
# re-diff on every ERPNext upgrade).
override_whitelisted_methods = {
    "erpnext.selling.page.point_of_sale.point_of_sale.get_items": "agriops_suite.pos.get_items",
}

# Party-integration tools (see agriops_suite/party.py). The Customer/Supplier
# sync is gated per-site by vac_party_tools_enabled; the Party Link guard is
# ungated — it only rejects NEW duplicate links (erpnext #35184 gap), which
# is pure protection for Common Party Accounting on any site.
doc_events = {
    "Customer": {"on_update": "agriops_suite.party.sync_party_masters"},
    "Supplier": {"on_update": "agriops_suite.party.sync_party_masters"},
    "Party Link": {"validate": "agriops_suite.party.validate_party_link"},
    # POS "type the price at the register" safeguard: block completing a POS
    # (is_pos) sale that still has a zero-rate line. Non-POS invoices untouched.
    "Sales Invoice": {"before_submit": "agriops_suite.pos.block_zero_rate_pos"},
}

# ---------------------------------------------------------------------------
# Fixtures — the reproducible "recipe" for our customizations.
# Exported/imported as JSON under agriops_suite/fixtures/ and applied on
# `bench migrate`.
#
# IMPORTANT: filters use EXPLICIT allowlists, NOT a blanket module filter.
# On this site many blank-module records belong to India Compliance, the MCP
# assistant app, or ERPNext regional setup and must NOT be captured here.
# The frozen classification (2026-07-07) lives in docs/CAPTURE_INVENTORY.md.
# ---------------------------------------------------------------------------

fixtures = [
    # --- Our custom DocType definitions (records are seeded separately) -----
    {
        "dt": "DocType",
        "filters": {
            "name": [
                "in",
                [
                    "Technical Name",
                    "Technical Name Pest",
                    "Technical Name Crop",
                    "Technical Name Weed",
                    "Pest",
                    "Crop",
                    "Weed",
                    "Grain Type",
                    "Product Detail Template",
                    "Product Detail Parameter",
                    "CD Scheme",
                    "CD Slab",
                    "VAC Party",
                    # goal-12 rebrand: ex "Credit Recovery" (+ child); the
                    # workspace owns the plain "LedgerLift" name
                    "LedgerLift Tracker",
                    "LedgerLift Follow-up",
                ],
            ]
        },
    },

    # --- Our Custom Fields (excludes GST India / assistant / standard fields)
    {
        "dt": "Custom Field",
        "filters": {
            "name": [
                "in",
                [
                    # Product Details on Item
                    "Item-pd_section",
                    "Item-pd_manufacturer",
                    "Item-product_detail_template",
                    "Item-pd_seed_grain_type",
                    "Item-pd_seed_days_till_maturity",
                    "Item-pd_seed_plant_breed",
                    "Item-pd_pesticide_technical_name",
                    "Item-pd_tn_pesticide_type",
                    "Item-pd_tn_dosage_per_acre",
                    "Item-pd_tn_dosage_per_litre",
                    "Item-pd_tn_pests",
                    "Item-pd_tn_crops",
                    "Item-pd_fertilizer_grade",
                    "Item-pd_fertilizer_dosage_per_acre",
                    # Item Group -> template driver
                    "Item Group-product_detail_template",
                    # Busy migration provenance
                    "Sales Invoice-busy_voucher_no",
                    "Sales Invoice-busy_voucher_ref",
                    "Purchase Invoice-busy_voucher_no",
                    "Purchase Invoice-busy_voucher_ref",
                    "Stock Entry-busy_voucher_no",
                    "Stock Entry-busy_voucher_ref",
                    "Journal Entry-busy_voucher_no",
                    "Journal Entry-busy_voucher_ref",
                    "Payment Entry-busy_voucher_no",
                    "Payment Entry-busy_voucher_ref",
                    "Payment Entry-cd_scheme",
                    "Journal Entry-cd_scheme",
                ],
            ]
        },
    },

    # --- Our Client Scripts -------------------------------------------------
    {
        "dt": "Client Script",
        "filters": {
            "name": [
                "in",
                [
                    "LedgerLift-Form",
                    "LedgerLift-List",
                    "Item Product Detail Molecule Fetch",
                    # party-tools counterpart buttons (fixture-ized post-
                    # rename as tracked; call agriops_suite.party.*)
                    "VAC Party Counterpart - Customer",
                    "VAC Party Counterpart - Supplier",
                ],
            ]
        },
    },

    # --- Our Server Scripts -------------------------------------------------
    {
        "dt": "Server Script",
        "filters": {
            "name": [
                "in",
                [
                    "LedgerLift Validate",
                    "LedgerLift Daily Refresh",
                    "LedgerLift Fetch Balance",
                    "LedgerLift Avg Days",
                    "LedgerLift Due Followups",
                ],
            ]
        },
    },

    # --- Credit Recovery dashboard widgets ----------------------------------
    {
        "dt": "Number Card",
        "filters": {
            "name": [
                "in",
                [
                    "Total Outstanding",
                    "Total Promised",
                    "Total Critical Accounts",
                    "Follow-ups Due Today",
                    "Avg Days Outstanding",
                    "Recovery This Month",
                ],
            ]
        },
    },
    {
        "dt": "Dashboard Chart",
        "filters": {
            "name": ["in", ["LedgerLift Outstanding by Status",
                            "LedgerLift Outstanding by Territory"]]
        },
    },

    # --- Our Reports (non-standard, DB-stored) ------------------------------
    # NOTE: the FinScope - * and StockPilot * report suites stay installer-
    # managed (custom_doctypes/), not fixtures — they iterate too fast.
    {
        "dt": "Report",
        "filters": {
            "name": ["in", ["LedgerLift Follow-ups",
                            "LedgerLift Customer Ledger Summary",
                            "LedgerLift Status Breakdown",
                            "CashControl Day Book"]]
        },
    },

    # --- v16 navigation (Workspace Sidebar + Desktop Icon per workspace) ----
    # NOTE: keep standard=0 — programmatic standard=1 sidebars/icons don't
    # render (frappe #38182/#38370). Icons must end up owned by Administrator
    # to be visible to all users; fixture sync (runs as Administrator) does this.
    {
        "dt": "Workspace Sidebar",
        "filters": {
            "name": ["in", ["LedgerLift", "CashControl", "ItemIntel",
                            "SchemeWise", "StockPilot", "FinScope"]]
        },
    },
    {
        "dt": "Desktop Icon",
        "filters": {
            "name": ["in", ["LedgerLift", "CashControl", "ItemIntel",
                            "SchemeWise", "StockPilot", "FinScope"]]
        },
    },

    # --- Our Workspaces (all six brands' nav; the suites' reports/cards
    # stay installer-managed) ------------------------------------------------
    {
        "dt": "Workspace",
        "filters": {
            "name": [
                "in",
                [
                    "LedgerLift",
                    "CashControl",
                    "ItemIntel",
                    "SchemeWise",
                    "StockPilot",
                    "FinScope",
                ],
            ]
        },
    },

    # --- Our Property Setters (UI tweaks made via Customize Form) -----------
    # Captures our manual field-level customizations (2026-06-10 onward) plus
    # the claude-agent Product Details reorderings. EXCLUDES the 2026-06-09
    # setup burst — 107 records created in a 12-second programmatic pass at site
    # setup (India Compliance audit-trail `track_changes`, `default_print_format`
    # and regional field hides). A fresh ERPNext + India Compliance site
    # recreates those on its own, so re-asserting them from here would be wrong.
    {
        "dt": "Property Setter",
        "filters": {"creation": [">=", "2026-06-10 00:00:00"]},
    },
]
