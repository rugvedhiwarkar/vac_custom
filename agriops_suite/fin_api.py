"""Financial Cockpit (/fin) — read-only statement & register API.

Phase 1: bootstrap + snapshot (day-wise bucket / P&L-leaf movements).
Phase 2: the rest of the books —

- tree:           chart of accounts with openings (drives group drill-down)
- group_summary:  member-account values inside any group, as-of or over a range
- ledger:         account / party register, paged or summarised, filterable
- outstanding:    party-wise receivable/payable with ageing + open vouchers
- stock_balance:  item-wise opening/in/out/closing for a range
- item_ledger:    stock movements for one item
- acct:           the accountant's-note block (depreciation schedule, drawings,
                  adjusted profits, corrected cash flow, capital events)
- manifest / sw:  PWA wrapper (same pattern as /slip)

Everything is read-only by construction: SELECTs only, role-guarded, and no
client string ever reaches SQL unparameterised — names are validated against
the Account/Item tables first, and subtree filters are lft/rgt ranges the
server resolves itself. Heavier payloads cache a few minutes keyed on the
ledger's modification stamp (shared bench — noisy neighbours).

Period Closing Voucher rows are excluded from P&L figures (mirroring the
standard statements) but kept on the equity side, where the closing lands.
"""

import json

import frappe
from frappe.utils import getdate

# Owner-only: the cockpit is the whole books laid bare, so access is a
# user allowlist in code — roles deliberately do NOT grant it (any System
# Manager could hand out a role; changing this list takes a git deploy).
# claude-agent is the automation identity — it already reads the ledger
# through the standard API, so listing it grants nothing new; drop the
# line to lock tooling out too.
ALLOWED_USERS = (
	"administrator",
	"hiwarkarvijay@gmail.com",  # Vijay Hiwarkar (director)
	"claude-agent@vijayagrocentre.frappe.cloud",  # automation / verification
)
COMPANY = "Vijay Agro Centre"
PCV = "Period Closing Voucher"
CACHE_SECONDS = 600
SCOPE = "/fin"

# bucket -> (root account names without company abbr, sign)
BUCKETS = {
	"inc": (["Income"], -1),
	"dexp": (["Direct Expenses"], 1),
	"iexp": (["Indirect Expenses"], 1),
	"ar": (["Accounts Receivable"], 1),
	"stock": (["Stock Assets"], 1),
	"cash": (["Bank Accounts", "Cash In Hand", "Cash-in-hand"], 1),
	"depo": (["Securities & Deposits (Asset)"], 1),
	"tax": (["Tax Assets"], 1),
	"fixed": (["Fixed Assets"], 1),
	"susp": (["Suspense Account", "Temporary Accounts"], 1),
	"ap": (["Accounts Payable"], -1),
	"duty": (["Duties and Taxes"], -1),
	"sliab": (["Stock Liabilities"], -1),
	"eq": (["Equity"], -1),
}
PL_BUCKETS = ("inc", "dexp", "iexp")

