"""POS item grid ordered by billing popularity instead of A-Z.

Pinned copy of ``erpnext.selling.page.point_of_sale.point_of_sale.get_items``
from ERPNext v16.25.0 with ONE functional change: the item query LEFT JOINs a
12-month billing-frequency aggregate (submitted Sales Invoice lines) and
orders by it — most-billed items first, name as tie-break. Search behaviour,
group filtering, pricing and stock enrichment are byte-identical to core.

Wired via ``override_whitelisted_methods`` in hooks.py.
⚠ Re-diff against core get_items on every ERPNext upgrade.
"""

import frappe
from frappe.query_builder import DocType, Order
from frappe.utils import cint, flt
from frappe.utils.nestedset import get_root_of

from erpnext.accounts.doctype.pos_invoice.pos_invoice import get_stock_availability
from erpnext.selling.page.point_of_sale.point_of_sale import (
    filter_result_items,
    get_conditions,
    get_item_group_condition,
    search_by_term,
)
from erpnext.stock.get_item_details import get_conversion_factor

POPULARITY_JOIN = """
        LEFT JOIN (
            SELECT sii.item_code AS item_code, COUNT(*) AS bill_count
            FROM `tabSales Invoice Item` sii
            INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE si.docstatus = 1
              AND si.company = %(company)s
              AND si.posting_date >= DATE_SUB(CURDATE(), INTERVAL 365 DAY)
            GROUP BY sii.item_code
        ) pop ON pop.item_code = item.name
"""


@frappe.whitelist()
def get_items(start, page_length, price_list, item_group, pos_profile, search_term=""):
    warehouse, hide_unavailable_items, company = frappe.db.get_value(
        "POS Profile", pos_profile, ["warehouse", "hide_unavailable_items", "company"]
    )

    result = []

    if search_term:
        result = search_by_term(search_term, warehouse, price_list) or []
        filter_result_items(result, pos_profile)
        if result:
            return result

    if not frappe.db.exists("Item Group", item_group):
        item_group = get_root_of("Item Group")

    condition = get_conditions(search_term)
    condition += get_item_group_condition(pos_profile)

    lft, rgt = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"])

    bin_join_selection, bin_join_condition = "", ""
    if hide_unavailable_items:
        bin_join_selection = "LEFT JOIN `tabBin` bin ON bin.item_code = item.name"
        bin_join_condition = (
            "AND (item.is_stock_item = 0 OR (item.is_stock_item = 1 "
            "AND bin.warehouse = %(warehouse)s AND bin.actual_qty > 0))"
        )

    items_data = frappe.db.sql(
        """
        SELECT
            item.name AS item_code,
            item.item_name,
            item.description,
            item.stock_uom,
            item.image AS item_image,
            item.is_stock_item,
            item.sales_uom
        FROM
            `tabItem` item {bin_join_selection}
        {popularity_join}
        WHERE
            item.disabled = 0
            AND item.has_variants = 0
            AND item.is_sales_item = 1
            AND item.is_fixed_asset = 0
            AND item.item_group in (SELECT name FROM `tabItem Group` WHERE lft >= {lft} AND rgt <= {rgt})
            AND {condition}
            {bin_join_condition}
        ORDER BY
            COALESCE(pop.bill_count, 0) DESC,
            item.name asc
        LIMIT
            {page_length} offset {start}""".format(
            start=cint(start),
            page_length=cint(page_length),
            lft=cint(lft),
            rgt=cint(rgt),
            condition=condition,
            bin_join_selection=bin_join_selection,
            bin_join_condition=bin_join_condition,
            popularity_join=POPULARITY_JOIN,
        ),
        {"warehouse": warehouse, "company": company},
        as_dict=1,
    )

    # return (empty) list if there are no results
    if not items_data:
        return result

    current_date = frappe.utils.today()

    for item in items_data:
        item.actual_qty, _, is_negative_stock_allowed = get_stock_availability(item.item_code, warehouse)

        ItemPrice = DocType("Item Price")
        item_prices = (
            frappe.qb.from_(ItemPrice)
            .select(
                ItemPrice.price_list_rate,
                ItemPrice.currency,
                ItemPrice.uom,
                ItemPrice.batch_no,
                ItemPrice.valid_from,
                ItemPrice.valid_upto,
            )
            .where(ItemPrice.price_list == price_list)
            .where(ItemPrice.item_code == item.item_code)
            .where(ItemPrice.selling == 1)
            .where((ItemPrice.valid_from <= current_date) | (ItemPrice.valid_from.isnull()))
            .where((ItemPrice.valid_upto >= current_date) | (ItemPrice.valid_upto.isnull()))
            .orderby(ItemPrice.valid_from, order=Order.desc)
        ).run(as_dict=True)

        stock_uom_price = next((d for d in item_prices if d.get("uom") == item.stock_uom), {})
        item_uom = item.stock_uom
        item_uom_price = stock_uom_price

        if item.sales_uom and item.sales_uom != item.stock_uom:
            item_uom = item.sales_uom
            sales_uom_price = next((d for d in item_prices if d.get("uom") == item.sales_uom), {})
            if sales_uom_price:
                item_uom_price = sales_uom_price

        if item_prices and not item_uom_price:
            item_uom = item_prices[0].get("uom")
            item_uom_price = item_prices[0]

        item_conversion_factor = get_conversion_factor(item.item_code, item_uom).get("conversion_factor")

        if item.stock_uom != item_uom:
            item.actual_qty = item.actual_qty // item_conversion_factor

        if item_uom_price and item_uom != item_uom_price.get("uom"):
            item_uom_price.price_list_rate = item_uom_price.price_list_rate * item_conversion_factor

        result.append(
            {
                **item,
                "price_list_rate": item_uom_price.get("price_list_rate"),
                "currency": item_uom_price.get("currency"),
                "uom": item_uom,
                "batch_no": item_uom_price.get("batch_no"),
            }
        )

    return {"items": result}


def block_zero_rate_pos(doc, method=None):
    """Safeguard for the "cashier types the price at the register" POS change
    (public/js/vac_pos.bundle.js): never let a POS sale be completed with a
    zero-rate line. The JS lets an unpriced item into the cart at rate 0 so the
    cashier can type the price on the spot; this catches the case where they
    forgot. Scoped to POS invoices (is_pos) — regular Sales Invoices, which may
    legitimately carry a zero-rate line (a free sample, a 100%-discount item),
    are untouched. Wired via before_submit on Sales Invoice in hooks.py."""
    if not getattr(doc, "is_pos", 0):
        return
    # Only the "forgot to price it" case: qty>0, net rate 0, AND no list price.
    # An intentional 100%-discount on a PRICED item keeps price_list_rate>0, so
    # it is allowed through.
    zero = [
        d.item_code
        for d in (doc.items or [])
        if flt(d.qty) and flt(d.rate) <= 0 and flt(d.price_list_rate) <= 0
    ]
    if zero:
        frappe.throw(
            frappe._("Set a price for these items before completing the sale: {0}").format(
                ", ".join(frappe.bold(x) for x in zero)
            ),
            title=frappe._("Price not set"),
        )

