# Capture Inventory — frozen 2026-07-07

Read-only inventory of what `vac_custom` captures, taken from **production**
(`vijayagrocentre.frappe.cloud`). This is the source of truth for the fixture
allowlists in `hooks.py`.

Installed apps on site: `frappe`, `erpnext`, `india_compliance`, `insights`,
`frappe_assistant_core`. No custom app of ours was installed yet — we start clean.

## CAPTURE (ours)

### Custom DocTypes (15) — module in {Custom, Accounts, Stock}
Technical Name, Technical Name Pest*, Technical Name Crop*, Technical Name Weed*,
Pest, Crop, Weed, Grain Type, Product Detail Template, Product Detail Parameter*,
CD Scheme, CD Slab*, CD Scheme Vendor*, VAC Party, Credit Recovery.
(* = child table.)

### Custom Fields (26 of the 39 blank-module fields)
- Item Product Details (14): `pd_section, pd_manufacturer, product_detail_template,
  pd_seed_grain_type, pd_seed_days_till_maturity, pd_seed_plant_breed,
  pd_pesticide_technical_name, pd_tn_pesticide_type, pd_tn_dosage_per_acre,
  pd_tn_dosage_per_litre, pd_tn_pests, pd_tn_crops, pd_fertilizer_grade,
  pd_fertilizer_dosage_per_acre`
- Item Group (1): `product_detail_template`
- Busy provenance (10): `busy_voucher_no` + `busy_voucher_ref` on Sales Invoice,
  Purchase Invoice, Stock Entry, Journal Entry, Payment Entry
- Migration tool (1): `BusyWin Masters Import-dry_run`

### Client Scripts (3)
Credit Recovery-Form, Credit Recovery-List, Item Product Detail Molecule Fetch.

### Server Scripts (2)
Credit Recovery Validate (DocType Event), Credit Recovery Daily Refresh
(Scheduler Event).

### Workspaces (3)
Credit Recovery Dashboard, Cash Discount, Product Details.

## EXCLUDE (app-owned or standard — NOT ours)

- **Custom fields (13 of the 39 blank-module):** `User-assistant_enabled`,
  `Custom DocPerm/DocPerm/DocShare-impersonate` (MCP assistant app);
  `Address-tax_category`, `Address-is_your_company_address`,
  `Contact-is_billing_contact`, `Communication-company`, `Email Account-company`,
  `UTM Campaign-crm_campaign`, `Print Settings-compact_item_print`,
  `Print Settings-print_uom_after_quantity`,
  `Print Settings-print_taxes_with_zero_amount` (standard ERPNext/CRM/regional).
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

1. **`BusyWin Masters Import` DocType** has a custom field (`dry_run`) but did NOT
   appear in the `custom=1` DocType list and is not owned by any installed app.
   Determine where it lives (leftover on-disk doctype? orphan?) and whether it
   must be captured, before finalizing.
2. **Property Setters (329, all blank-module):** a MIX of ours and an automated
   setup burst. 25 owned by `claude-agent@...` (2026-07-04, ours); ~200 in a
   `2026-06-09 19:29` burst across standard/India doctypes (setup/regional).
   Strategy: start conservative (our custom DocTypes + our custom fields +
   claude-agent-owned), then let the Phase 5 staging reconcile prove the set.