# ---- hand-maintained accountant narrative (update alongside the books) ----
COGS_GAP_CURRENT_FY = 224000  # unbooked COGS from the stock-update gap, FY26-27
PROFIT_HISTORY_CARRIED = [
	{"fy": "pre-2022", "profit": 3703697, "src": "carried into capital (opening JE)"},
	{"fy": "FY22-23", "profit": 1400212, "src": "carried into capital (opening JE)"},
	{"fy": "FY23-24", "profit": 589095, "src": "carried into capital (opening JE)"},
]
REVIEW_ITEMS = [
	{"item": "Cash Overage income Rs 2,15,763", "sev": "warn",
		"detail": "Two JEs dated 15-7-2026 (JE26-00740 Rs 43,196 + JE26-00743 Rs 1,72,567) booked as income. If this is accumulated unbilled cash sales there is a GST angle - show both JEs to the filing firm."},
	{"item": "Unaccounted Cash suspense -Rs 76,991 inside FY26-27 COGS", "sev": "warn",
		"detail": "A credit sitting in Stock Expenses reduces cost of goods sold. Identify source voucher and reclass."},
	{"item": "BS suspense -Rs 1,17,533 + temporary opening -Rs 47,216", "sev": "info",
		"detail": "Static since Mar-26. Old sale/purchase adjustment and migration remainder - clear with one JE each once traced."},
	{"item": "Receivables are harvest-cycle old", "sev": "warn",
		"detail": "Nearly all gross AR is >120 days old, partly offset by recent credits/advances. Normal for village credit, but worth a recovery push before Kharif spending peaks."},
	{"item": "FY24-25 monthly shape is migration-lumpy", "sev": "info",
		"detail": "Vouchers were period-lumped in migration. Trust FY24-25 totals, not its months."},
]
PROPOSED_ACTIONS = [
	{"action": "Book the current-year depreciation provision",
		"detail": "JE: Dr Depreciation / Cr Accumulated Depreciation - Equipment, per the schedule below. Prior years are in closed periods - disclose, do not reopen."},
	{"action": "Reclass Home expenses to drawings",
		"detail": "JE: Dr Capital (Drawings) / Cr Home Expense + Home for the current year, and repoint those accounts to equity so future entries never hit P&L."},
	{"action": "Close the COGS gap",
		"detail": "Fix non-POS Sales Invoice defaults (update_stock + warehouse) and backfill the affected invoices (~Rs 2.24L COGS). Already scoped."},
	{"action": "Clear suspense balances",
		"detail": "Trace and zero: Sale/Purchase ADJ, Temporary Opening, Unaccounted Cash."},
	{"action": "Line up the FY23-24 backfill",
		"detail": "One bridge run from BusyWin company 0001 unlocks full 4-year statements everywhere here."},
]


def _guard():
	if (frappe.session.user or "").lower() not in ALLOWED_USERS:
		frappe.throw("The Financial Cockpit is restricted.", frappe.PermissionError)


def _abbr():
	return frappe.get_cached_value("Company", COMPANY, "abbr")


def _full(name):
	return f"{name} - {_abbr()}"


def _ranges():
	abbr = _abbr()
	wanted = [f"{root} - {abbr}" for roots, _ in BUCKETS.values() for root in roots]
	rows = frappe.get_all(
		"Account",
		filters={"name": ("in", wanted), "company": COMPANY},
		fields=["name", "lft", "rgt"],
	)
	by_name = {r.name: r for r in rows}
	out = {}
	for bucket, (roots, sign) in BUCKETS.items():
		rr = []
		for root in roots:
			acc = by_name.get(f"{root} - {abbr}")
			if acc:
				rr.append((acc.lft, acc.rgt))
		out[bucket] = (rr, sign)
	return out


def _gl_stamp():
	row = frappe.db.sql(
		"select count(*), max(modified) from `tabGL Entry` where company = %s",
		(COMPANY,),
	)[0]
	return f"{row[0]}:{row[1]}"


def _cached(key_parts, builder, seconds=CACHE_SECONDS):
	key = "agriops_fin:" + ":".join(str(p) for p in key_parts) + ":" + _gl_stamp()
	cached = frappe.cache().get_value(key)
	if cached:
		out = json.loads(cached)
		out["from_cache"] = True
		return out
	out = builder()
	out["from_cache"] = False
	frappe.cache().set_value(key, json.dumps(out, default=str), expires_in_sec=seconds)
	return out


def _account_row(name_or_stripped):
	"""Resolve an account by full or abbr-stripped name; None if absent."""
	for candidate in (name_or_stripped, _full(name_or_stripped)):
		row = frappe.db.get_value(
			"Account", {"name": candidate, "company": COMPANY},
			["name", "lft", "rgt", "is_group", "root_type"], as_dict=True,
		)
		if row:
			return row
	return None


def _fy_start_for(date_obj):
	y = date_obj.year if date_obj.month >= 4 else date_obj.year - 1
	return getdate(f"{y}-04-01")


# ================= Phase 1 =================

@frappe.whitelist(methods=["GET"])
def bootstrap():
	_guard()
	span = frappe.db.sql(
		"""select min(posting_date), max(posting_date)
		from `tabGL Entry` where company = %s and is_cancelled = 0""",
		(COMPANY,),
	)[0]
	return {
		"company": COMPANY,
		"d0": str(span[0]),
		"asof": str(span[1]),
		"today": frappe.utils.today(),
		"buckets": list(BUCKETS),
		"fiscal_years": [
			fy.name
			for fy in frappe.get_all(
				"Fiscal Year", fields=["name"], order_by="year_start_date"
			)
		],
	}


