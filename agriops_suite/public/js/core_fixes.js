// ============================================================================
// Targeted runtime fixes for upstream ERPNext v16 bugs. No core files are
// edited; each fix wraps the affected function and defers to the original
// everywhere else. Drop each entry once the upstream fix ships.
//
// FIX 1 — horizontal Financial Report Templates render every cell blank.
// erpnext.financial_statements.formatter starts with is_blank_row(), which
// treats any row without a plain account/account_name/section_name field as
// a spacer and returns "". Horizontal/Columnar templates (e.g. "Horizontal
// Balance Sheet (Columnar)") emit rows whose fields all live behind seg_N_
// prefixes (plus _segment_info/segment_values), so EVERY row of a horizontal
// template was blanked. Segmented rows are never blanket-blank: the
// per-column formatters already handle their empty cells (is_blank_line).
// ============================================================================
(function () {
	var tries = 0;
	function patch() {
		var fs = window.erpnext && erpnext.financial_statements;
		if (!fs || !fs.is_blank_row) {
			// erpnext.financial_statements only loads on a Financial Statement report
			// view; on every other page it never appears. Cap the poll so this isn't
			// an endless 500ms timer for the life of the tab.
			if (++tries > 40) return;
			return setTimeout(patch, 500);
		}
		if (fs.__vac_blankrow_patched) return;
		fs.__vac_blankrow_patched = true;
		var orig = fs.is_blank_row;
		fs.is_blank_row = function (data) {
			if (data && data._segment_info) return false;
			return orig(data);
		};
	}
	patch();
	$(document).ready(patch);
})();
