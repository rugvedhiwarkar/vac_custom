app_name = "vac_custom"
app_title = "VAC Custom"
app_publisher = "Vijay Agro Centre"
app_description = (
    "Vijay Agro Centre ERPNext customizations captured as versioned fixtures "
    "(custom DocTypes, fields, scripts, workspaces) for reproducible "
    "staging <-> production."
)
app_email = "rugvedhiwarkar@gmail.com"
app_license = "mit"

# ---------------------------------------------------------------------------
# Fixtures — the reproducible "recipe" for our customizations.
# Exported/imported as JSON under vac_custom/fixtures/ and applied on
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
                    "CD Scheme Vendor",
                    "VAC Party",
                    "Credit Recovery",
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
                    # Migration tool toggle
                    "BusyWin Masters Import-dry_run",
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
                ],
            ]
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
                    "Cash Discount",
                    "Product Details",
                ],
            ]
        },
    },

    # --- Property Setters ---------------------------------------------------
    # NOT FINALIZED. The 329 site property setters are a MIX of our UI
    # customizations and an India-Compliance / ERPNext setup burst
    # (2026-06-09 19:29). Do NOT blanket-export. Phase 2/5 will start from the
    # conservative set below (our custom DocTypes + our custom fields +
    # claude-agent-owned) and let the staging reconcile surface any true gaps.
    # {
    #     "dt": "Property Setter",
    #     "filters": {"doc_type": ["in", [ <our custom doctypes> ]]},
    # },
]