def _build_daily():
	"""Core of snapshot(): (d0, asof, nd, daily, leaf, audit) from the GL."""
	ranges = _ranges()
	col_sql, params = [], []
	for bucket, (rr, sign) in ranges.items():
		if not rr:
			col_sql.append(f"0 as `{bucket}`")
			continue
		cond = "(" + " or ".join(["a.lft between %s and %s"] * len(rr)) + ")"
		pcv_guard = ""
		if bucket in PL_BUCKETS:
			pcv_guard = "gl.voucher_type != %s and "
			params.append(PCV)
		col_sql.append(
			f"round(sum(case when {pcv_guard}{cond} "
			f"then ({sign}) * (gl.debit - gl.credit) else 0 end)) as `{bucket}`"
		)
		for lft, rgt in rr:
			params.extend([lft, rgt])

	day_rows = frappe.db.sql(
		f"""select gl.posting_date as d, {", ".join(col_sql)}
		from `tabGL Entry` gl
		join `tabAccount` a on a.name = gl.account
		where gl.company = %s and gl.is_cancelled = 0
		group by gl.posting_date
		order by gl.posting_date""",
		params + [COMPANY],
		as_dict=True,
	)
	if not day_rows:
		frappe.throw(f"No GL entries found for {COMPANY}")

	d0, asof = day_rows[0].d, day_rows[-1].d
	nd = (asof - d0).days + 1
	daily = {b: {} for b in BUCKETS}
	for row in day_rows:
		idx = str((row.d - d0).days)
		for b in BUCKETS:
			v = int(row[b] or 0)
			if v:
				daily[b][idx] = v

	pl_rr = [r for b in PL_BUCKETS for r in ranges[b][0]]
	cond = "(" + " or ".join(["a.lft between %s and %s"] * len(pl_rr)) + ")"
	lp = []
	for lft, rgt in pl_rr:
		lp.extend([lft, rgt])
	leaf_rows = frappe.db.sql(
		f"""select gl.posting_date as d, gl.account as acct, a.root_type as rt,
			round(sum(gl.debit - gl.credit)) as net
		from `tabGL Entry` gl
		join `tabAccount` a on a.name = gl.account
		where gl.company = %s and gl.is_cancelled = 0
			and gl.voucher_type != %s and {cond}
		group by gl.posting_date, gl.account""",
		[COMPANY, PCV] + lp,
		as_dict=True,
	)
	leaf = {}
	for row in leaf_rows:
		v = int(row.net or 0)
		if row.rt == "Income":
			v = -v
		if v:
			leaf.setdefault(row.acct, {})[str((row.d - d0).days)] = v

	tot = frappe.db.sql(
		"""select round(sum(debit), 2), round(sum(credit), 2)
		from `tabGL Entry` where company = %s and is_cancelled = 0""",
		(COMPANY,),
	)[0]
	dr, cr = float(tot[0] or 0), float(tot[1] or 0)
	audit = {"dr": dr, "cr": cr, "balanced": abs(dr - cr) < 1}
	return d0, asof, nd, daily, leaf, audit


@frappe.whitelist(methods=["GET"])
def snapshot():
	_guard()

	def build():
		d0, asof, nd, daily, leaf, audit = _build_daily()
		return {
			"company": COMPANY,
			"d0": str(d0), "asof": str(asof), "nd": nd,
			"daily": daily, "leaf": leaf, "audit": audit,
			"generated": frappe.utils.now(),
		}

	return _cached(["snapshot", COMPANY], build)


# ================= Phase 2: chart of accounts & group drill =================

