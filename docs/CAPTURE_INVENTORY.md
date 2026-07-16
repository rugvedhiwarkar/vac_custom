# Capture Inventory — frozen 2026-07-07

Read-only inventory of what `agriops_suite` (ex `agro_suite`) captures, taken from **production**
(`vijayagrocentre.frappe.cloud`). This is the source of truth for the fixture
allowlists in `hooks.py`.

Installed apps on site **as of the 2026-07-07 freeze**: `frappe`, `erpnext`,
`india_compliance`, `insights`, `frappe_assistant_core`. No custom app of ours was
installed yet — we start clean.

> **Stale since 2026-07-16:** `insights` is **no longer installed** on production
> (or staging) — it disappeared when the installed-apps registry was rewritten
> 2026-07-15 18:48:31. Nothing in this inventory captures Insights, so the fixture
> allowlists are unaffected; the app list above is kept as the historical record of
> the freeze. For the live app set see CLAUDE.md, which is the source of truth.

## CAPTURE (ours)

### Custom DocTypes (15) — module in {Custom, Accounts, Stock}
Technical Name, Technical Name Pest*, Technical Name Crop*, Technical Name Weed*,
Pest, Crop, Weed, Grain Type, Product Detail Template, Product Detail Parameter*,
CD Scheme, CD Slab*, CD Scheme Vendor*, VAC Party, Credit Recovery.
(* = child table.)

### Custom Fields (25 of the 39 blank-module fields)
- Item Product Details (14): `pd_section, pd_manufacturer, product_detail_template,
  pd_seed_grain_type, pd_seed_days_till_maturity, pd_seed_plant_breed,
  pd_pesticide_technical_name, pd_tn_pesticide_type, pd_tn_dosage_per_acre,
  pd_tn_dosage_per_litre, pd_tn_pests, pd_tn_crops, pd_fertilizer_grade,
  pd_fertilizer_dosage_per_acre`
- Item Group (1): `product_detail_template`
- Busy provenance (10): `busy_voucher_no` + `busy_voucher_ref` on Sales Invoice,
  Purchase Invoice, Stock Entry, Journal Entry, Payment Entry

### Client Scripts (3)
Credit Recovery-Form, Credit Recovery-List, Item Product Detail Molecule Fetch.

### Server Scripts (2)
Credit Recovery Validate (DocType Event), Credit Recovery Daily Refresh
(Scheduler Event).

### Workspaces (3)
Credit Recovery Dashboard, Cash Discount, Product Details.

### Property Setters (222)
All site-level (blank-module) property setters created **2026-06-10 onward** —
our manual Customize Form tweaks + the claude-agent Product Details reorderings.
Filter: `{"creation": [">=", "2026-06-10 00:00:00"]}`. Top doc_types: Purchase
Receipt, Purchase/Sales Invoice, Sales Order, Delivery Note, Quotation.
EXCLUDES the 107-record 2026-06-09 setup burst (see EXCLUDE + Open item 2).

## EXCLUDE (app-owned or standard — NOT ours)

- **Custom fields (13 of the 39 blank-module):** `User-assistant_enabled`,
  `Custom DocPerm/DocPerm/DocShare-impersonate` (MCP assistant app);
  `Address-tax_category`, `Address-is_your_company_address`,
  `Contact-is_billing_contact`, `Communication-company`, `Email Account-company`,
  `UTM Campaign-crm_campaign`, `Print Settings-compact_item_print`,
  `Print Settings-print_uom_after_quantity`,
  `Print Settings-print_taxes_with_zero_amount` (standard ERPNext/CRM/regional).
- **Orphaned custom field:** `BusyWin Masters Import-dry_run` — its DocType was
  deleted, so the field is dangling. Excluded (see Open item 1).
- **466 custom fields** in modules GST India (457), Income Tax India (7),
  Audit Trail (2) — owned by India Compliance et al.

## DATA (reproduced by seed or masters, NOT blind fixtures)

- Reference masters (one-time seed): Technical Name 1,079, Pest 783, Weed 360,
  Crop 256, Grain Type 5, Product Detail Template 3.
- Operational/large, excluded entirely: VAC Party 1,708; Credit Recovery 0 (live
  tracker); tagged Item records.
- **Income-account routing is DATA, not a script:** native ERPNext via Item
  Defaults (1,120 Item-level + 63 Item Group-level income accounts). The
  "engine 2337950" from memory is NOT a custom script — confirmed no script
  references income. Nothing to fixture for it.

## OPEN ITEMS (resolve in Phase 2)

1. **`BusyWin Masters Import` DocType — RESOLVED 2026-07-07.** The DocType does
   NOT exist (deleted). `BusyWin Masters Import-dry_run` is an ORPHANED custom
   field left behind. Excluded from capture. Optional prod cleanup: delete the
   orphan field — separate, needs an explicit go-ahead.
2. **Property Setters — RESOLVED 2026-07-07.** Captured the **222** site-level
   setters created 2026-06-10 onward (our UI tweaks). EXCLUDED the **107**-record
   2026-06-09 setup burst — a 12-second programmatic pass (India Compliance
   audit-trail `track_changes`, `default_print_format`, regional field hides)
   that a fresh ERPNext + India Compliance site recreates on its own. Verified:
   `sync_fixtures` imports the full set with exit code 0.
