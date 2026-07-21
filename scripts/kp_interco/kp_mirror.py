"""KP inter-company mirror — construct Krushiyog Plant's books from VAC's records.

Runs BENCH-SIDE (needs doc.insert(set_name=...) for deterministic mirror names).
Plan: docs/kp_intercompany_plan.md. STAGING ONLY — the site guard below refuses
production outright; the prod run is a separate, user-gated step.

Mirror map (VAC source, docstatus=1  ->  KP company mirror):
  PI supplier=KP           -> Sales Invoice   customer "Vijay Agro Centre"   KPSI<tail>
  SI customer=KP           -> Purchase Invoice supplier "Vijay Agro Centre"  KPPI<tail>
  JE touching KP parties   -> Journal Entry (rows translated, see flip rules) KPJE<tail>
  PE party=KP              -> Journal Entry (cash leg -> Cash - KP)          KPJE-<name>
  VAC opening (is_opening) -> one opening JE Dr VAC receivable / Cr Temp Opening

Row translation for JEs (each mirror JE must balance or the JE is HELD):
  party = KP-as-supplier   -> party VAC-as-customer, dr/cr FLIPPED
  party = KP-as-customer   -> party VAC-as-supplier, dr/cr FLIPPED
  party = pseudo expense head -> party VAC-as-supplier, dr/cr FLIPPED
  other rows (VAC cash/bank/...) -> dr/cr FLIPPED, account =
        the pseudo-head's mapped expense/asset account if the JE carries
        exactly one pseudo-head, else Cash - KP if the account is cash/bank,
        else HOLD the JE for manual mapping (listed in preview).

Naming = idempotency: mirrors are named from the source tail (PI24-00179 ->
KPSI24-00179), set via insert(set_name=...) so no naming-series counter is
touched. Re-runs skip existing names. update_stock=0 everywhere (Phase A,
accounts-only) so no stock ledger, no reposts, no deadlock class.

Usage (from ~/frappe-bench/sites):
  ../env/bin/python /tmp/kp_mirror.py --site vac-staging.nvi.frappe.cloud preview
  ../env/bin/python /tmp/kp_mirror.py --site ... prereqs
  ../env/bin/python /tmp/kp_mirror.py --site ... go [--limit N] [--types si,pi,je,pe,opening]
  ../env/bin/python /tmp/kp_mirror.py --site ... reconcile
Log: everything also appends to /tmp/kp_mirror.log (full log, never tail).
"""
import argparse
import json
import sys
import traceback

import frappe

VAC = "Vijay Agro Centre"
KP = "Krushiyog Plant"
KP_PARTY = "Krushiyog Plant, Paraswada"
VAC_PARTY = "Vijay Agro Centre"          # customer+supplier created in KP books
CC = "Main - KP"
CASH_KP = "Cash - KP"
DEBTORS_KP = "Debtors - KP"
CREDITORS_KP = "Creditors - KP"
TEMP_OPEN_KP = "Temporary Opening - KP"
INTERFIRM_KP = "Inter-Firm Transfers - KP"   # suspense for non-party VAC legs
GST_COST_KP = "GST on Purchases (Unregistered) - KP"  # unclaimable GST folded to cost

# pseudo expense-head customers in VAC books -> KP account (created by prereqs)
HEADS = {
    "Krushiyog Labor Kharch":    ("Labour Kharch - KP", "Indirect Expenses - KP", "Expense Account"),
    "Krushiyog Itar Kharcha":    ("Itar Kharcha - KP", "Indirect Expenses - KP", "Expense Account"),
    "Krushiyog Freight Expense": ("Freight Kharch - KP", "Indirect Expenses - KP", "Expense Account"),
    "Krushiyog Capital Expense": ("Plant and Machinery - KP", "Fixed Assets - KP", "Fixed Asset"),
}
ALL_PARTIES = [KP_PARTY] + list(HEADS)

LOG = open("/tmp/kp_mirror.log", "a", buffering=1)


def log(msg):
    print(msg)
    LOG.write(msg + "\n")


def mirror_name(src_name, kind):
    # PI24-00179 -> KPSI24-00179 ; SI26-00081-1 -> KPPI26-00081-1 ; JE26-00648 -> KPJE26-00648
    if kind == "pe":
        return "KPJE-" + src_name
    swap = {"si": ("PI", "KPSI"), "pi": ("SI", "KPPI"), "je": ("JE", "KPJE")}[kind]
    # explicit raise, not assert: -O would strip the assert and then slice a wrong
    # prefix length, producing a garbage (non-idempotent) mirror name. Callers in
    # go() catch this and skip the one doc instead of aborting the whole run.
    if not src_name.startswith(swap[0]):
        raise ValueError(f"unexpected source name {src_name} (expected {swap[0]} prefix)")
    return swap[1] + src_name[len(swap[0]):]