@frappe.whitelist(methods=["GET"])
def tree():
	"""All accounts (stripped names, parent links) + BS-leaf openings at the
	current fiscal-year start. P&L leaves open at zero (years are PCV-closed)."""
	_guard()

	def build():
		abbr = f" - {_abbr()}"
		accounts = frappe.get_all(
			"Account",
			filters={"company": COMPANY},
			fields=["name", "parent_account", "lft", "is_group", "root_type"],
			order_by="lft",
		)
		fy0 = _fy_start_for(getdate(frappe.utils.today()))
		opening_rows = frappe.db.sql(
			"""select gl.account, round(sum(gl.debit - gl.credit)) as bal
			from `tabGL Entry` gl join `tabAccount` a on a.name = gl.account
			where gl.company = %s and gl.is_cancelled = 0
				and gl.posting_date < %s
				and a.root_type in ('Asset', 'Liability', 'Equity')
			group by gl.account""",
			(COMPANY, str(fy0)),
		)
		opening = {r[0]: int(r[1] or 0) for r in opening_rows}
		idx = {a.name: i for i, a in enumerate(accounts)}
		out_rows = []
		for a in accounts:
			out_rows.append([
				a.name.replace(abbr, ""),
				idx.get(a.parent_account, -1),
				1 if a.is_group else 0,
				a.root_type or "",
				0 if a.is_group else opening.get(a.name, 0),
			])
		return {"tree": out_rows, "opening_asof": str(fy0)}

	return _cached(["tree", COMPANY], build, seconds=3600)


@frappe.whitelist(methods=["GET"])
def group_summary(roots, mode="bal", as_of=None, from_date=None, to_date=None,
		cmp_as_of=None, cmp_from=None, cmp_to=None):
	"""Values for the direct children of the given group account(s).

	mode 'bal': balance to as_of (raw debit-nature sign; client flips L/E).
	mode 'flow': P&L total over from_date..to_date, signed by root type,
	PCV excluded. Compare columns via the cmp_* twins.
	"""
	_guard()
	root_names = frappe.parse_json(roots) if isinstance(roots, str) else roots
	parents = []
	for rn in root_names[:6]:
		row = _account_row(rn)
		if row:
			parents.append(row)
	if not parents:
		frappe.throw("Unknown group account")

	kids = []
	for p in parents:
		if not p.is_group:
			kids.append(p)
	child_rows = frappe.get_all(
		"Account",
		filters={"parent_account": ("in", [p.name for p in parents if p.is_group]),
			"company": COMPANY},
		fields=["name", "lft", "rgt", "is_group", "root_type"],
		order_by="lft",
	)
	kids.extend(child_rows)
	if not kids:
		return {"rows": [], "mode": mode}
	# bound the account join by the widest parent range (keeps the scan small)
	lo = min(p.lft for p in parents)
	hi = max(p.rgt for p in parents)

	def value_cols(date_a=None, date_b=None, at=None):
		cols, params = [], []
		for i, c in enumerate(kids):
			sign = -1 if (mode == "flow" and c.root_type == "Income") else 1
			pcv_guard = ""
			if mode == "flow":
				pcv_guard = "gl.voucher_type != %s and "
				params.append(PCV)
			cols.append(
				f"round(sum(case when {pcv_guard}a.lft between %s and %s "
				f"then ({sign}) * (gl.debit - gl.credit) else 0 end)) as `v{i}`"
			)
			params.extend([c.lft, c.rgt])
		where = "gl.company = %s and gl.is_cancelled = 0"
		wparams = [COMPANY]
		if mode == "bal":
			where += " and gl.posting_date <= %s"
			wparams.append(str(getdate(at)))
		else:
			where += " and gl.posting_date between %s and %s"
			wparams.extend([str(getdate(date_a)), str(getdate(date_b))])
		row = frappe.db.sql(
			f"""select {", ".join(cols)}
			from `tabGL Entry` gl
			join `tabAccount` a on a.name = gl.account
				and a.lft between {int(lo)} and {int(hi)}
			where {where}""",
			params + wparams,
			as_dict=True,
		)[0]
		return [int(row[f"v{i}"] or 0) for i in range(len(kids))]

	if mode == "bal":
		vals = value_cols(at=as_of or frappe.utils.today())
		cvals = value_cols(at=cmp_as_of) if cmp_as_of else None
	else:
		vals = value_cols(date_a=from_date, date_b=to_date)
		cvals = value_cols(date_a=cmp_from, date_b=cmp_to) if cmp_from and cmp_to else None

	abbr = f" - {_abbr()}"
	rows = []
	for i, c in enumerate(kids):
		rows.append({
			"name": c.name.replace(abbr, ""),
			"is_group": 1 if c.is_group else 0,
			"root_type": c.root_type,
			"v": vals[i],
			"c": cvals[i] if cvals else None,
		})
	return {"rows": rows, "mode": mode}


