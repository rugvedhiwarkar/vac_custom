// ============================================================================
// FinScope — BusyWin-style ledger features for the FinScope report delegates
// and the StockPilot report suite.
//
// Loaded on every desk page via app_include_js, but SELF-GATING: every hook
// re-checks the current report name and activates ONLY on reports whose name
// starts with one of the known prefixes. Standard reports — and every report
// on a site that has none of ours — are untouched, so this file is safe to
// ship to the shared prod+staging bench ahead of the reports themselves.
//
// Features (persisted per-browser in localStorage, keyed per report):
//   - persistent column ORDER  (drag a column; survives Refresh and reload)
//   - persistent column WIDTH  (drag a column edge; survives Refresh and reload)
//   - column VISIBILITY        (remove a column, or use the "Columns" picker)
//   - column RENAME            (pencil in the "Columns" picker; reset restores)
//   - Summarize By any column  (2 levels) with collapsible drill-down; group
//     headers subtotal amount columns only (balance/opening/closing excluded);
//     GL-style Opening/Total/Closing rows are pinned outside the groups.
//     Reports that render their OWN tree (rows carry `indent`, e.g. the
//     StockPilot family reports) keep the column tools but skip Summarize —
//     grouping an already-grouped tree would double-count parents.
// ============================================================================
frappe.provide("finscope");

finscope.PREFIXES = ["FinScope - ", "StockPilot "];
// Standard reports (e.g. "General Ledger") augmented IN-PLACE, opt-in PER SITE
// via site_config `finscope_ledger_reports` (surfaced on frappe.boot). Empty by
// default => shipping this changes nothing until a site enables it. Exact-name
// match only, so unrelated reports are never touched.
finscope.exact_reports = function () {
	try { return (frappe.boot && frappe.boot.finscope_ledger_reports) || []; } catch (e) { return []; }
};
finscope.is_feature_report = function (name) {
	if (typeof name !== "string") return false;
	for (var i = 0; i < finscope.PREFIXES.length; i++) {
		if (name.indexOf(finscope.PREFIXES[i]) === 0) return true;
	}
	if (finscope.exact_reports().indexOf(name) >= 0) return true;
	return false;
};
finscope.native_tree = function (rows) {
	for (var i = 0; i < (rows || []).length; i++) {
		if (rows[i] && rows[i].indent !== undefined && rows[i].indent !== null) return true;
	}
	return false;
};
finscope.on = function () {
	var r = frappe.query_report;
	return !!(r && finscope.is_feature_report(r.report_name));
};

finscope.rname = () => (frappe.query_report ? frappe.query_report.report_name : "x");
finscope.col_key = () => "finscope_colorder::" + finscope.rname();
finscope.sum_key = () => "finscope_summarize::" + finscope.rname();
finscope.hid_key = () => "finscope_hidden::" + finscope.rname();
finscope.ren_key = () => "finscope_rename::" + finscope.rname();
finscope.wid_key = () => "finscope_width::" + finscope.rname();
finscope.ls_get = (k) => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } };
finscope.ls_set = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
finscope.get_hidden = () => finscope.ls_get(finscope.hid_key()) || [];
finscope.set_hidden = (a) => finscope.ls_set(finscope.hid_key(), a);
finscope.get_renames = () => finscope.ls_get(finscope.ren_key()) || {};
finscope.set_renames = (m) => finscope.ls_set(finscope.ren_key(), m);
finscope.get_widths = () => finscope.ls_get(finscope.wid_key()) || {};
finscope.set_widths = (m) => finscope.ls_set(finscope.wid_key(), m);
finscope.fields_in_order = (dt) => (dt.getColumns() || []).map((c) => c.fieldname).filter(Boolean);

/* ---- visibility + rename: rebuild report.columns from the pristine set ----
   __fs_cols (stashed in prepare_report_data) is never mutated; renamed
   columns are shallow CLONES so the original labels survive a reset. */
