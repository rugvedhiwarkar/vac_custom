"""
Renumber all migrated vouchers to  <TYPE><FY2>-<#####>
    Sales Invoice        -> SI24-00001
    Purchase Invoice     -> PI24-00001
    Journal Entry        -> JE24-00001
    Payment Entry        -> PE24-00001
    Stock Entry          -> SE24-00001
    Purchase Receipt     -> PR24-00001
    Stock Reconciliation -> SREC24-00001

FY2 = fiscal year (Apr-Mar) 2-digit start: 24 = FY2024-25.  Numbered chronologically
within each (doctype, FY) by posting_date then creation.

DORMANT one-time operational tool — wired to no hook; runs only when executed.
RUN ON THE TARGET SITE'S BENCH ONLY (staging first). Examples:
    # 1. dry-run: build + persist the old->new map, reconcile snapshot, NO writes
    bench --site <site> execute agriops_suite.renumber.run --kwargs "{'dry_run': True}"
    # 2. apply (after dry-run reviewed):
    bench --site <site> execute agriops_suite.renumber.run --kwargs "{'dry_run': False}"
    # 3. verify only (recompute reconcile + orphan scan):
    bench --site <site> execute agriops_suite.renumber.verify
    # 4. rollback (swap new->old using the persisted map):
    bench --site <site> execute agriops_suite.renumber.rollback

Safety properties:
  * dry_run default True — the map + reconcile snapshot are produced with zero writes.
  * Idempotent / resumable — a doc already at its new name is skipped; the map is
    built once and persisted, so a re-run continues where it stopped.
  * New namespace (SI24-*) is DISJOINT from old (SINV-26-*) => no transient collisions.
  * frappe.rename_doc(force=True) handles the doc identity, child-table parents, and
    every Link / Dynamic-Link reference. The Data-keyed ledger tables (GL/SLE/PLE...),
    which rename_doc does NOT touch, are patched explicitly and reported per table.
  * Reconcile gate: GL debit=credit unchanged, per-type ledger counts unchanged,
    outstanding unchanged, ZERO orphaned ledger rows. verify() fails loudly otherwise.
"""

import frappe, json, os, time

# (doctype, new prefix)
SPEC = [
    ("Sales Invoice", "SI"),
    ("Purchase Invoice", "PI"),
    ("Journal Entry", "JE"),
    ("Payment Entry", "PE"),
    ("Stock Entry", "SE"),
    ("Purchase Receipt", "PR"),
    ("Stock Reconciliation", "SREC"),
]
PAD = 5          # SI24-00001
CHUNK = 200      # commit every N renames

# (table, type_column, name_column) rows keyed on voucher/against by Data, NOT Link.
# rename_doc will NOT update these — we patch them explicitly. Missing tables/columns
# on a given site are auto-skipped (verified against information_schema at runtime).
PATCH_TARGETS = [
    ("GL Entry", "voucher_type", "voucher_no"),
    ("GL Entry", "against_voucher_type", "against_voucher"),
    ("Stock Ledger Entry", "voucher_type", "voucher_no"),
    ("Payment Ledger Entry", "voucher_type", "voucher_no"),
    ("Payment Ledger Entry", "against_voucher_type", "against_voucher_no"),
    ("Advance Payment Ledger Entry", "voucher_type", "voucher_no"),
    ("Advance Payment Ledger Entry", "against_voucher_type", "against_voucher_no"),
    ("Serial and Batch Bundle", "voucher_type", "voucher_no"),
    ("Stock Reservation Entry", "voucher_type", "voucher_no"),
    ("Repost Item Valuation", "voucher_type", "voucher_no"),
    ("Repost Payment Ledger Items", "voucher_type", "voucher_no"),
    ("Repost Accounting Ledger Items", "voucher_type", "voucher_no"),
    ("Unreconcile Payment", "voucher_type", "voucher_no"),
]

MAP_FILE = os.path.join(frappe.get_site_path(), "voucher_rename_map.json")


# ----------------------------------------------------------------------------- helpers
def _fy2(d):
    y = d.year if d.month >= 4 else d.year - 1
    return str(y)[-2:]

def _col_exists(table, col):
    return bool(frappe.db.sql(
        """SELECT 1 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s LIMIT 1""",
        (f"tab{table}", col)))