# ================= Phase 2: ledger =================

@frappe.whitelist(methods=["GET"])
def ledger(kind, name, from_date, to_date, vtype=None, mode="rows", start=0, party_type=None):
	"""Account or party register.

	mode 'rows': voucher rows, paged 500, with page-start running balance.
	mode 'day' / 'month' / 'vtype': server-side summaries (no paging).
	P&L account ledgers open at the fiscal-year start of from_date and
	exclude PCV rows, per the statement convention.
	"""
	_guard()
	start = min(max(int(start or 0), 0), 100000)
	f, t = getdate(from_date), getdate(to_date)
	if f > t:
		f, t = t, f
	params = [COMPANY]
	if kind == "account":
		acc = _account_row(name)
		if not acc:
			frappe.throw("Unknown account")
		if acc.is_group:
			frappe.throw("Pick a leaf account (use the group drill for groups)")
		who = "gl.account = %s"
		params.append(acc.name)
		is_pl = acc.root_type in ("Income", "Expense")
	elif kind == "party":
		if not frappe.db.exists("Customer", name) and not frappe.db.exists("Supplier", name):
			frappe.throw("Unknown party")
		who = "gl.party = %s"
		params.append(name)
		# A dual-role peer (a Customer AND a Supplier of the same name, e.g.
		# "Krushiyog Plant, Paraswada") otherwise nets its Debtors and Creditors
		# GL into one figure. An optional party_type scopes the register to one
		# side; absent = the combined view (unchanged default).
		if party_type:
			if party_type not in ("Customer", "Supplier"):
				frappe.throw("party_type must be Customer or Supplier")
			who += " and gl.party_type = %s"
			params.append(party_type)
		is_pl = False
	else:
		frappe.throw("kind must be account or party")

	pcv_sql = " and gl.voucher_type != %s" if is_pl else ""
	if is_pl:
		params.append(PCV)
	vt_sql = ""
	if vtype:
		vt_sql = " and gl.voucher_type = %s"
		params.append(vtype)

	base = (
		"from `tabGL Entry` gl where gl.company = %s and gl.is_cancelled = 0 and "
		+ who + pcv_sql + vt_sql
	)

	open_floor = str(_fy_start_for(f)) if is_pl else "1900-01-01"
	opening = frappe.db.sql(
		f"select coalesce(round(sum(gl.debit - gl.credit)), 0) {base} "
		"and gl.posting_date >= %s and gl.posting_date < %s",
		params + [open_floor, str(f)],
	)[0][0]

	rng = params + [str(f), str(t)]
	rng_sql = base + " and gl.posting_date between %s and %s"

	totals = frappe.db.sql(
		f"select count(*), coalesce(round(sum(gl.debit)),0), coalesce(round(sum(gl.credit)),0) {rng_sql}",
		rng,
	)[0]

	out = {
		"opening": int(opening), "count": int(totals[0]),
		"total_dr": int(totals[1]), "total_cr": int(totals[2]),
		"mode": mode,
	}
	if mode in ("day", "month", "vtype"):
		key = {"day": "gl.posting_date", "month": "date_format(gl.posting_date, '%%Y-%%m')",
			"vtype": "gl.voucher_type"}[mode]
		groups = frappe.db.sql(
			f"select {key} as k, count(*), round(sum(gl.debit)), round(sum(gl.credit)) {rng_sql} "
			f"group by {key} order by " + ("sum(gl.debit)+sum(gl.credit) desc" if mode == "vtype" else "k"),
			rng,
		)
		out["groups"] = [[str(g[0]), int(g[1]), int(g[2] or 0), int(g[3] or 0)] for g in groups]
		return out

	page_shift = frappe.db.sql(
		f"""select coalesce(round(sum(x.debit - x.credit)), 0) from (
			select gl.debit, gl.credit {rng_sql}
			order by gl.posting_date, gl.creation limit {int(start)}
		) x""",
		rng,
	)[0][0] if start else 0
	rows = frappe.db.sql(
		f"""select gl.posting_date, gl.voucher_type, gl.voucher_no,
			coalesce(gl.party, ''), gl.account,
			round(gl.debit), round(gl.credit) {rng_sql}
		order by gl.posting_date, gl.creation
		limit 500 offset {int(start)}""",
		rng,
	)
	abbr = f" - {_abbr()}"
	out.update({
		"page_start": start,
		"page_open": int(opening) + int(page_shift),
		"has_more": start + len(rows) < int(totals[0]),
		"rows": [[str(r[0]), r[1], r[2], r[3], (r[4] or "").replace(abbr, ""),
			int(r[5] or 0), int(r[6] or 0)] for r in rows],
	})
	return out