finscope.apply_hidden = function (report) {
	var full = (report.__fs_cols && report.__fs_cols.length ? report.__fs_cols : report.columns) || [];
	var hidden = finscope.get_hidden();
	var ren = finscope.get_renames();
	var vis = hidden.length ? full.filter((c) => hidden.indexOf(c.fieldname) < 0) : full.slice();
	// frappe bakes the header text into column.name/content at prepare time
	// (prepare_columns), so a rename must override those too, not just label.
	report.columns = vis.map((c) =>
		ren[c.fieldname]
			? Object.assign({}, c, { label: ren[c.fieldname], name: ren[c.fieldname], content: ren[c.fieldname] })
			: c
	);
};

/* ---- persistent column ORDER ---- */
finscope.save_order = function () {
	var r = frappe.query_report;
	if (r && r.datatable) finscope.ls_set(finscope.col_key(), finscope.fields_in_order(r.datatable));
};
finscope.apply_order = async function (report) {
	var dt = report.datatable; if (!dt) return;
	var saved = finscope.ls_get(finscope.col_key()); if (!saved || !saved.length) return;
	var cm = dt.columnmanager; if (!cm || !cm.switchColumn) return;
	var existing = finscope.fields_in_order(dt);
	var target = saved.filter((f) => existing.indexOf(f) >= 0);
	existing.forEach((f) => { if (target.indexOf(f) < 0) target.push(f); });
	if (existing.join(",") === target.join(",")) return;
	report.__fs_applying = true;
	try {
		for (var pos = 0; pos < target.length; pos++) {
			var cur = dt.getColumns().map((c) => c.fieldname);
			var from = cur.indexOf(target[pos]); var to = pos + 1;
			if (from > 0 && from !== to) { cm.switchColumn(to, from); await new Promise((r) => setTimeout(r, 70)); }
		}
	} catch (e) { console.error("FinScope order", e); }
	report.__fs_applying = false;
};
finscope.decorate_options = function (options) {
	try {
		var saved = finscope.ls_get(finscope.col_key());
		if (saved && saved.length && options.columns) {
			var map = {}; options.columns.forEach((c) => (map[c.fieldname] = c));
			var re = [];
			saved.forEach((f) => { if (map[f]) { re.push(map[f]); delete map[f]; } });
			options.columns.forEach((c) => { if (map[c.fieldname]) { re.push(c); delete map[c.fieldname]; } });
			if (re.length === options.columns.length) options.columns = re;
		}
	} catch (e) {}
	try {
		var savedW = finscope.get_widths();
		if (options.columns && Object.keys(savedW).length) {
			options.columns.forEach((c) => { if (c.fieldname && savedW[c.fieldname]) c.width = savedW[c.fieldname]; });
		}
	} catch (e) {}
	options.events = options.events || {};
	var prevSw = options.events.onSwitchColumn;
	options.events.onSwitchColumn = function () {
		if (prevSw) { try { prevSw.apply(this, arguments); } catch (e) {} }
		var r = frappe.query_report; if (r && r.__fs_applying) return;
		setTimeout(finscope.save_order, 80);
	};
	var prevRm = options.events.onRemoveColumn;
	options.events.onRemoveColumn = function (col) {
		if (prevRm) { try { prevRm.apply(this, arguments); } catch (e) {} }
		try {
			var fn = col && col.fieldname;
			if (fn) { var h = finscope.get_hidden(); if (h.indexOf(fn) < 0) { h.push(fn); finscope.set_hidden(h); } }
		} catch (e) {}
	};
	return options;
};