def is_cashish(account):
    a = account.lower()
    return "cash" in a or "bank" in a or "till" in a


# ---------------------------------------------------------------- extraction
def extract():
    src = {}
    src["pi"] = frappe.get_all("Purchase Invoice",
        filters={"supplier": KP_PARTY, "docstatus": 1, "company": VAC},
        fields=["name", "posting_date", "is_return", "return_against",
                "grand_total", "rounded_total"],
        order_by="posting_date asc, is_return asc, name asc")
    src["si"] = frappe.get_all("Sales Invoice",
        filters={"customer": KP_PARTY, "docstatus": 1, "company": VAC},
        fields=["name", "posting_date", "is_return", "return_against",
                "grand_total", "rounded_total"],
        order_by="posting_date asc, is_return asc, name asc")
    je_names = [r[0] for r in frappe.db.sql(
        """select distinct parent from `tabJournal Entry Account`
           where party in %(p)s and docstatus = 1""", {"p": ALL_PARTIES})]
    src["je"] = frappe.get_all("Journal Entry",
        filters={"name": ["in", je_names], "docstatus": 1, "company": VAC,
                 "is_opening": "No"},
        fields=["name", "posting_date"], order_by="posting_date asc, name asc")
    src["pe"] = frappe.get_all("Payment Entry",
        filters={"party": KP_PARTY, "docstatus": 1, "company": VAC},
        fields=["name", "posting_date", "payment_type", "party_type",
                "paid_amount", "paid_to", "paid_from"],
        order_by="posting_date asc, name asc")
    # opening: VAC-side is_opening GL for the KP party (net credit = VAC owes KP)
    op = frappe.db.sql("""select
            sum(credit) - sum(debit) from `tabGL Entry`
            where party = %(p)s and is_opening = 'Yes' and is_cancelled = 0
              and company = %(c)s""", {"p": KP_PARTY, "c": VAC})[0][0] or 0
    src["opening_vac_owes_kp"] = float(op)
    return src


