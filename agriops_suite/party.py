# Party-integration tools for dual-role parties (customer AND supplier).
#
# Vijay Agro Centre trades both ways with many agro-dealer peers. ERPNext
# models that as two masters joined by a Party Link, which Common Party
# Accounting (ENABLED on production) consumes at invoice submit to move the
# receivable onto the payable ledger. These helpers only FEED or PROTECT that
# mechanism — they never hook invoice submission or touch GL/JE posting.
#
# make_counterparty / sync_party_masters are gated per-site by the
# `vac_party_tools_enabled` site-config flag (same staging-first contract as
# vac_theme). validate_party_link is ungated: it only rejects NEW duplicate
# links, which is safe everywhere.

import frappe
from frappe import _

CUSTOMER_GROUP_DEFAULT = "Customer Wholesale"
SUPPLIER_GROUP_DEFAULT = "Other Creditors"

# flat master fields mirrored across a linked pair (Address/Contact docs are
# SHARED via Dynamic Links at creation time, so they never need syncing)
SYNC_FIELDS = ("gstin", "gst_category", "tax_id", "pan")


def tools_enabled():
    return bool(frappe.conf.get("vac_party_tools_enabled"))


def find_link(role, party):
    """Return the Party Link this (role, party) participates in, else None.

    Role-aware on purpose: a Customer and a Supplier sharing one name are
    different parties, and core's name-only checks confuse the two.
    """
    for role_field, party_field in (
        ("primary_role", "primary_party"),
        ("secondary_role", "secondary_party"),
    ):
        rows = frappe.get_all(
            "Party Link",
            filters={role_field: role, party_field: party},
            fields=["name", "primary_role", "primary_party", "secondary_role", "secondary_party"],
            limit=1,
        )
        if rows:
            return rows[0]
    return None


def link_counterpart(link, role, party):
    """Given a link row and one side, return (other_role, other_party)."""
    if link.primary_role == role and link.primary_party == party:
        return link.secondary_role, link.secondary_party
    return link.primary_role, link.primary_party


@frappe.whitelist()
def make_counterparty(role, name):
    """Create (or adopt) the opposite-role master for a party and link them.

    Called from the Customer/Supplier form button. Creates the counterpart
    only when no same-name record exists; shares the source's Address and
    Contact docs with a freshly created counterpart; always finishes by
    creating the Party Link (primary = the side the user clicked from).
    """
    if not tools_enabled():
        frappe.throw(_("Party tools are not enabled on this site (vac_party_tools_enabled)."))
    if role not in ("Customer", "Supplier"):
        frappe.throw(_("Role must be Customer or Supplier."))
    other_role = "Supplier" if role == "Customer" else "Customer"
    if not frappe.has_permission(other_role, "create"):
        frappe.throw(_("Not permitted to create {0}").format(_(other_role)), frappe.PermissionError)
    # also require READ on the SOURCE party: get_doc does not enforce it, and the
    # counterpart copies gstin/pan/tax_id, so without this a create-on-one-role
    # user could exfiltrate a party they cannot otherwise read.
    if not frappe.has_permission(role, "read", doc=name):
        frappe.throw(_("Not permitted to read {0} {1}").format(_(role), name), frappe.PermissionError)

    src = frappe.get_doc(role, name)

    existing = find_link(role, name)
    if existing:
        o_role, o_party = link_counterpart(existing, role, name)
        frappe.throw(
            _("{0} {1} is already linked to {2} {3} ({4}).").format(
                _(role), frappe.bold(name), _(o_role), frappe.bold(o_party), existing.name
            ),
            title=_("Already linked"),
        )

    created = False
    if frappe.db.exists(other_role, name):
        counterpart = name
    else:
        doc = build_counterpart(src, other_role)
        doc.insert()
        counterpart = doc.name
        created = True
        share_addresses_and_contacts(role, name, other_role, counterpart)

    from erpnext.accounts.doctype.party_link.party_link import create_party_link

    link = create_party_link(role, name, counterpart)
    return {"counterpart": counterpart, "created": created, "party_link": link.name}


