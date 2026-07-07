# VAC Custom

A Frappe/ERPNext app that captures **Vijay Agro Centre's customizations as
versioned fixtures**, so staging and production stay reproducible and every
change lives in git instead of only in a live database.

## What it captures

- **15 custom DocTypes** — Technical Name (+ Pest/Crop/Weed child tables),
  Pest, Crop, Weed, Grain Type, Product Detail Template (+ Product Detail
  Parameter), CD Scheme (+ CD Slab, CD Scheme Vendor), VAC Party, Credit
  Recovery.
- **~26 custom fields** — Product Details on Item, the Item Group template
  driver, and Busy migration provenance fields (`busy_voucher_*`).
- **3 client scripts, 2 server scripts, 3 workspaces.**

## What it deliberately does NOT capture

- India Compliance / Income Tax / Audit Trail custom fields (owned by those
  apps — 466 fields).
- The MCP assistant app's fields (`assistant_enabled`, `impersonate`).
- Standard ERPNext/CRM/regional fields and the 2026-06-09 setup property-setter
  burst.
- **Data** (item tags, income-account defaults, reclass JEs, party/tracker
  records). Large reference masters (Technical Name, Pest, Crop, Weed, Grain
  Type) are handled by a **one-time seed**, not blind fixtures, so live edits
  are never overwritten on `bench migrate`.

See `docs/CAPTURE_INVENTORY.md` for the full frozen classification.

## Install / re-install (Frappe Cloud or bench)

```bash
# App is added to the bench group from its private GitHub repo via the
# Frappe Cloud dashboard, then:
bench --site <site> install-app vac_custom
bench --site <site> migrate      # applies fixtures
bench --site <site> clear-cache
```

Because fixtures are exported FROM production unchanged, installing on
production is expected to be a **no-op** against existing objects.

## Status

Under construction — see the plan and `docs/CAPTURE_INVENTORY.md`. Fixture JSON
is generated in Phase 3 (read-only from production); property-setter capture is
finalized during the staging reconcile (Phase 5).