# ------------------------------------------------------------------ prereqs
def ensure_prereqs(dry=False):
    """Idempotent: KP company shell, VAC party records, internal flags, KP accounts."""
    actions = []

    # KP company: exists on prod (0-GL shell, standard CoA); the staging clone
    # predates the multi-company work, so create the same shell there. Standard
    # chart auto-creates Debtors/Creditors/Cash/Sales/COGS/Temporary Opening - KP
    # and the Main - KP cost center — the exact names this script relies on.
    if not frappe.db.exists("Company", KP):
        actions.append(f"CREATE Company {KP} (abbr KP, INR, standard CoA)")
        if not dry:
            frappe.get_doc({"doctype": "Company", "company_name": KP, "abbr": "KP",
                            "default_currency": "INR", "country": "India",
                            }).insert(ignore_permissions=True)
            frappe.db.commit()
    else:
        actions.append(f"exists: Company {KP}")

    # Phase A = accounts-only (periodic inventory): stock items on a PI must hit
    # the expense account directly, not Stock Received But Not Billed (found by
    # the smoke test: SRBNB posting with perpetual inventory on). Closing stock
    # enters via year-end JE per plan §2.3.
    if frappe.db.get_value("Company", KP, "enable_perpetual_inventory"):
        actions.append("SET Company KP enable_perpetual_inventory=0 (periodic, Phase A)")
        if not dry:
            frappe.db.set_value("Company", KP, "enable_perpetual_inventory", 0)
    else:
        actions.append("exists: perpetual inventory already off for KP")

    def ensure_party(doctype, flags):
        if frappe.db.exists(doctype, VAC_PARTY):
            actions.append(f"exists: {doctype} {VAC_PARTY}")
            return
        actions.append(f"CREATE {doctype} {VAC_PARTY} (internal, represents {VAC})")
        if dry:
            return
        d = frappe.get_doc({"doctype": doctype,
                            ("customer_name" if doctype == "Customer" else "supplier_name"): VAC_PARTY,
                            **flags})
        d.insert(set_name=VAC_PARTY, ignore_permissions=True)

    ensure_party("Customer", {"customer_group": "All Customer Groups", "territory": "All Territories",
                              "customer_type": "Company", "gst_category": "Registered Regular",
                              "is_internal_customer": 1, "represents_company": VAC})
    ensure_party("Supplier", {"supplier_group": "All Supplier Groups", "supplier_type": "Company",
                              "gst_category": "Registered Regular",
                              "is_internal_supplier": 1, "represents_company": VAC})

    # internal flags on the existing KP pair (forward one-click flow)
    for dt, fld in [("Customer", "is_internal_customer"), ("Supplier", "is_internal_supplier")]:
        cur = frappe.db.get_value(dt, KP_PARTY, fld)
        if cur:
            actions.append(f"exists: {dt} {KP_PARTY} {fld}=1")
        else:
            actions.append(f"SET {dt} {KP_PARTY} {fld}=1 represents={KP}")
            if not dry:
                frappe.db.set_value(dt, KP_PARTY, {fld: 1, "represents_company": KP})

    # allowed companies rows so the internal parties are usable in both books
    for dt, name, comp in [("Customer", VAC_PARTY, KP), ("Supplier", VAC_PARTY, KP),
                           ("Customer", KP_PARTY, VAC), ("Supplier", KP_PARTY, VAC)]:
        if dry or not frappe.db.exists(dt, name):
            continue
        d = frappe.get_doc(dt, name)
        if comp not in [r.company for r in (d.get("companies") or [])]:
            d.append("companies", {"company": comp})
            d.save(ignore_permissions=True)
            actions.append(f"allowed company {comp} on {dt} {name}")

    # KP-side accounts for the pseudo heads
    for head, (acct, parent, atype) in HEADS.items():
        if frappe.db.exists("Account", acct):
            actions.append(f"exists: Account {acct}")
            continue
        actions.append(f"CREATE Account {acct} under {parent} ({atype})")
        if dry:
            continue
        frappe.get_doc({"doctype": "Account", "company": KP,
                        "parent_account": parent, "account_type": atype if atype != "Expense Account" else "",
                        "account_name": acct.replace(" - KP", ""),
                        "root_type": "Asset" if atype == "Fixed Asset" else "Expense",
                        }).insert(ignore_permissions=True)
    # unclaimable GST on purchases from VAC (KP unregistered -> no ITC; the tax
    # is part of cost). Direct expense so it sits with COGS in KP's P&L.
    if not frappe.db.exists("Account", GST_COST_KP):
        parent = next((p for p in ["Direct Expenses - KP", "Indirect Expenses - KP"]
                       if frappe.db.exists("Account", p)), None)
        assert parent, "no parent group for GST cost account"
        actions.append(f"CREATE Account {GST_COST_KP} under {parent}")
        if not dry:
            frappe.get_doc({"doctype": "Account", "company": KP, "parent_account": parent,
                            "account_name": "GST on Purchases (Unregistered)",
                            "root_type": "Expense"}).insert(ignore_permissions=True)
    else:
        actions.append(f"exists: Account {GST_COST_KP}")

    # suspense for VAC legs that are neither party nor cash nor expense-head
    if not frappe.db.exists("Account", INTERFIRM_KP):
        parent = next((p for p in ["Current Liabilities - KP", "Current Assets - KP"]
                       if frappe.db.exists("Account", p)), None)
        assert parent, "no parent group for Inter-Firm Transfers - KP"
        actions.append(f"CREATE Account {INTERFIRM_KP} under {parent}")
        if not dry:
            frappe.get_doc({"doctype": "Account", "company": KP, "parent_account": parent,
                            "account_name": "Inter-Firm Transfers",
                            "root_type": "Liability" if "Liabilities" in parent else "Asset",
                            }).insert(ignore_permissions=True)
    else:
        actions.append(f"exists: Account {INTERFIRM_KP}")
    for a in [CASH_KP, DEBTORS_KP, CREDITORS_KP, TEMP_OPEN_KP, "Sales - KP",
              "Cost of Goods Sold - KP"]:
        assert frappe.db.exists("Account", a), f"KP account missing: {a}"
    if not dry:
        frappe.db.commit()
    return actions


