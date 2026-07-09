app_name = "agro_suite"
app_title = "Agro Suite"
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

# ---------------------------------------------------------------------------
# Fixtures — the reproducible "recipe" for our customizations.
# Exported/imported as JSON under agro_suite/fixtures/ and applied on
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
                    "Credit Recovery",
                    "Credit Recovery Follow-up",
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
                    "Credit Recovery-Form",
                    "Credit Recovery-List",
                    "Item Product Detail Molecule Fetch",
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
                    "Credit Recovery Validate",
                    "Credit Recovery Daily Refresh",
                    "Credit Recovery Fetch Balance",
                    "Credit Recovery Avg Days",
                    "Credit Recovery Due Followups",
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
            "name": ["in", ["CR Outstanding by Status", "CR Outstanding by Territory"]]
        },
    },

    # --- Our Reports (non-standard, DB-stored) ------------------------------
    {
        "dt": "Report",
        "filters": {
            "name": ["in", ["Credit Recovery Follow-ups", "VAC Customer Ledger Summary"]]
        },
    },

    # --- v16 navigation (Workspace Sidebar + Desktop Icon per workspace) ----
    # NOTE: keep standard=0 — programmatic standard=1 sidebars/icons don't
    # render (frappe #38182/#38370). Icons must end up owned by Administrator
    # to be visible to all users; fixture sync (runs as Administrator) does this.
    {
        "dt": "Workspace Sidebar",
        "filters": {
            "name": ["in", ["Credit Recovery", "SchemeWise", "Product Details"]]
        },
    },
    {
        "dt": "Desktop Icon",
        "filters": {
            "name": ["in", ["Credit Recovery", "SchemeWise", "Product Details"]]
        },
    },

    # --- Our Workspaces -----------------------------------------------------
    {
        "dt": "Workspace",
        "filters": {
            "name": [
                "in",
                [
                    "Credit Recovery Dashboard",
                    "SchemeWise",
                    "Product Details",
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