def _active_patch_targets():
    """Filter PATCH_TARGETS to those that actually exist on this site."""
    out = []
    for table, tcol, ncol in PATCH_TARGETS:
        if _col_exists(table, tcol) and _col_exists(table, ncol):
            out.append((table, tcol, ncol))
    return out


# ----------------------------------------------------------------------------- map
def build_map(persist=True):
    """Deterministic old->new for every submitted doc. Chronological within (type, FY)."""
    mapping = {}   # doctype -> [ {old, new, posting_date} ]
    for dt, pfx in SPEC:
        rows = frappe.db.sql(
            f"SELECT name, posting_date, creation FROM `tab{dt}` WHERE docstatus=1",
            as_dict=True)
        buckets = {}
        for r in rows:
            if not r.posting_date:
                frappe.throw(f"{dt} {r.name} has no posting_date — resolve before renumber")
            buckets.setdefault(_fy2(r.posting_date), []).append(r)
        dt_rows = []
        for fy, rs in buckets.items():
            rs.sort(key=lambda r: (r.posting_date, r.creation, r.name))
            for i, r in enumerate(rs, 1):
                dt_rows.append({"old": r.name,
                                "new": f"{pfx}{fy}-{i:0{PAD}d}",
                                "posting_date": str(r.posting_date)})
        mapping[dt] = dt_rows
    if persist:
        with open(MAP_FILE, "w") as f:
            json.dump(mapping, f, indent=0)
    total = sum(len(v) for v in mapping.values())
    print(f"[map] built {total} old->new pairs across {len(mapping)} doctypes -> {MAP_FILE}")
    return mapping

def _load_map():
    if not os.path.exists(MAP_FILE):
        return build_map()
    with open(MAP_FILE) as f:
        return json.load(f)


# ----------------------------------------------------------------------------- reconcile
def snapshot():
    """Numbers that MUST be invariant across the rename (names aside)."""
    gl = frappe.db.sql("SELECT SUM(debit), SUM(credit) FROM `tabGL Entry`")[0]
    snap = {
        "gl_debit": float(gl[0] or 0),
        "gl_credit": float(gl[1] or 0),
        "gl_by_type": dict(frappe.db.sql(
            "SELECT voucher_type, COUNT(*) FROM `tabGL Entry` GROUP BY voucher_type")),
        "sle_by_type": dict(frappe.db.sql(
            "SELECT voucher_type, COUNT(*) FROM `tabStock Ledger Entry` GROUP BY voucher_type")),
        "ple_by_type": dict(frappe.db.sql(
            "SELECT voucher_type, COUNT(*) FROM `tabPayment Ledger Entry` GROUP BY voucher_type")),
        "si_outstanding": float(frappe.db.sql(
            "SELECT SUM(outstanding_amount) FROM `tabSales Invoice` WHERE docstatus=1")[0][0] or 0),
        "pi_outstanding": float(frappe.db.sql(
            "SELECT SUM(outstanding_amount) FROM `tabPurchase Invoice` WHERE docstatus=1")[0][0] or 0),
        "orphans": _orphan_counts(),
    }
    return snap

def _orphan_counts():
    """Ledger rows whose voucher_no has no matching parent document — must stay 0."""
    out = {}
    for table in ("GL Entry", "Stock Ledger Entry", "Payment Ledger Entry"):
        n = 0
        for dt, _pfx in SPEC:
            n += frappe.db.sql(
                f"""SELECT COUNT(*) FROM `tab{table}` le
                    LEFT JOIN `tab{dt}` d ON d.name = le.voucher_no
                    WHERE le.voucher_type=%s AND d.name IS NULL""", dt)[0][0]
        out[table] = n
    return out

def verify(before=None):
    """Recompute snapshot; compare to `before` if given. Print PASS/FAIL per invariant."""
    after = snapshot()
    print("[verify] orphaned ledger rows (must be 0):", after["orphans"])
    print(f"[verify] GL debit={after['gl_debit']:.2f} credit={after['gl_credit']:.2f} "
          f"balanced={abs(after['gl_debit']-after['gl_credit'])<0.01}")
    ok = (abs(after["gl_debit"] - after["gl_credit"]) < 0.01
          and all(v == 0 for v in after["orphans"].values()))
    if before:
        for k in ("gl_debit", "gl_credit", "si_outstanding", "pi_outstanding",
                  "gl_by_type", "sle_by_type", "ple_by_type"):
            same = before[k] == after[k]
            ok = ok and same
            print(f"[verify] {k}: {'OK' if same else 'CHANGED  '+str(before[k])+' -> '+str(after[k])}")
    print("[verify] RESULT:", "PASS" if ok else "FAIL")
    return ok