# ------------------------------------------------------------- JE translation
def translate_je(src_doc):
    """Return (rows, holds). rows = KP mirror rows; holds = reason string or None."""
    heads_in = {r.party for r in src_doc.accounts if r.party in HEADS}
    rows, unmapped = [], []
    for r in src_doc.accounts:
        dr, cr = float(r.debit or 0), float(r.credit or 0)
        if r.party == KP_PARTY and r.party_type == "Supplier":
            rows.append({"account": DEBTORS_KP, "party_type": "Customer", "party": VAC_PARTY,
                         "debit_in_account_currency": cr, "credit_in_account_currency": dr,
                         "user_remark": f"mirror of {src_doc.name}: KP-supplier leg"})
        elif r.party == KP_PARTY and r.party_type == "Customer":
            rows.append({"account": CREDITORS_KP, "party_type": "Supplier", "party": VAC_PARTY,
                         "debit_in_account_currency": cr, "credit_in_account_currency": dr,
                         "user_remark": f"mirror of {src_doc.name}: KP-customer leg"})
        elif r.party in HEADS:
            rows.append({"account": CREDITORS_KP, "party_type": "Supplier", "party": VAC_PARTY,
                         "debit_in_account_currency": cr, "credit_in_account_currency": dr,
                         "user_remark": f"mirror of {src_doc.name}: {r.party} (cost funded by VAC)"})
        elif r.party:
            # THIRD-PARTY book transfer (VCMF, farmers, Shetikarita, KFC...):
            # VAC moved value between KP's ledger and this party. KP's books
            # absorb the claim/obligation: SAME party, same role, dr/cr flipped.
            # These become real open balances in KP's aging — the accountant's
            # reclass list (16 such JEs, ≈₹40.2L, inspected 2026-07-16).
            acct = DEBTORS_KP if r.party_type == "Customer" else CREDITORS_KP
            rows.append({"account": acct, "party_type": r.party_type, "party": r.party,
                         "debit_in_account_currency": cr, "credit_in_account_currency": dr,
                         "user_remark": f"mirror of {src_doc.name}: third-party transfer ({r.party})"})
        else:
            # VAC's own leg (cash/bank/asset/inter-firm) — flipped; account:
            # exactly-one-pseudo-head -> that head's expense/asset account;
            # cash-ish -> Cash - KP; anything else -> Inter-Firm Transfers
            # suspense (accountant reclasses; source account kept in remark).
            if len(heads_in) == 1:
                acct = HEADS[next(iter(heads_in))][0]
            elif is_cashish(r.account):
                acct = CASH_KP
            else:
                acct = INTERFIRM_KP
            rows.append({"account": acct,
                         "debit_in_account_currency": cr, "credit_in_account_currency": dr,
                         "user_remark": f"mirror of {src_doc.name}: VAC leg {r.account}"})
    if unmapped:
        return None, f"unmapped non-party legs: {sorted(set(unmapped))}"
    tdr = round(sum(x["debit_in_account_currency"] for x in rows), 2)
    tcr = round(sum(x["credit_in_account_currency"] for x in rows), 2)
    if abs(tdr - tcr) > 0.01:
        return None, f"mirror unbalanced dr={tdr} cr={tcr}"
    rows = [x for x in rows if x["debit_in_account_currency"] or x["credit_in_account_currency"]]
    for x in rows:
        x["cost_center"] = CC
    return rows, None


# ---------------------------------------------------------------- doc makers
def make_si(src_name):
    s = frappe.get_doc("Purchase Invoice", src_name)   # VAC buys -> KP sells
    # KP is unregistered and cannot charge GST; a source PI carrying tax would
    # mean VAC recorded tax on an unregistered purchase — surface it, don't guess.
    if abs(s.base_total_taxes_and_charges or 0) > 0.01:
        return None, f"source {s.name} carries taxes {s.base_total_taxes_and_charges} on an unregistered KP sale"
    if abs(float(s.paid_amount or 0)) > 0.005:
        return None, f"source {s.name} carries embedded payment {s.paid_amount} — extend mirror first"
    d = frappe.get_doc({
        "doctype": "Sales Invoice", "company": KP, "customer": VAC_PARTY,
        "posting_date": str(s.posting_date), "set_posting_time": 1,
        "due_date": str(s.posting_date), "currency": "INR", "conversion_rate": 1,
        "selling_price_list": "Standard Selling", "ignore_pricing_rule": 1,
        "update_stock": 0, "is_return": s.is_return,
        "return_against": mirror_name(s.return_against, "si") if s.get("return_against") else None,
        "cost_center": CC, "debit_to": DEBTORS_KP, "disable_rounded_total": 0,
        "remarks": f"Mirror of VAC {s.name} (KP inter-company books)",
        "items": [{"item_code": r.item_code, "item_name": r.item_name, "qty": r.qty,
                   "rate": r.rate, "uom": r.uom, "conversion_factor": r.conversion_factor or 1,
                   "cost_center": CC} for r in s.items],
    })
    return d, None


