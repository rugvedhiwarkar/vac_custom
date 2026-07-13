/* VAC morning greeting banner — injected at the top of the VAC landing
 * workspace. Gated on frappe.boot.vac_theme_enabled (same per-site switch as
 * the desk theme), so production stays untouched until the flag is set.
 *
 * The banner is greeting-only (no KPI tiles); the workspace's own number cards
 * carry the metrics and pick up the lifted-card finish from vac_theme.css.
 */
(function () {
	if (!(window.frappe && frappe.boot && frappe.boot.vac_theme_enabled)) return;

	var LANDING = "VAC"; // workspace name behind the / redirect

	// client-side count with explicit list-filters — frappe.db.count silently
	// drops object filters here and returns the table total, so call get_count
	// directly with [[field, op, value], ...].
	function count(doctype, filters) {
		return frappe
			.call("frappe.client.get_count", { doctype: doctype, filters: filters })
			.then(function (r) {
				return r && r.message != null ? r.message : null;
			})
			.catch(function () {
				return null;
			});
	}

	function build() {
		var wrap = document.createElement("div");
		wrap.id = "vac-greet-wrap";
		wrap.innerHTML =
			'<div class="b">' +
			'<div class="eyebrow" id="vg-eyebrow">This morning at the shop</div>' +
			'<h1 id="vg-greet">Good morning</h1>' +
			"<p id=\"vg-sub\">Here's how Vijay Agro Centre is doing today.</p>" +
			'<div class="meta">' +
			'<span class="tag">FY <b id="vg-fy">—</b></span>' +
			'<span class="tag" id="vg-tills-tag">— tills open</span>' +
			'<span class="tag" id="vg-bills-tag">— bills so far today</span>' +
			'<span class="tag">Last synced <b id="vg-sync">—</b></span>' +
			"</div></div>";
		return wrap;
	}

	function fill(wrap) {
		function q(id) {
			return wrap.querySelector("#" + id);
		}
		var h = new Date().getHours();
		var period = h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
		var fn = ((frappe.session.user_fullname || "") + "").trim().split(" ")[0];
		if (q("vg-eyebrow"))
			q("vg-eyebrow").textContent = "This " + period + " at the shop";
		if (q("vg-greet"))
			q("vg-greet").textContent =
				"Good " + period + (fn ? ", " + fn : "") + " " + String.fromCodePoint(0x1f33e);
		var m = window.moment ? moment() : null;
		if (q("vg-sub"))
			q("vg-sub").textContent =
				"Here's how Vijay Agro Centre is doing today" +
				(m ? ", " + m.format("dddd D MMMM YYYY") : "") +
				".";
		var dt = new Date(),
			mo = dt.getMonth() + 1,
			fsy = mo >= 4 ? dt.getFullYear() : dt.getFullYear() - 1;
		if (q("vg-fy")) q("vg-fy").textContent = fsy + "–" + String(fsy + 1).slice(2);
		if (m && q("vg-sync")) q("vg-sync").textContent = m.format("h:mm A");

		var today = frappe.datetime.get_today();
		count("POS Opening Entry", [
			["status", "=", "Open"],
			["docstatus", "=", 1],
		]).then(function (n) {
			if (n != null && q("vg-tills-tag"))
				q("vg-tills-tag").innerHTML =
					"<b>" + n + "</b> " + (n === 1 ? "till" : "tills") + " open";
		});
		count("Sales Invoice", [
			["posting_date", "=", today],
			["docstatus", "=", 1],
			["is_return", "=", 0],
		]).then(function (n) {
			if (n != null && q("vg-bills-tag"))
				q("vg-bills-tag").innerHTML =
					"<b>" + n + "</b> " + (n === 1 ? "bill" : "bills") + " so far today";
		});
	}

	function on_landing() {
		var r = frappe.get_route ? frappe.get_route() : [];
		return r && r[0] === "Workspaces" && r[1] === LANDING;
	}

	function try_inject(n) {
		if (!on_landing()) return;
		if (document.getElementById("vac-greet-wrap")) return;
		// Wait for the workspace content to actually RENDER before showing the
		// banner. Injecting as soon as the empty container exists made the banner
		// appear ahead of the KPI cards on a cold first load — the cards fetch
		// their data async, so there was a visible empty gap below the banner
		// until they filled in (and it was fine on return visits because the
		// page was cached). Require the redactor to have blocks; only after the
		// retries are exhausted, inject anyway so the banner is never lost.
		var redactor = document.querySelector(".codex-editor__redactor");
		var target =
			redactor && redactor.children.length > 0
				? redactor
				: n <= 0
				? redactor || document.querySelector(".layout-main-section")
				: null;
		if (target) {
			var wrap = build();
			target.parentNode.insertBefore(wrap, target);
			fill(wrap);
			return;
		}
		if (n > 0) setTimeout(function () { try_inject(n - 1); }, 200);
	}

	function handle() {
		if (on_landing()) {
			try_inject(50);
		} else {
			var e = document.getElementById("vac-greet-wrap");
			if (e) e.remove();
		}
	}

	if (frappe.router && frappe.router.on) frappe.router.on("change", handle);
	$(document).on("page-change", handle);
	handle();
})();