# ================= Phase 2: outstanding / stock =================

def _run_report(report_name, filters):
	from frappe.desk.query_report import run
	return run(report_name, filters=filters, ignore_prepared_report=True)


@frappe.whitelist(methods=["GET"])
def outstanding(side="ar", as_of=None):
	_guard()
	as_of = str(getdate(as_of or frappe.utils.today()))
	report = "Accounts Receivable" if side == "ar" else "Accounts Payable"

	def build():
		res = _run_report(report, {
			"company": COMPANY, "report_date": as_of,
			"ageing_based_on": "Posting Date", "range": "30, 60, 90, 120",
		})
		cols = {c.get("fieldname") for c in res.get("columns", []) if isinstance(c, dict)}
		rk = [k for k in ("range1", "range2", "range3", "range4", "range5") if k in cols]
		agg, vouchers = {}, {}
		for r in res.get("result", []):
			if not (isinstance(r, dict) and r.get("party")):
				continue
			p = agg.setdefault(r["party"], {"out": 0.0, "b": [0.0] * len(rk)})
			p["out"] += r.get("outstanding") or 0
			for j, k in enumerate(rk):
				p["b"][j] += r.get(k) or 0
			if abs(r.get("outstanding") or 0) > 0.5:
				age = (getdate(as_of) - getdate(r.get("posting_date"))).days
				vouchers.setdefault(r["party"], []).append(
					[r.get("voucher_no") or "", str(r.get("posting_date"))[:10],
						int(round(r["outstanding"])), age])
		summary = sorted(
			[[k, int(round(v["out"]))] + [int(round(x)) for x in v["b"]]
				for k, v in agg.items() if abs(v["out"]) > 0.5],
			key=lambda x: -abs(x[1]),
		)
		top = [s[0] for s in summary[:40]]
		drill = {p: sorted(vouchers.get(p, []), key=lambda v: -abs(v[2]))[:25] for p in top}
		return {"side": side, "as_of": as_of, "rows": summary, "drill": drill,
			"total": int(sum(s[1] for s in summary))}

	return _cached(["outstanding", side, as_of], build)


@frappe.whitelist(methods=["GET"])
def stock_balance(from_date, to_date):
	_guard()
	f, t = str(getdate(from_date)), str(getdate(to_date))

	def build():
		res = _run_report("Stock Balance", {
			"company": COMPANY, "from_date": f, "to_date": t,
		})
		items = []
		for r in res.get("result", []):
			if not (isinstance(r, dict) and r.get("item_code")):
				continue
			items.append([
				r.get("item_code"), r.get("item_group") or "",
				round(r.get("opening_qty") or 0, 1), round(r.get("in_qty") or 0, 1),
				round(r.get("out_qty") or 0, 1), round(r.get("bal_qty") or 0, 1),
				int(round(r.get("val_rate") or 0)), int(round(r.get("bal_val") or 0)),
			])
		items.sort(key=lambda x: -abs(x[7]))
		return {"from": f, "to": t, "items": items,
			"total_value": int(sum(i[7] for i in items))}

	return _cached(["stockbal", f, t], build)


@frappe.whitelist(methods=["GET"])
def item_ledger(item, from_date, to_date):
	_guard()
	if not frappe.db.exists("Item", item):
		frappe.throw("Unknown item")
	f, t = str(getdate(from_date)), str(getdate(to_date))
	rows = frappe.db.sql(
		"""select posting_date, round(actual_qty, 1), round(qty_after_transaction, 1),
			round(valuation_rate), voucher_type, voucher_no, warehouse
		from `tabStock Ledger Entry`
		where company = %s and is_cancelled = 0 and item_code = %s
			and posting_date between %s and %s
		order by posting_date desc, creation desc limit 500""",
		(COMPANY, item, f, t),
	)
	# Take the NEWEST 500 (was oldest 500 — a fast-moving item then showed a
	# months-old "current" balance); reverse to render oldest -> newest so the
	# last row's running qty is the real on-hand. has_more flags the truncation.
	truncated = len(rows) >= 500
	rows = list(rows)[::-1]
	return {"item": item, "has_more": truncated, "rows": [
		[str(r[0]), float(r[1] or 0), float(r[2] or 0), int(r[3] or 0), r[4], r[5],
			"" if (r[6] or "").startswith("Main Store") else (r[6] or "").replace(f" - {_abbr()}", "")]
		for r in rows]}


