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
# "Fast Journal" button on the Point of Sale screen (Cash Desk). The JS is
# self-gating: it renders only on sites where the `fast_voucher_config`
# Server Script API exists and returns enabled=1, so shipping this code to
# the shared bench does NOT surface it on a site until it is explicitly
# switched on (staging-first). The earlier "Log Payment" button was retired
# 2026-07-16 (its four "POS Cash Desk *" Server Scripts are disabled on both
# sites — the rollback path if it is ever needed again).
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

# Bare "/" -> each user's OWN workspace (admin -> Admin Desk, dad -> Director,
# nikita -> Employee Desk). A Website Route Redirect row cannot do this: it is
# global, one target for everyone — a `/` -> `/desk/vac` row is exactly what
# pinned all three of us to VAC. Deleting such a row is NOT sufficient either;
# bare "/" then 404s on a stock v16 (get_home_page() returns "/desk/<slug>" with
# a leading slash and path_resolver treats it as a template path). Full reasoning
# in agriops_suite/desk_home.py.
# ⚠️ Requires that Website Settings has NO `/` redirect row — a row short-circuits
# at path_resolver.py:44, before page_renderer hooks are ever consulted.
page_renderer = ["agriops_suite.desk_home.WorkspaceHomeRedirect"]

# keep chosen standard reports (e.g. General Ledger) running LIVE rather than as
# prepared/background reports — re-asserted after every migrate because a core
# ERPNext upgrade re-imports the standard report and would flip it back.
after_migrate = "agriops_suite.report_config.ensure_live_reports"

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
    # --- Roles our DocTypes' permissions reference -------------------------
    # MUST sync before the DocType block: Driver Slip's permission rows link
    # to Role "Driver", so a fresh site needs the role row first.
    # NB: keep is_custom=0 on Driver — a role with is_custom=1 cannot be
    # granted on a custom DocType by non-Administrator users (v16
    # validate_permission_for_all_role), which breaks REST/fixture edits.
    # Same for "Stock Counter" (Stock Count PWA /count): the Stock Count
    # Session permissions reference it, including a permlevel-1 row with
    # read=0/write=1 that lets the server snapshot the book position through
    # a counter's own save without ever showing it back to them.
    {
        "dt": "Role",
        "filters": {"name": ["in", ["Driver", "Stock Counter"]]},
    },

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
                    # StockPilot config single (goal-11 residual, captured
                    # 2026-07-16). Definition only — the VALUES (cutoffs,
                    # frequencies, frozen class map) are user-tunable runtime
                    # state and are deliberately NOT fixtures: a deploy must
                    # never reset them.
                    "StockPilot Settings",
                    # Driver Slip PWA (/slip): the phone-captured transport-log
                    # record. Series DRS- ("Expression (old style)" — format:
                    # autoname's bare {#####} shares ONE global counter).
                    # Multi-item: one slip = one document = one invoice with
                    # N lines; child table carries item/qty (+ office rate).
                    "Driver Slip",
                    "Driver Slip Item",
                    # Stock Count PWA (/count): one counting run + its lines.
                    # It exists because ERPNext DELETES zero-variance rows from
                    # a Stock Reconciliation (remove_items_with_no_change), so
                    # an item counted and found correct would otherwise leave
                    # no record and StockPilot would re-list it as overdue for
                    # ever. The session keeps every counted line; only real
                    # differences reach the reconciliation.
                    # ⛔ track_changes MUST stay 0 on Stock Count Session — a
                    # Version row stores the raw child dict, and get_docinfo
                    # serves Versions with ignore_permissions, which would hand
                    # the counter every permlevel-hidden book quantity.
                    "Stock Count Session",
                    "Stock Count Entry",
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
                    # Alias on Customer — alternate spelling of the same person kept
                    # from de-dup merges (owner rule 2026-07-16: merged record's name
                    # survives here), so counter staff can still find them by it.
                    "Customer-custom_alias",
                    # Village on Customer — backfilled from BusyWin
                    # MasterAddressInfo.Address1, which the migration bridge dropped in
                    # normalize.py before the bundle was built. Deliberately a Customer
                    # custom field rather than an Address record: Address.city feeds GST
                    # place-of-supply, and Busy has no state/pincode to populate one
                    # safely (PINCode set on 6 of 3,923 masters).
                    "Customer-custom_village",
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
                    # Stock Count Session review: builds the DRAFT Stock
                    # Reconciliation from the counted lines.
                    "Stock Count Session - Review",
                    "Item Product Detail Molecule Fetch",
                    # party-tools counterpart buttons (fixture-ized post-
                    # rename as tracked; call agriops_suite.party.*)
                    "VAC Party Counterpart - Customer",
                    "VAC Party Counterpart - Supplier",
                    # "Print" button group on the bill forms — one click to the
                    # matching VAC print format. Labels follow is_return (Debit
                    # Note / Credit Note / Goods Return Note). The Sales Invoice
                    # one also embeds the vac_wa WhatsApp helper.
                    "VAC Print Buttons - Sales Invoice",
                    "VAC Print Buttons - Delivery Note",
                    "VAC Print Buttons - Purchase Order",
                    "VAC Print Buttons - Purchase Receipt",
                    "VAC Print Buttons - Purchase Invoice",
                    # BOI Sihora RTGS/NEFT application / deposit slip off a
                    # Payment Entry (deposit slip on Internal Transfer)
                    "VAC Print Buttons - Payment Entry",
                    # BOI deposit slip with counted denominations
                    "VAC Print Buttons - Bank Deposit Voucher",
                    # Driver Slip office review: Make Invoice button + challan
                    # duplicate warning (the PWA's desk-side counterpart)
                    "Driver Slip - Make Invoice",
                ],
            ]
        },
    },

    # --- Our Print Formats (Busy-replica bill layouts) ----------------------
    # 4 sales + 4 purchase. The A4/A5 tax invoice and the two goods notes each
    # branch inside one HTML on doc.doctype / is_return, but every Print Format
    # RECORD is a distinct row and is listed explicitly here. Self-contained:
    # the fixture carries the full html+css, so a fresh site reproduces them on
    # migrate. Source lives in custom_doctypes/print_formats/ (pf_install.py).
    {
        "dt": "Print Format",
        "filters": {
            "name": [
                "in",
                [
                    "VAC Tax Invoice A4",
                    "VAC Tax Invoice A5",
                    "VAC Delivery Note",
                    "VAC Delivery Slip",
                    "VAC Purchase Order",
                    "VAC Goods Received Note",
                    "VAC Goods Received Slip",
                    "VAC Purchase Voucher",
                    # Bank of India (Sihora) RTGS/NEFT application form,
                    # pre-filled from a Payment Entry (vac_rtgs_neft.html)
                    "VAC RTGS NEFT Request",
                    # BOI deposit/pay-in slip: BDV variant auto-fills the
                    # counted denominations, PE variant prints them blank
                    "VAC Deposit Slip",
                    "VAC Deposit Slip PE",
                    # BOI Positive Pay System cheque requisition off a PE
                    "VAC PPS Requisition",
                ],
            ]
        },
    },

    # --- Our Server Scripts -------------------------------------------------
    # StockPilot: ONLY the two class-freeze scripts are fixtures — they are
    # stable infra tied to the StockPilot Settings doctype (the Daily
    # scheduler must survive every deploy). The suite's other server scripts
    # (Make Count SR / Make PO / 4 number-card endpoints) stay installer-
    # managed with the reports they serve, same boundary as the Report note
    # below — fixture-syncing them would clobber installer iterations.
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
                    "StockPilot Freeze Classes",
                    "StockPilot Class Freeze Refresh",
                    # Stock Count PWA (/count) endpoints. safe_exec notes:
                    # frappe.parse_json does NOT exist here (use json.loads),
                    # and frappe.get_all takes NO parent= kwarg (that is the
                    # REST spelling; in-process it is parent_doctype and a
                    # bare parent= raises TypeError).
                    "Stock Count Bootstrap",
                    "Stock Count Submit",
                    "Stock Count Make Recon",
                    "Stock Count Validate",
                    # Driver Slip PWA endpoints (DB records like LedgerLift's;
                    # safe_exec notes: no generate_hash / get_roles in there —
                    # uid fallback is "desk-"+doc.name, office check is
                    # user_type System User vs Website User)
                    "Driver Slip Validate",
                    "Driver Slip Submit",
                    "Driver Slip Bootstrap",
                    "Driver Slip Make Invoice",
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
                            "SchemeWise", "StockPilot"]]
        },
    },
    {
        "dt": "Desktop Icon",
        "filters": {
            "name": ["in", ["LedgerLift", "CashControl", "ItemIntel",
                            "SchemeWise", "StockPilot"]]
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
    # default_print_format for the bill forms -> the VAC formats. Kept in a
    # SEPARATE prefixed file (printdefaults_property_setter.json) because 4 of
    # the 5 records were created in the 2026-06-09 setup burst and the date
    # filter above deliberately excludes that burst — a plain merge would drop
    # them on the next export. `prefix` writes its own file, so the two Property
    # Setter captures never collide. (SI/DN existed pre-print-work; PI/PO/PR
    # were repointed/added 2026-07-16.)
    {
        "dt": "Property Setter",
        "prefix": "printdefaults",
        "filters": {
            "name": [
                "in",
                [
                    "Sales Invoice-main-default_print_format",
                    "Delivery Note-main-default_print_format",
                    "Purchase Invoice-main-default_print_format",
                    "Purchase Order-main-default_print_format",
                    "Purchase Receipt-main-default_print_format",
                ],
            ]
        },
    },
]