def make_pi(src_name):
    s = frappe.get_doc("Sales Invoice", src_name)      # VAC sells -> KP buys
    d = frappe.get_doc({
        "doctype": "Purchase Invoice", "company": KP, "supplier": VAC_PARTY,
        "posting_date": str(s.posting_date), "set_posting_time": 1,
        "due_date": str(s.posting_date), "currency": "INR", "conversion_rate": 1,
        "ignore_pricing_rule": 1, "update_stock": 0, "is_return": s.is_return,
        "return_against": mirror_name(s.return_against, "pi") if s.get("return_against") else None,
        "cost_center": CC, "credit_to": CREDITORS_KP,
        "bill_no": s.name, "bill_date": str(s.posting_date),
        "remarks": f"Mirror of VAC {s.name} (KP inter-company books)",
        "items": [{"item_code": r.item_code, "item_name": r.item_name, "qty": r.qty,
                   "rate": r.rate, "uom": r.uom, "conversion_factor": r.conversion_factor or 1,
                   "cost_center": CC} for r in s.items],
    })
    # VAC charged GST on this sale; KP (unregistered) has no ITC — the tax is
    # cost. One Actual charge row keeps the mirror's grand total == source's.
    tax = float(s.base_total_taxes_and_charges or 0)
    if abs(tax) > 0.005:
        d.append("taxes", {"charge_type": "Actual", "account_head": GST_COST_KP,
                           "description": f"GST on VAC bill {s.name} (unclaimable, folded to cost)",
                           "tax_amount": tax, "cost_center": CC})
    # Embedded payment on the source (POS-style SI: part cash at billing) — the
    # VAC party ledger only moves by the outstanding, so KP's mirror must show
    # the same cash-out or inter-co symmetry breaks (found: SI25-01213, ₹9,500).
    paid = float(s.paid_amount or 0)
    if abs(paid) > 0.005:
        if s.is_return:
            return None, f"source {s.name} is a return with embedded payment {paid} — map manually"
        d.is_paid = 1
        d.mode_of_payment = "Cash"
        d.cash_bank_account = CASH_KP
        d.paid_amount = paid
    return d, None


def make_je(src_name):
    s = frappe.get_doc("Journal Entry", src_name)
    rows, hold = translate_je(s)
    if hold:
        return None, hold
    d = frappe.get_doc({
        "doctype": "Journal Entry", "company": KP, "voucher_type": "Journal Entry",
        "posting_date": str(s.posting_date), "cheque_no": s.name,
        "cheque_date": str(s.posting_date),
        "user_remark": f"Mirror of VAC {s.name} (KP inter-company books)",
        "accounts": rows,
    })
    return d, None


def make_pe_je(pe):
    s = frappe.get_doc("Payment Entry", pe["name"])
    # Deductions (TDS / write-off / rounding) move the party ledger by more than
    # paid_amount, and their own GL leg is not mirrored here — so a source PE with
    # deductions would break inter-co symmetry. Atypical on KP goods trade: HOLD
    # it for manual mapping rather than post a silently-wrong mirror.
    ded = float(getattr(s, "total_deductions", 0) or 0)
    if abs(ded) > 0.005:
        return None, f"source {s.name} carries deductions {ded} (TDS/write-off) — mirror manually"
    amt = float(s.paid_amount)
    # VAC Pay->supplier KP: KP receives cash: Dr Cash, Cr VAC-customer (receivable down)
    # VAC Receive<-customer KP: KP pays cash: Cr Cash, Dr VAC-supplier (payable down)
    if s.payment_type == "Pay":
        rows = [{"account": CASH_KP, "debit_in_account_currency": amt, "cost_center": CC},
                {"account": DEBTORS_KP, "party_type": "Customer", "party": VAC_PARTY,
                 "credit_in_account_currency": amt, "cost_center": CC}]
    else:
        rows = [{"account": CASH_KP, "credit_in_account_currency": amt, "cost_center": CC},
                {"account": CREDITORS_KP, "party_type": "Supplier", "party": VAC_PARTY,
                 "debit_in_account_currency": amt, "cost_center": CC}]
    d = frappe.get_doc({
        "doctype": "Journal Entry", "company": KP, "voucher_type": "Journal Entry",
        "posting_date": str(s.posting_date),
        "user_remark": f"Mirror of VAC {s.name} ({s.payment_type} {amt}) (KP inter-company books)",
        "accounts": rows,
    })
    return d, None


def make_opening(amount):
    d = frappe.get_doc({
        "doctype": "Journal Entry", "company": KP, "voucher_type": "Opening Entry",
        "posting_date": "2024-04-01", "is_opening": "Yes",
        "user_remark": ("Opening 2024-04-01: VAC owes KP (mirror of VAC opening JE24-00007). "
                        "Capital/plant/stock openings pending accountant figures — "
                        "parked in Temporary Opening per plan §3.2."),
        "accounts": [
            {"account": DEBTORS_KP, "party_type": "Customer", "party": VAC_PARTY,
             "debit_in_account_currency": amount, "cost_center": CC},
            {"account": TEMP_OPEN_KP, "credit_in_account_currency": amount, "cost_center": CC},
        ],
    })
    return d