# ================= Phase 2: accountant's note =================

@frappe.whitelist(methods=["GET"])
def acct():
	"""Depreciation schedule, drawings reclass, adjusted profits, corrected
	cash flow and capital events — computed live; narrative constants above."""
	_guard()

	def build():
		d0, asof, nd, daily, leaf, audit = _build_daily()

		def pref(m):
			p = [0] * (nd + 1)
			for i in range(nd):
				p[i + 1] = p[i] + (m.get(str(i)) or 0)
			return p

		P = {b: pref(daily[b]) for b in daily}

		def rng(b, a, z):
			return P[b][min(z, nd - 1) + 1] - P[b][max(a, 0)]

		def bal(b, i):
			return P[b][min(max(i, -1), nd - 1) + 1]

		import datetime
		def didx(dt):
			return (dt - d0).days

		# month grid
		months, cur = [], datetime.date(d0.year, d0.month, 1)
		while cur <= asof:
			nxt = datetime.date(cur.year + (1 if cur.month == 12 else 0),
				1 if cur.month == 12 else cur.month + 1, 1)
			a = max(0, didx(cur))
			z = min(nd - 1, didx(nxt - datetime.timedelta(days=1)))
			months.append((cur, a, z))
			cur = nxt
		# fiscal years present (Apr starts)
		fys = []
		for mi, (mstart, a, z) in enumerate(months):
			if mstart.month == 4 or mi == 0:
				fys.append({"label": f"FY{str(mstart.year)[2:]}-{str(mstart.year + 1)[2:]}",
					"a": a, "mi0": mi})
			fys[-1]["z"] = z
			fys[-1]["mi1"] = mi

		# depreciation: 15% WDV P&M block, half rate for Oct-Mar additions
		sched, open_wdv = [], 0.0
		for fy in fys:
			adds_early = adds_late = disp = 0.0
			for mi in range(fy["mi0"], fy["mi1"] + 1):
				mstart, a, z = months[mi]
				delta = rng("fixed", a, z)
				early = 4 <= mstart.month <= 9
				if delta > 0:
					if early:
						adds_early += delta
					else:
						adds_late += delta
				else:
					disp += -delta
			current = fy is fys[-1] and (asof.month != 3 or asof.day < 31)
			est_full = 0.15 * (open_wdv + adds_early - disp) + 0.075 * adds_late
			if current:
				elapsed = (asof - datetime.date(months[fy["mi0"]][0].year, 4, 1)).days + 1
				dep = 0.15 * (open_wdv + adds_early - disp) * elapsed / 365.0
			else:
				dep = est_full
			sched.append({"fy": fy["label"], "open": round(open_wdv),
				"early": round(adds_early), "late": round(adds_late),
				"disp": round(disp), "est_full": round(est_full), "dep": round(dep),
				"close": round(open_wdv + adds_early + adds_late - disp - dep)})
			open_wdv += adds_early + adds_late - disp - dep

		# drawings: Home* leaves
		home_keys = [k for k in leaf if k.startswith("Home")]
		def leaf_rng(k, a, z):
			return sum(v for i, v in leaf[k].items() if a <= int(i) <= z)
		drawings = {fy["label"]: round(sum(leaf_rng(k, fy["a"], fy["z"]) for k in home_keys))
			for fy in fys}

		# adjusted P&L per FY
		adjusted = []
		for i, fy in enumerate(fys):
			rev = rng("inc", fy["a"], fy["z"])
			rep = rev - rng("dexp", fy["a"], fy["z"]) - rng("iexp", fy["a"], fy["z"])
			gap = -COGS_GAP_CURRENT_FY if fy is fys[-1] else 0
			row = {"fy": fy["label"], "revenue": rev, "reported": rep,
				"dep": -sched[i]["dep"], "drawings": drawings[fy["label"]],
				"cogs_gap": gap}
			row["adjusted"] = rep + row["dep"] + row["drawings"] + row["cogs_gap"]
			adjusted.append(row)

		# corrected CF monthly + capital events
		cf_fix = []
		for mstart, a, z in months:
			prof = rng("inc", a, z) - rng("dexp", a, z) - rng("iexp", a, z)
			def dlt(b):
				return bal(b, z) - bal(b, a - 1)
			ops = prof - dlt("ar") - dlt("stock") - dlt("depo") - dlt("tax") - dlt("susp") \
				+ dlt("ap") + dlt("duty") + dlt("sliab")
			inv = -dlt("fixed")
			dcash = dlt("cash")
			cf_fix.append({"m": mstart.strftime("%b '%y"), "ops": round(ops),
				"inv": round(inv), "fin": round(dcash - ops - inv), "dcash": round(dcash)})

		closures = frappe.db.sql(
			"""select gl.posting_date, round(sum(gl.credit - gl.debit))
			from `tabGL Entry` gl join `tabAccount` a on a.name = gl.account
			where gl.company = %s and gl.is_cancelled = 0
				and gl.voucher_type = %s and a.root_type = 'Equity'
			group by gl.posting_date order by gl.posting_date""",
			(COMPANY, PCV),
		)
		capital_moves = frappe.db.sql(
			"""select gl.posting_date, round(sum(gl.credit - gl.debit))
			from `tabGL Entry` gl join `tabAccount` a on a.name = gl.account
			where gl.company = %s and gl.is_cancelled = 0
				and gl.voucher_type != %s and a.root_type = 'Equity'
			group by gl.posting_date having abs(sum(gl.credit - gl.debit)) > 0.5
			order by gl.posting_date""",
			(COMPANY, PCV),
		)
		fin_events = []
		for i, (dt, amt) in enumerate(capital_moves):
			label = "Books opened - capital brought forward" if i == 0 \
				else "Capital movement (journal)"
			fin_events.append({"date": str(dt), "label": label, "amt": int(amt)})

		history = list(PROFIT_HISTORY_CARRIED)
		for i, fy in enumerate(fys):
			live = fy is fys[-1]
			history.append({"fy": fy["label"] + (" YTD" if live else ""),
				"profit": adjusted[i]["reported"],
				"src": "live, to " + asof.strftime("%d-%m-%Y") if live else "full books (PCV closed)"})

		return {
			"asof": str(asof),
			"sched": sched, "drawings": drawings, "adjusted": adjusted,
			"profit_history": history,
			"cf_fix": cf_fix,
			"closures": [[str(c[0]), int(c[1])] for c in closures],
			"fin_events": fin_events,
			"review": REVIEW_ITEMS, "proposed": PROPOSED_ACTIONS,
			"cogs_gap": COGS_GAP_CURRENT_FY,
		}

	return _cached(["acct", COMPANY], build)