def build_counterpart(src, other_role):
    doc = frappe.new_doc(other_role)
    party_name = src.get("customer_name") or src.get("supplier_name") or src.name
    src_type = src.get("customer_type") or src.get("supplier_type")

    if other_role == "Supplier":
        doc.supplier_name = party_name
        doc.supplier_group = SUPPLIER_GROUP_DEFAULT
        doc.supplier_type = map_party_type(doc, "supplier_type", src_type)
    else:
        doc.customer_name = party_name
        doc.customer_group = CUSTOMER_GROUP_DEFAULT
        doc.customer_type = map_party_type(doc, "customer_type", src_type)

    if doc.meta.has_field("country"):
        doc.country = src.get("country") or "India"
    for field in SYNC_FIELDS:
        if src.get(field) and doc.meta.has_field(field):
            doc.set(field, src.get(field))
    return doc


def map_party_type(doc, fieldname, value):
    # Customer and Supplier type Selects have different option sets
    options = [o.strip() for o in (doc.meta.get_field(fieldname).options or "").split("\n") if o.strip()]
    return value if value in options else "Individual"


def share_addresses_and_contacts(src_role, src_name, other_role, other_name):
    """Point the source party's Address/Contact docs at the counterpart too
    (one shared doc, two Dynamic Links — the standard ERPNext pattern)."""
    for doctype in ("Address", "Contact"):
        parents = frappe.get_all(
            "Dynamic Link",
            filters={"parenttype": doctype, "link_doctype": src_role, "link_name": src_name},
            pluck="parent",
        )
        for parent in set(parents):
            doc = frappe.get_doc(doctype, parent)
            if any(l.link_doctype == other_role and l.link_name == other_name for l in doc.links):
                continue
            doc.append("links", {"link_doctype": other_role, "link_name": other_name})
            doc.save()


def sync_party_masters(doc, method=None):
    """doc_events on_update for Customer/Supplier: mirror flat master fields
    across a linked pair. Writes with frappe.db.set_value (fires no
    doc_events → no recursion) and only when a value actually differs."""
    if not tools_enabled():
        return
    flags = frappe.flags
    if flags.in_import or flags.in_migrate or flags.in_install or flags.in_patch or flags.in_fixtures:
        return
    if doc.doctype not in ("Customer", "Supplier"):
        return

    link = find_link(doc.doctype, doc.name)
    if not link:
        return
    other_role, other_name = link_counterpart(link, doc.doctype, doc.name)
    if not frappe.db.exists(other_role, other_name):
        return

    other_meta = frappe.get_meta(other_role)
    updates = {}
    for field in SYNC_FIELDS:
        if not doc.meta.has_field(field) or not other_meta.has_field(field):
            continue
        current = frappe.db.get_value(other_role, other_name, field)
        if (doc.get(field) or "") != (current or ""):
            updates[field] = doc.get(field)
    if updates:
        frappe.db.set_value(other_role, other_name, updates)
        frappe.clear_document_cache(other_role, other_name)


def validate_party_link(doc, method=None):
    """doc_events validate for Party Link: one link per (role, party).

    Core validate misses a party appearing as PRIMARY in two links (erpnext
    #35184) — a duplicate can route the common-party transfer JE to the wrong
    ledger. Role-aware so same-name Customer/Supplier records stay distinct.
    """
    for role, party in (
        (doc.primary_role, doc.primary_party),
        (doc.secondary_role, doc.secondary_party),
    ):
        if not (role and party):
            continue
        for role_field, party_field in (
            ("primary_role", "primary_party"),
            ("secondary_role", "secondary_party"),
        ):
            existing = frappe.get_all(
                "Party Link",
                filters={role_field: role, party_field: party, "name": ["!=", doc.name or ""]},
                limit=1,
            )
            if existing:
                frappe.throw(
                    _(
                        "{0} {1} already has a Party Link ({2}). Only one link per party is "
                        "allowed — a second link can misroute the common-party transfer entry."
                    ).format(_(role), frappe.bold(party), existing[0].name),
                    title=_("Duplicate Party Link"),
                )