# ------------------------------------------------------------------- actions
def preview(src):
    from collections import defaultdict
    def fy(d):
        d = str(d); y, m = int(d[:4]), int(d[5:7])
        s = y if m >= 4 else y - 1
        return f"FY{s%100:02d}-{(s+1)%100:02d}"
    log("\n=== PREVIEW (no writes) ===")
    log(f"opening: VAC owes KP {src['opening_vac_owes_kp']:,.2f} at 2024-04-01")
    for kind, label in [("pi", "VAC PI -> KP SI"), ("si", "VAC SI -> KP PI")]:
        agg = defaultdict(lambda: [0, 0.0])
        for r in src[kind]:
            a = agg[fy(r["posting_date"])]; a[0] += 1; a[1] += r["grand_total"]
        for k in sorted(agg):
            log(f"  {label}  {k}: {agg[k][0]:>4} docs  net {agg[k][1]:>14,.2f}")
        exists = sum(1 for r in src[kind]
                     if frappe.db.exists("Sales Invoice" if kind == "pi" else "Purchase Invoice",
                                         mirror_name(r["name"], "si" if kind == "pi" else "pi")))
        log(f"  {label}  mirrors already present: {exists}/{len(src[kind])}")
    held = []
    ok = 0
    for r in src["je"]:
        s = frappe.get_doc("Journal Entry", r["name"])
        rows, hold = translate_je(s)
        if hold:
            held.append((r["name"], hold))
        else:
            ok += 1
    log(f"  JE mirrors: {ok} translate clean, {len(held)} HELD")
    for n, why in held[:20]:
        log(f"     HELD {n}: {why}")
    log(f"  PE mirrors: {len(src['pe'])}")
    log("=== END PREVIEW ===")
    return held


def go(src, limit=None, types=("opening", "si", "pi", "je", "pe")):
    frappe.flags.in_migrate = True
    stats = {"inserted": 0, "skipped": 0, "failed": 0}
    failures = []

    def push(doc, name, expect_total=None):
        if frappe.db.exists(doc.doctype, name):
            stats["skipped"] += 1
            return
        try:
            doc.insert(set_name=name, ignore_permissions=True)
            if expect_total is not None and abs(float(doc.grand_total) - float(expect_total)) > 0.02:
                raise ValueError(f"total drift: mirror {doc.grand_total} vs source {expect_total}")
            doc.submit()
            frappe.db.commit()
            stats["inserted"] += 1
            log(f"OK   {doc.doctype} {name}")
        except Exception as e:
            frappe.db.rollback()
            stats["failed"] += 1
            failures.append((name, str(e)[:300]))
            log(f"FAIL {doc.doctype} {name}: {e}")

    n = 0
    if "opening" in types and src["opening_vac_owes_kp"] > 0.005:
        if frappe.db.exists("Journal Entry", "KPJE-OPENING-2024"):
            stats["skipped"] += 1
        else:
            push(make_opening(src["opening_vac_owes_kp"]), "KPJE-OPENING-2024")
    # invoices in strict date order across both types (returns after their base
    # by the is_return sort inside each date)
    inv = []
    if "si" in types:
        inv += [("si", r) for r in src["pi"]]
    if "pi" in types:
        inv += [("pi", r) for r in src["si"]]
    inv.sort(key=lambda t: (str(t[1]["posting_date"]), t[1]["is_return"], t[1]["name"]))
    for kind, r in inv:
        if limit and n >= limit:
            break
        try:
            name = mirror_name(r["name"], kind)
        except ValueError as e:
            log(f"HELD {r['name']}: {e}")
            continue
        doc, hold = (make_si if kind == "si" else make_pi)(r["name"])
        if hold:
            log(f"HELD {r['name']}: {hold}")
            continue
        push(doc, name, expect_total=r["grand_total"])
        n += 1
    if "je" in types:
        for r in src["je"]:
            if limit and n >= limit:
                break
            try:
                name = mirror_name(r["name"], "je")
            except ValueError as e:
                log(f"HELD {r['name']}: {e}")
                continue
            doc, hold = make_je(r["name"])
            if hold:
                log(f"HELD {r['name']}: {hold}")
                continue
            push(doc, name)
            n += 1
    if "pe" in types:
        for r in src["pe"]:
            if limit and n >= limit:
                break
            doc, hold = make_pe_je(r)
            if hold:
                log(f"HELD {r['name']}: {hold}")
                continue
            push(doc, mirror_name(r["name"], "pe"))
            n += 1
    log(f"\nGO summary: {stats}")
    for name, err in failures[:30]:
        log(f"  FAILED {name}: {err}")
    return stats