# ================= PWA wrapper =================

@frappe.whitelist(allow_guest=True, methods=["GET"])
def manifest():
	m = {
		"name": "VAC Cockpit",
		"short_name": "VAC Cockpit",
		"start_url": SCOPE,
		"scope": SCOPE,
		"display": "standalone",
		"background_color": "#0d0d0d",
		"theme_color": "#006300",
		"icons": [
			{"src": "/assets/agriops_suite/images/slip-icon-192.png",
				"sizes": "192x192", "type": "image/png"},
			{"src": "/assets/agriops_suite/images/slip-icon-512.png",
				"sizes": "512x512", "type": "image/png"},
		],
	}
	from werkzeug.wrappers import Response
	resp = Response(json.dumps(m), mimetype="application/manifest+json")
	resp.headers["Cache-Control"] = "no-cache"
	return resp


@frappe.whitelist(allow_guest=True, methods=["GET"])
def sw():
	from werkzeug.wrappers import Response
	path = frappe.get_app_path("agriops_suite", "public", "js", "fin_sw.js")
	with open(path, encoding="utf-8") as f:
		body = f.read()
	resp = Response(body, mimetype="text/javascript")
	resp.headers["Service-Worker-Allowed"] = SCOPE
	resp.headers["Cache-Control"] = "no-cache"
	return resp