/* ---- summarize + drill-down ---- */
finscope.is_sum_col = function (col) {
	var ft = (col.fieldtype || "").toLowerCase();
	if (["currency", "float", "int", "percent"].indexOf(ft) < 0) return false;
	return !/balance|closing|opening/.test((col.fieldname || "").toLowerCase());
};
finscope.cell = function (row, fn) { var v = row[fn]; return v === undefined || v === null || v === "" ? "(Blank)" : v; };
finscope.pin_kind = function (row, columns) {
	for (var i = 0; i < columns.length; i++) {
		var v = row[columns[i].fieldname];
		if (typeof v !== "string") continue;
		var s = v.trim().replace(/^['"]+/, "").replace(/['"]+$/, "").toLowerCase();
		if (!s) continue;
		if (/^opening\b/.test(s)) return "top";
		if (/^(total|closing|grand total|net total|difference)\b/.test(s)) return "bottom";
		return false;
	}
	return false;
};
finscope.build_groups = function (flat, columns, by1, by2, all_cols) {
	var lookup = all_cols && all_cols.length ? all_cols : columns;
	var c1 = lookup.find((c) => c.fieldname === by1);
	if (!c1) return { rows: flat, tree: false };
	var c2 = by2 ? lookup.find((c) => c.fieldname === by2) : null;
	var sumCols = columns.filter(finscope.is_sum_col);
	var TEXTY = ["", "data", "link", "dynamic link", "text", "small text", "text editor", "select", "autocomplete", "html"];
	var labelCol = columns.find((c) => c.fieldname && !c.hidden && TEXTY.indexOf((c.fieldtype || "").toLowerCase()) >= 0) || c1;
	var labelField = labelCol.fieldname;
	var top = [], bottom = [], mid = [];
	flat.forEach((r) => { var k = finscope.pin_kind(r, columns); if (k === "top") top.push(r); else if (k === "bottom") bottom.push(r); else mid.push(r); });
	function grp(rows, col) { var order = [], map = {}; rows.forEach((r) => { var k = String(finscope.cell(r, col.fieldname)); if (!(k in map)) { map[k] = []; order.push(k); } map[k].push(r); }); return { order, map }; }
	function header(node, parent, indent, lf, key, members) { var h = { _fs_node: node, _fs_parent: parent, indent: indent, __fs_group: 1 }; h[lf] = String(key) + "  (" + members.length + ")"; sumCols.forEach((c) => { h[c.fieldname] = members.reduce((s, m) => s + (parseFloat(m[c.fieldname]) || 0), 0); }); return h; }
	function leaf(m, node, parent, indent) { var d = Object.assign({}, m); d._fs_node = node; d._fs_parent = parent; d.indent = indent; return d; }
	var out = [], pi = 0;
	top.forEach((r) => out.push(leaf(r, "fstop" + pi++, "", 0)));
	var gi = 0, g1 = grp(mid, c1);
	g1.order.forEach((k1) => {
		var members = g1.map[k1]; var gid = "fsg" + gi++;
		out.push(header(gid, "", 0, labelField, k1, members));
		if (c2) {
			var g2 = grp(members, c2), si = 0;
			g2.order.forEach((k2) => { var subs = g2.map[k2]; var sid = gid + "s" + si++; out.push(header(sid, gid, 1, labelField, k2, subs)); subs.forEach((m, j) => out.push(leaf(m, sid + "d" + j, sid, 2))); });
		} else { members.forEach((m, j) => out.push(leaf(m, gid + "d" + j, gid, 1))); }
	});
	bottom.forEach((r) => out.push(leaf(r, "fsbot" + pi++, "", 0)));
	return { rows: out, tree: true };
};
finscope.apply_summarize = function (report) {
	var flat = report.__fs_flat; if (!flat) return;
	// native-tree reports manage their own indent hierarchy — leave data,
	// tree flags and rendering entirely alone
	if (finscope.native_tree(flat)) return;
	var sel = finscope.ls_get(finscope.sum_key()) || { by1: "", by2: "" };
	var treeNow = !!sel.by1;
	if (treeNow) {
		var res = finscope.build_groups(flat, report.columns, sel.by1, sel.by2, report.__fs_cols);
		report.data = res.rows; report.tree_report = true;
		report.report_settings.tree = true; report.report_settings.name_field = "_fs_node"; report.report_settings.parent_field = "_fs_parent";
		if (typeof report.report_settings.initial_depth !== "number") report.report_settings.initial_depth = 0;
	} else {
		report.data = flat; report.tree_report = false; report.report_settings.tree = false;
	}
	if (report.__fs_tree_state !== treeNow || treeNow) {
		report.__fs_tree_state = treeNow;
		if (report.datatable) { try { report.$report.empty(); } catch (e) {} report.datatable = null; }
	}
};

/* ---- control bar: Summarize By + Columns picker (hide / rename / reset) ---- */
finscope.icon = function (name, fallback) {
	try { if (frappe.utils.icon) return frappe.utils.icon(name, "sm"); } catch (e) {}
	return fallback;
};
finscope.add_control = function (report) {
	// the desk reuses ONE QueryReport instance across in-SPA navigation, so
	// the bar must be rebuilt per report (and removed on non-FinScope ones)
	if (!report.$report) return;
	if (report.__fs_ctrl === report.report_name) return;
	var visCols = (report.columns || []).filter((c) => c.fieldname && c.label);
	if (!visCols.length) return;
	report.__fs_ctrl = report.report_name;
	$(".finscope-summarize-bar").remove();
	var nativeTree = finscope.native_tree(report.__fs_flat);
	var ren0 = finscope.get_renames();
	var $bar = $('<div class="finscope-summarize-bar" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:2px 0 10px;"></div>');
	if (!nativeTree) {
		var sel = finscope.ls_get(finscope.sum_key()) || { by1: "", by2: "" };
		var groupCols = (report.__fs_cols && report.__fs_cols.length ? report.__fs_cols : report.columns).filter((c) => c.fieldname && c.label && !c.hidden);
		var opts = '<option value="">— none —</option>' + groupCols.map((c) => '<option value="' + c.fieldname + '">' + frappe.utils.escape_html(ren0[c.fieldname] || c.label) + "</option>").join("");
		$bar.append('<span style="font-weight:600;">Summarize By</span>' +
			'<select class="fs-by1 form-control input-xs" style="width:200px">' + opts + "</select>" +
			'<span class="text-muted">then</span>' +
			'<select class="fs-by2 form-control input-xs" style="width:200px">' + opts + "</select>");
		$bar.find(".fs-by1").val(sel.by1 || ""); $bar.find(".fs-by2").val(sel.by2 || "");
		$bar.find("select").on("change", function () {
			finscope.ls_set(finscope.sum_key(), { by1: $bar.find(".fs-by1").val(), by2: $bar.find(".fs-by2").val() });
			report.render_datatable();
		});
	} else {
		$bar.append('<span style="font-weight:600;">' + __("Ledger Tools") + "</span>");
	}

	// --- Columns picker: show/hide checkbox + rename pencil + reset, persisted ---
	var allCols = (report.__fs_cols && report.__fs_cols.length ? report.__fs_cols : report.columns).filter((c) => c.fieldname && c.label && !c.hidden);
	var $colWrap = $('<div style="position:relative;display:inline-block;margin-left:6px;">');
	var $colBtn = $('<button class="btn btn-default btn-xs">Columns ▾</button>');
	var $colMenu = $('<div style="display:none;position:absolute;z-index:1010;top:100%;left:0;background:var(--fg-color,#fff);border:1px solid var(--border-color,#d1d8dd);border-radius:6px;padding:6px;max-height:320px;overflow:auto;min-width:260px;box-shadow:0 4px 14px rgba(0,0,0,.18);"></div>');
	function rebuildMenu() {
		var hidden = finscope.get_hidden();
		var ren = finscope.get_renames();
		$colMenu.empty();
		allCols.forEach(function (c) {
			var eff = ren[c.fieldname] || c.label;
			var $row = $('<div style="display:flex;align-items:center;gap:7px;padding:4px 6px;white-space:nowrap;border-radius:4px;"></div>');
			var $chk = $('<input type="checkbox" style="cursor:pointer;margin:0;" ' + (hidden.indexOf(c.fieldname) < 0 ? "checked" : "") + ">");
			$chk.on("change", function () {
				var h = finscope.get_hidden();
				if (this.checked) h = h.filter((x) => x !== c.fieldname);
				else if (h.indexOf(c.fieldname) < 0) h.push(c.fieldname);
				finscope.set_hidden(h);
				report.render_datatable();
			});
			var hint = ren[c.fieldname] ? ' <span class="text-muted" style="font-size:11px">(' + frappe.utils.escape_html(c.label) + ")</span>" : "";
			var $lbl = $('<span style="flex:1;">' + frappe.utils.escape_html(eff) + hint + "</span>");
			var $edit = $('<a title="Rename column" style="cursor:pointer;opacity:.65;line-height:1;">' + finscope.icon("edit", "&#9998;") + "</a>");
			$edit.on("click", function (e) {
				e.preventDefault(); e.stopPropagation();
				frappe.prompt(
					{ fieldname: "label", fieldtype: "Data", label: __("Column label"), reqd: 1, default: eff },
					function (v) {
						var m = finscope.get_renames();
						var nl = (v.label || "").trim();
						if (!nl || nl === c.label) delete m[c.fieldname]; else m[c.fieldname] = nl;
						finscope.set_renames(m);
						report.render_datatable();
						rebuildMenu();
					},
					__("Rename column"), __("Save")
				);
			});
			$row.append($chk).append($lbl).append($edit);
			if (ren[c.fieldname]) {
				var $rst = $('<a title="Reset name" style="cursor:pointer;opacity:.65;line-height:1;">' + finscope.icon("refresh", "&#8634;") + "</a>");
				$rst.on("click", function (e) {
					e.preventDefault(); e.stopPropagation();
					var m = finscope.get_renames();
					delete m[c.fieldname];
					finscope.set_renames(m);
					report.render_datatable();
					rebuildMenu();
				});
				$row.append($rst);
			}
			$colMenu.append($row);
		});
	}
	$colBtn.on("click", function (e) { e.preventDefault(); rebuildMenu(); $colMenu.toggle(); });
	$(document).off("click.fscols").on("click.fscols", function (e) {
		if ($colWrap[0] && !$colWrap[0].contains(e.target) && !$(e.target).closest(".modal").length) $colMenu.hide();
	});
	$colWrap.append($colBtn).append($colMenu);
	$bar.append($colWrap);

	$bar.insertBefore(report.$report);
};

finscope.wrap_settings = function (report) {
	var rs = report.report_settings;
	if (!rs || rs.__fs_wrapped) return;
	rs.__fs_wrapped = true;
	var prevGDO = rs.get_datatable_options;
	rs.get_datatable_options = function (options) {
		if (prevGDO) { try { options = prevGDO.call(rs, options) || options; } catch (e) {} }
		return finscope.on() ? finscope.decorate_options(options) : options;
	};
	var prevADR = rs.after_datatable_render;
	rs.after_datatable_render = function (d) {
		if (prevADR) { try { prevADR.call(rs, d); } catch (e) {} }
		if (!finscope.on()) return;
		try { finscope.apply_order(frappe.query_report); } catch (e) {}
		try { finscope.add_control(frappe.query_report); } catch (e) {}
	};
	var prevFmt = rs.formatter;
	rs.formatter = function (value, row, column, data, df) {
		if (finscope.on() && data && data.__fs_group) return "<b>" + df(value, row, column, data) + "</b>";
		if (prevFmt) { try { return prevFmt(value, row, column, data, df); } catch (e) {} }
		return df(value, row, column, data);
	};
};

// Replicate the FinScope-GL delegate's dual-role party search onto the STANDARD
// General Ledger (only where the finscope_ledger_reports flag enabled GL): with no
// Party Type chosen, search Customers AND Suppliers together (dual-role parties tagged
// "Customer + Supplier"), and drop depends_on so Party is typeable without a type.
finscope.dual_party_get_data = function (txt) {
	var pt = frappe.query_report.get_filter_value("party_type");
	if (pt) return frappe.db.get_link_options(pt, txt);
	return Promise.all([
		frappe.db.get_link_options("Customer", txt),
		frappe.db.get_link_options("Supplier", txt),
	]).then(function (res) {
		var seen = {}, out = [];
		[["Customer", res[0]], ["Supplier", res[1]]].forEach(function (pair) {
			(pair[1] || []).forEach(function (o) {
				var v = (o && o.value !== undefined) ? o.value : o;
				if (seen[v]) { seen[v].description = "Customer + Supplier"; return; }
				var row = { value: v, description: pair[0] }; seen[v] = row; out.push(row);
			});
		});
		return out;
	});
};
finscope.patch_gl_party = function () {
	var KEY = "General Ledger";
	var store = frappe.query_reports || (frappe.query_reports = {});
	function patch(cfg) {
		try {
			if (!cfg || !cfg.filters || cfg.__fs_party) return cfg;
			var party = cfg.filters.filter(function (f) { return f.fieldname === "party"; })[0];
			if (!party) return cfg;
			cfg.__fs_party = 1;
			party.depends_on = undefined;
			party.get_data = finscope.dual_party_get_data;
		} catch (e) { console.error("FinScope GL party patch", e); }
		return cfg;
	}
	// GL js is a page_js loaded after this boot script, so intercept its assignment;
	// if it somehow loaded first, patch what's already there.
	if (store[KEY]) { patch(store[KEY]); return; }
	try {
		var held;
		Object.defineProperty(store, KEY, {
			configurable: true, enumerable: true,
			get: function () { return held; },
			set: function (v) { held = patch(v); },
		});
	} catch (e) { /* interceptor unsupported — standard GL keeps its stock party filter */ }
};

finscope.init = function () {
	if (finscope.__inited) return;
	if (!(frappe.views && frappe.views.QueryReport)) return setTimeout(finscope.init, 200);
	finscope.__inited = true;
	var proto = frappe.views.QueryReport.prototype;
	var origPrep = proto.prepare_report_data;
	proto.prepare_report_data = function () {
		var ret = origPrep.apply(this, arguments);
		if (finscope.is_feature_report(this.report_name)) {
			try { this.__fs_flat = (this.data || []).slice(); this.__fs_cols = (this.columns || []).slice(); } catch (e) {}
		}
		return ret;
	};
	var origRender = proto.render_datatable;
	proto.render_datatable = function () {
		if (finscope.is_feature_report(this.report_name)) {
			try { finscope.wrap_settings(this); } catch (e) {}
			try { finscope.apply_hidden(this); } catch (e) {}
			try { finscope.apply_summarize(this); } catch (e) {}
		} else {
			try {
				$(".finscope-summarize-bar").remove();
				this.__fs_ctrl = null;
				if (this.__fs_tree_state) { this.tree_report = false; this.__fs_tree_state = false; }
			} catch (e) {}
		}
		return origRender.apply(this, arguments);
	};
	// SPA route changes reuse the QueryReport instance and may show a message
	// instead of rendering (e.g. prepared reports), so render-time cleanup is
	// not enough: scrub the control bar + tree state whenever the route leaves
	// a FinScope report.
	frappe.router.on("change", function () {
		try {
			var rt = frappe.get_route();
			var isFs = rt && rt[0] === "query-report" && finscope.is_feature_report(rt[1]);
			if (isFs) return;
			$(".finscope-summarize-bar").remove();
			var r = frappe.query_report;
			if (r && r.__fs_tree_state) {
				r.__fs_tree_state = false; r.tree_report = false; r.__fs_ctrl = null;
				if (r.report_settings) r.report_settings.tree = false;
				if (r.datatable) { try { r.$report.empty(); } catch (e) {} r.datatable = null; }
			}
		} catch (e) {}
	});
	// persist column WIDTHS: after any mouse-up while on a feature report, if a
	// column width changed (i.e. a resize just happened) snapshot all widths.
	$(document).on("mouseup.fswidth", function () {
		var r = frappe.query_report;
		if (!r || !r.datatable || !finscope.on()) return;
		setTimeout(function () {
			if (!r.datatable) return;
			var cols = r.datatable.getColumns() || [];
			var cur = {}, changed = false;
			cols.forEach(function (c) { if (c.fieldname && c.width) cur[c.fieldname] = c.width; });
			var saved = finscope.get_widths();
			Object.keys(cur).forEach(function (k) { if (saved[k] !== cur[k]) changed = true; });
			if (changed) finscope.set_widths(cur);
		}, 150);
	});
	// GL dual-role party filter — only where the flag enabled the standard General Ledger.
	if (finscope.is_feature_report("General Ledger")) { try { finscope.patch_gl_party(); } catch (e) {} }
	console.log("FinScope: ledger features active (order / width / hide / rename / summarize) for 'FinScope - *' and 'StockPilot *' reports");
};
finscope.init();
$(document).ready(finscope.init);