# ----------------------------------------------------------------------------- apply
def _patch_ledgers(dt, old, new, targets):
    patched = 0
    for table, tcol, ncol in targets:
        frappe.db.sql(
            f"UPDATE `tab{table}` SET `{ncol}`=%s WHERE `{tcol}`=%s AND `{ncol}`=%s",
            (new, dt, old))
        # sql() returns () for an UPDATE (not a rowcount) — `int += ()` would raise
        # TypeError and abort apply/rollback. Read the affected rows off the cursor.
        patched += frappe.db._cursor.rowcount or 0
    return patched

def run(dry_run=True):
    t0 = time.time()
    print(f"=== renumber_vouchers  site={frappe.local.site}  dry_run={dry_run} ===")
    before = snapshot()
    print(f"[pre] GL debit={before['gl_debit']:.2f} credit={before['gl_credit']:.2f} "
          f"orphans={before['orphans']}")
    # Load the reviewed map if it already exists; only build+persist on the very
    # first run. Previously this rebuilt from CURRENT DB state every call, so a
    # re-run (or post-apply dry-run) overwrote the good map with an all-identity
    # one — silently destroying rollback. To force a rebuild, delete the map file.
    mapping = _load_map()

    if dry_run:
        # show first/last of each doctype and stop
        for dt, _pfx in SPEC:
            rows = mapping[dt]
            if rows:
                print(f"[dry] {dt}: {len(rows)}  e.g. {rows[0]['old']} -> {rows[0]['new']}"
                      f"  ...  {rows[-1]['old']} -> {rows[-1]['new']}")
        print("[dry] no writes performed. Review, then run with dry_run=False.")
        return

    targets = _active_patch_targets()
    print("[apply] ledger patch targets:", [f"{t}.{c}" for t, _tc, c in targets])
    frappe.flags.in_migrate = True
    done = ledger = 0
    for dt, _pfx in SPEC:
        for row in mapping[dt]:
            old, new = row["old"], row["new"]
            if old == new or not frappe.db.exists(dt, old):
                continue  # already renamed / resumable skip
            frappe.rename_doc(dt, old, new, force=True, rebuild_search=False,
                              show_alert=False)
            ledger += _patch_ledgers(dt, old, new, targets)
            done += 1
            if done % CHUNK == 0:
                frappe.db.commit()
                print(f"[apply] {done} renamed, {ledger} ledger rows patched "
                      f"({time.time()-t0:.0f}s)")
    frappe.db.commit()
    print(f"[apply] DONE {done} renamed, {ledger} ledger rows patched "
          f"({time.time()-t0:.0f}s)")
    verify(before)

def rollback():
    """Swap new -> old using the persisted map (same patch logic, reversed)."""
    # Abort loudly if the map is gone: _load_map would rebuild it from the already
    # renamed DB (all old==new), so rollback would restore NOTHING while printing
    # success. The map is the only record of the original names.
    if not os.path.exists(MAP_FILE):
        frappe.throw(
            f"No rename map at {MAP_FILE} — cannot roll back. Restore the map file "
            f"(or a site backup); rebuilding it from renamed docs yields a no-op map."
        )
    with open(MAP_FILE) as f:
        mapping = json.load(f)
    targets = _active_patch_targets()
    frappe.flags.in_migrate = True
    done = 0
    for dt, _pfx in SPEC:
        for row in mapping[dt]:
            old, new = row["old"], row["new"]
            if old == new or not frappe.db.exists(dt, new):
                continue
            frappe.rename_doc(dt, new, old, force=True, rebuild_search=False, show_alert=False)
            _patch_ledgers(dt, new, old, targets)
            done += 1
            if done % CHUNK == 0:
                frappe.db.commit()
    frappe.db.commit()
    print(f"[rollback] restored {done} documents to original names")