def reconcile(src):
    log("\n=== RECONCILE ===")
    ok = True
    # 1) doc parity
    for kind, mdt in [("pi", "Sales Invoice"), ("si", "Purchase Invoice")]:
        want = len(src[kind])
        have = frappe.db.count(mdt, {"company": KP, "docstatus": 1,
                                     "remarks": ["like", "Mirror of VAC %"]})
        log(f"  parity {mdt:<17} source={want} mirrors={have} {'PASS' if want == have else 'CHECK'}")
    # 2) inter-co symmetry. The VAC side of the relationship spans FIVE ledgers:
    # the KP party itself PLUS the 4 pseudo expense heads (costs VAC paid for KP,
    # sitting as VAC's claim until netted). KP's mirror books carry all of it on
    # the single VAC party — so the identity is:
    #   [KP-party (cr-dr)] - [heads (dr-cr)]  ==  KP books' VAC-party (dr-cr)
    def net(party, company, sign):
        r = frappe.db.sql("""select sum(credit)-sum(debit) from `tabGL Entry`
            where company=%(c)s and party=%(p)s and is_cancelled=0""",
            {"c": company, "p": party})[0][0] or 0
        return float(r) * sign
    kp_party_net = net(KP_PARTY, VAC, +1)              # +ve = VAC owes KP
    heads_net = {h: net(h, VAC, -1) for h in HEADS}    # +ve = KP owes VAC (claim)
    vac_side = kp_party_net - sum(heads_net.values())
    kp_side = -net(VAC_PARTY, KP, +1)                  # dr-cr: +ve = VAC owes KP
    log(f"  VAC side: KP-party {kp_party_net:,.2f}"
        + "".join(f" | {h.split()[-2]} {v:,.2f}" for h, v in heads_net.items() if abs(v) > 0.005)
        + f" -> net VAC-owes-KP {vac_side:,.2f}")
    diff = round(vac_side - kp_side, 2)
    ok &= abs(diff) < 1
    log(f"  inter-co symmetry: VAC books net {vac_side:,.2f}; KP books say "
        f"{kp_side:,.2f}; diff {diff:,.2f} {'PASS' if abs(diff) < 1 else 'FAIL'}")
    # 3) KP GL balanced
    bal = frappe.db.sql("""select round(sum(debit)-sum(credit),2) from `tabGL Entry`
        where company=%(c)s and is_cancelled=0""", {"c": KP})[0][0] or 0
    ok &= float(bal) == 0
    log(f"  KP GL Dr-Cr = {bal} {'PASS' if float(bal) == 0 else 'FAIL'}")
    # 4) revenue sanity per FY
    rev = frappe.db.sql("""select sum(base_grand_total) from `tabSales Invoice`
        where company=%(c)s and docstatus=1""", {"c": KP})[0][0] or 0
    src_rev = sum(r["grand_total"] for r in src["pi"])
    log(f"  KP revenue total {float(rev):,.2f} vs source {src_rev:,.2f} "
        f"{'PASS' if abs(float(rev) - src_rev) < 1 else 'CHECK'}")
    log(f"=== RECONCILE {'PASS' if ok else 'HAS FAILURES'} ===")
    return ok


