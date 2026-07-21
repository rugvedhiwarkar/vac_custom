/* VAC greeting banner — injected at the top of every workspace. Gated on
 * frappe.boot.vac_theme_enabled (same per-site switch as the desk theme), so
 * production stays untouched until the flag is set.
 *
 * The banner is greeting-only (no KPI tiles); each workspace's own number cards
 * carry the metrics and pick up the lifted-card finish from vac_theme.css.
 *
 * It is role-aware. Counter staff get an operational greeting only — the shift
 * and the bill count — with no fiscal-year or group-level framing, because
 * those belong to the people who own the books, not the till.
 */
(function () {
	if (!(window.frappe && frappe.boot && frappe.boot.vac_theme_enabled)) return;

	function has_role(role) {
		var roles = (frappe.boot && frappe.boot.user && frappe.boot.user.roles) || [];
		return roles.indexOf(role) !== -1;
	}

	// Order matters: Administrator carries every role, so it must be matched
	// before Director, and Director before the generic System Manager.
	function persona() {
		if (frappe.session.user === "Administrator") return "admin";
		if (has_role("Director")) return "director";
		if (has_role("System Manager")) return "admin";
		return "staff";
	}

	var COPY = {
		admin: {
			where: "at Vijay Agro Centre",
			sub: "Vijay Agro Centre and Krushiyog Plant",
			tags: ["fy", "tills", "bills", "sync"],
		},
		director: {
			where: "across the group",
			sub: "Krushiyog Plant and Vijay Agro Centre",
			tags: ["fy", "tills", "bills", "sync"],
		},
		staff: {
			where: "at the counter",
			sub: "Here's your day at the counter",
			tags: ["tills", "bills"],
		},
	};

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

	var TAG_HTML = {
		fy: '<span class="tag">FY <b id="vg-fy">—</b></span>',
		tills: '<span class="tag" id="vg-tills-tag">— tills open</span>',
		bills: '<span class="tag" id="vg-bills-tag">— bills so far today</span>',
		sync: '<span class="tag">Last synced <b id="vg-sync">—</b></span>',
	};

	function build(who) {
		var meta = COPY[who].tags
			.map(function (t) {
				return TAG_HTML[t];
			})
			.join("");
		var wrap = document.createElement("div");
		wrap.id = "vac-greet-wrap";
		wrap.innerHTML =
			'<div class="b">' +
			'<div class="eyebrow" id="vg-eyebrow">This morning</div>' +
			'<h1 id="vg-greet">Good morning</h1>' +
			'<p id="vg-sub"></p>' +
			'<div class="meta">' +
			meta +
			"</div></div>";
		return wrap;
	}

	function fill(wrap, who) {
		function q(id) {
			return wrap.querySelector("#" + id);
		}
		// Counter (staff) view is VAC-specific: scope its counts to the default company
		// so KP/KFC/VSS documents don't inflate "bills today" / "tills open".
		var dco = (frappe.defaults && frappe.defaults.get_default) ? frappe.defaults.get_default("company") : null;
		var coFilter = (who === "staff" && dco) ? [["company", "=", dco]] : [];
		var h = new Date().getHours();
		var period = h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
		var fn = ((frappe.session.user_fullname || "") + "").trim().split(" ")[0];
		if (q("vg-eyebrow"))
			q("vg-eyebrow").textContent = "This " + period + " " + COPY[who].where;
		if (q("vg-greet"))
			q("vg-greet").textContent =
				"Good " + period + (fn ? ", " + fn : "") + " " + String.fromCodePoint(0x1f33e);
		var m = window.moment ? moment() : null;
		var when = m ? ", " + m.format("dddd D MMMM YYYY") : "";
		if (q("vg-sub"))
			q("vg-sub").textContent =
				who === "staff"
					? COPY.staff.sub + when + "."
					: "Here's how " + COPY[who].sub + " are doing today" + when + ".";
		if (q("vg-fy")) {
			var dt = new Date(),
				mo = dt.getMonth() + 1,
				fsy = mo >= 4 ? dt.getFullYear() : dt.getFullYear() - 1;
			q("vg-fy").textContent = fsy + "–" + String(fsy + 1).slice(2);
		}
		if (m && q("vg-sync")) q("vg-sync").textContent = m.format("h:mm A");

		if (q("vg-tills-tag"))
			count("POS Opening Entry", coFilter.concat([
				["status", "=", "Open"],
				["docstatus", "=", 1],
			])).then(function (n) {
				if (n != null && q("vg-tills-tag"))
					q("vg-tills-tag").innerHTML =
						"<b>" + n + "</b> " + (n === 1 ? "till" : "tills") + " open";
			});
		if (q("vg-bills-tag"))
			count("Sales Invoice", coFilter.concat([
				["posting_date", "=", frappe.datetime.get_today()],
				["docstatus", "=", 1],
				["is_return", "=", 0],
			])).then(function (n) {
				if (n != null && q("vg-bills-tag"))
					q("vg-bills-tag").innerHTML =
						"<b>" + n + "</b> " + (n === 1 ? "bill" : "bills") + " so far today";
			});
	}

	function on_workspace() {
		var r = frappe.get_route ? frappe.get_route() : [];
		return !!(r && r[0] === "Workspaces" && r[1]);
	}

	function try_inject(n) {
		if (!on_workspace()) return;
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
			var who = persona();
			var wrap = build(who);
			target.parentNode.insertBefore(wrap, target);
			fill(wrap, who);
			return;
		}
		if (n > 0) setTimeout(function () { try_inject(n - 1); }, 200);
	}

	// Always tear the banner down first. Workspace-to-workspace navigation
	// re-renders the editor in place, which destroys an already-injected
	// banner — and the "already exists" guard in try_inject would then stop it
	// coming back. Dropping it here means every render re-injects cleanly.
	function handle() {
		var e = document.getElementById("vac-greet-wrap");
		if (e) e.remove();
		if (on_workspace()) try_inject(50);
	}

	if (frappe.router && frappe.router.on) frappe.router.on("change", handle);
	$(document).on("page-change", handle);
	handle();
})();