def wipe(names=None):
    """Delete KP-company vouchers (staging reset). names=None -> ALL of them;
    otherwise only the listed mirror names. Safe by construction: the site
    guard already refused non-staging sites, and only KP-company documents are
    touched — VAC's books are never in scope."""
    n, failed = 0, 0
    for dt in ["Sales Invoice", "Purchase Invoice", "Journal Entry"]:
        flt = {"company": KP}
        if names:
            flt["name"] = ["in", names]
        for name in [r.name for r in frappe.get_all(
                dt, filters=flt, order_by="posting_date desc, name desc")]:
            # per-doc guard: one cancel/delete failure (e.g. a period lock) must not
            # abort the whole wipe and strand the KP company half-deleted.
            try:
                doc = frappe.get_doc(dt, name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc(dt, name, force=1, ignore_permissions=True)
                frappe.db.commit()
                n += 1
                log(f"wiped {dt} {name}")
            except Exception as e:
                frappe.db.rollback()
                failed += 1
                log(f"WIPE FAIL {dt} {name}: {e}")
    log(f"wipe done: {n} docs removed, {failed} failed")


def gap(src):
    """Find VAC-side vouchers on the 5 KP-relationship ledgers with NO KP mirror."""
    mirrored = {r["name"] for k in ("pi", "si", "je", "pe") for r in src[k]}
    rows = frappe.db.sql("""select voucher_type, voucher_no, party,
            sum(debit) dr, sum(credit) cr from `tabGL Entry`
            where company=%(c)s and party in %(p)s and is_cancelled=0
              and is_opening='No'
            group by voucher_type, voucher_no, party""",
        {"c": VAC, "p": ALL_PARTIES}, as_dict=True)
    log("\n=== UNMIRRORED VOUCHERS on the 5 ledgers ===")
    tot = 0.0
    for r in rows:
        if r.voucher_no in mirrored:
            continue
        net = float(r.dr) - float(r.cr)
        tot += net
        log(f"  {r.voucher_type:<16} {r.voucher_no:<16} {r.party:<30} dr-cr={net:>12,.2f}")
    log(f"  TOTAL unmirrored net (dr-cr) = {tot:,.2f}")
    log("=== END GAP ===")


def gap2(src):
    """Per-voucher symmetry: VAC-side net (5 ledgers) vs KP-side net (VAC party)."""
    def vac_net(v):
        r = frappe.db.sql("""select sum(credit)-sum(debit) from `tabGL Entry`
            where company=%(c)s and voucher_no=%(v)s and party in %(p)s
              and is_cancelled=0""", {"c": VAC, "v": v, "p": ALL_PARTIES})[0][0]
        return float(r or 0)
    def kp_net(v):
        r = frappe.db.sql("""select sum(debit)-sum(credit) from `tabGL Entry`
            where company=%(c)s and voucher_no=%(v)s and party=%(p)s
              and is_cancelled=0""", {"c": KP, "v": v, "p": VAC_PARTY})[0][0]
        return float(r or 0)
    log("\n=== PER-VOUCHER SYMMETRY MISMATCHES ===")
    tot = 0.0
    pairs = ([(r["name"], mirror_name(r["name"], "si")) for r in src["pi"]]
             + [(r["name"], mirror_name(r["name"], "pi")) for r in src["si"]]
             + [(r["name"], mirror_name(r["name"], "je")) for r in src["je"]]
             + [(r["name"], mirror_name(r["name"], "pe")) for r in src["pe"]])
    for s, m in pairs:
        d = round(vac_net(s) - kp_net(m), 2)
        if abs(d) > 0.01:
            tot += d
            log(f"  {s:<16} -> {m:<18} vac={vac_net(s):>12,.2f} kp={kp_net(m):>12,.2f} diff={d:>10,.2f}")
    log(f"  TOTAL per-voucher diff = {tot:,.2f}")
    log("=== END ===")


def dump_held(src):
    log("\n=== HELD JE DETAIL ===")
    for r in src["je"]:
        s = frappe.get_doc("Journal Entry", r["name"])
        _, hold = translate_je(s)
        if not hold:
            continue
        log(f"\n{ s.name }  {s.posting_date}  [{hold}]")
        log(f"  title={s.get('title')!r} remark={ (s.user_remark or '')[:120]!r} sysgen={s.is_system_generated}")
        for a in s.accounts:
            log(f"   {a.account:<44} party={a.party_type or '':<9}{a.party or '':<30} "
                f"dr={a.debit:>12,.2f} cr={a.credit:>12,.2f}")
    log("=== END HELD ===")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("action", choices=["preview", "prereqs", "go", "reconcile", "held", "wipe", "gap", "gap2"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--types", default="opening,si,pi,je,pe")
    ap.add_argument("--names")
    args = ap.parse_args()

    # ---- HARD STAGING GUARD ----
    # Explicit exit, NOT assert: `python -O` / PYTHONOPTIMIZE strips assert
    # statements, which would remove the ONLY thing keeping this write-capable
    # script off production.
    if "staging" not in args.site:
        sys.exit(
            "REFUSED: this script only runs against a staging site. The production "
            "run is a separate user-gated step per docs/kp_intercompany_plan.md §4.")

    frappe.init(site=args.site)
    frappe.connect()
    frappe.set_user("Administrator")
    log(f"\n##### kp_mirror {args.action} on {args.site} #####")
    try:
        if args.action == "prereqs":
            for a in ensure_prereqs():
                log("  " + a)
            return
        if args.action == "wipe":
            wipe(names=args.names.split(",") if args.names else None)
            return
        src = extract()
        if args.action == "preview":
            preview(src)
        elif args.action == "held":
            dump_held(src)
        elif args.action == "gap":
            gap(src)
        elif args.action == "gap2":
            gap2(src)
        elif args.action == "go":
            go(src, limit=args.limit, types=tuple(args.types.split(",")))
        elif args.action == "reconcile":
            reconcile(src)
    except Exception:
        log(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
