// vac_wa — WhatsApp send helper for VAC bill formats. CANONICAL SOURCE lives
// in custom_doctypes/print_formats/vac_wa_helper.js; it is embedded verbatim
// into BOTH agriops_suite/public/js/vac_pos_print.js and the "VAC Print
// Buttons - Sales Invoice" Client Script (idempotent guard below). Flow:
// render PDF (authed) -> attach as PUBLIC file on the doc (guests can open
// /files/) -> wa.me deep link with the bill summary + PDF link.
window.vac_wa = window.vac_wa || {
	formats: ["VAC Tax Invoice A4", "VAC Tax Invoice A5", "VAC Delivery Slip"],
	norm(ph) {
		ph = (ph || "").replace(/\D/g, "");
		if (ph.length === 10) ph = "91" + ph;
		return ph;
	},
	async pdf_link(doctype, name, fmt) {
// Public so the (logged-out) WhatsApp recipient can open it — but the URL must
		// NOT be guessable from the sequential invoice number, or other customers'
		// bills could be enumerated. Put a random token in the filename; the LIKE
		// lookup below reuses the existing file on re-share (no duplicate pile-up).
		const base = (name + " " + fmt).replace(/[^\w\- .]/g, "");
		const ex = await frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "File",
				filters: { attached_to_doctype: doctype, attached_to_name: name,
					file_name: ["like", base + " %.pdf"], is_private: 0 },
				fields: ["file_url"], limit_page_length: 1,
			},
		});
		if (ex.message && ex.message.length) {
			return frappe.urllib.get_full_url(ex.message[0].file_url);
		}
		const token = (self.crypto && crypto.randomUUID)
			? crypto.randomUUID().replace(/-/g, "")
			: (Date.now().toString(36) + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2));
		const fname = base + " " + token + ".pdf";
		const pdf = await fetch(frappe.urllib.get_full_url(
			`/api/method/frappe.utils.print_format.download_pdf?doctype=${encodeURIComponent(doctype)}` +
			`&name=${encodeURIComponent(name)}&format=${encodeURIComponent(fmt)}&no_letterhead=1`));
		if (!pdf.ok) throw new Error("pdf render failed");
		const fd = new FormData();
		fd.append("file", await pdf.blob(), fname);
		fd.append("doctype", doctype);
		fd.append("docname", name);
		fd.append("is_private", "0");
		const up = await fetch("/api/method/upload_file", {
			method: "POST", headers: { "X-Frappe-CSRF-Token": frappe.csrf_token }, body: fd,
		});
		const j = await up.json();
		if (!j.message || !j.message.file_url) throw new Error("upload failed");
		return frappe.urllib.get_full_url(j.message.file_url);
	},
	async send_dialog(doc) {
		const me = window.vac_wa;
		const cm = doc.contact_mobile ||
			(((await frappe.db.get_value("Customer", doc.customer, "mobile_no")).message || {}).mobile_no) || "";
		const users = (((await frappe.call({
			method: "frappe.client.get_list",
			args: { doctype: "User", filters: { enabled: 1, user_type: "System User" },
				fields: ["full_name", "mobile_no"], limit_page_length: 0 },
		})).message) || []).filter((u) => u.mobile_no);
		const opts = [`Customer — ${doc.customer_name || doc.customer}`]
			.concat(users.map((u) => `${u.full_name} (${u.mobile_no})`))
			.concat(["Other number"]);
		const d = new frappe.ui.Dialog({
			title: __("Send on WhatsApp"),
			fields: [
				{ fieldname: "to", label: __("Send to"), fieldtype: "Select",
					options: opts.join("\n"), default: opts[0],
					change: () => {
						const v = d.get_value("to");
						let n = v === "Other number" ? "" : cm;
						const m = v.match(/\(([+\d][\d ]*)\)$/);  // allow a leading + so "+91…" staff numbers match (norm() strips it)
						if (m) n = m[1];
						d.set_value("number", n);
					} },
				{ fieldname: "number", label: __("Mobile Number"), fieldtype: "Data",
					default: cm, description: __("10 digits, or with country code") },
				{ fieldname: "fmt", label: __("Document"), fieldtype: "Select",
					options: me.formats.join("\n"), default: me.formats[0] },
			],
			primary_action_label: __("Open WhatsApp"),
			primary_action: async (v) => {
				const n = me.norm(v.number);
				if (n.length < 11) { frappe.msgprint(__("Enter a valid mobile number")); return; }
				d.get_primary_btn().prop("disabled", true);
				try {
					const link = await me.pdf_link(doc.doctype, doc.name, v.fmt);
					const label = v.fmt.indexOf("Delivery") >= 0 ? "Delivery Note" : "Bill";
					const msg = ["*Vijay Agro Centre, Sihora*",
						`${label} ${doc.name} | ${frappe.datetime.str_to_user(doc.posting_date)}`,
						`Amount: Rs ${format_number(doc.rounded_total || doc.grand_total, null, 2)}`,
						"", `${label} PDF: ${link}`, "", "Contact: 9881527395"].join("\n");
					window.open(`https://wa.me/${n}?text=${encodeURIComponent(msg)}`, "_blank");
					d.hide();
				} catch (e) {
					console.error("vac_wa:", e);
					frappe.msgprint(__("Could not prepare the PDF link"));
				} finally {
					d.get_primary_btn().prop("disabled", false);
				}
			},
		});
		d.show();
	},
};

// vac_pos_print: extra buttons on the POS order-summary screen (post-checkout
// AND Recent Orders): Invoice A4, Delivery Slip, WhatsApp. Print Receipt stays
// the stock button (POS Profiles point it at "VAC Tax Invoice A5").
(function () {
	const LETTERHEAD = "Blank (VAC Bill Formats)";
	const PRINT_BUTTONS = [
		["Invoice A4", "VAC Tax Invoice A4"],
		["Delivery Slip", "VAC Delivery Slip"],
	];
	function patch() {
		const cls = window.erpnext?.PointOfSale?.PastOrderSummary;
		if (!cls) return false;
		if (cls.__vac_print_patched) return true;
		cls.__vac_print_patched = true;
		const orig = cls.prototype.load_summary_of;
		cls.prototype.load_summary_of = function (...args) {
			orig.apply(this, args);
			try {
				if (!this.$summary_btns || !this.doc || this.doc.docstatus !== 1) return;
				this.$summary_btns.find(".vac-extra-print").remove();
				PRINT_BUTTONS.forEach(([label, fmt]) => {
					const $b = $(`<div class="summary-btn btn btn-default vac-extra-print">${__(label)}</div>`);
					$b.on("click", () => frappe.utils.print(this.doc.doctype, this.doc.name, fmt, LETTERHEAD));
					this.$summary_btns.append($b);
				});
				const $wa = $(`<div class="summary-btn btn btn-default vac-extra-print">${__("WhatsApp")}</div>`);
				$wa.on("click", () => window.vac_wa.send_dialog(this.doc));
				this.$summary_btns.append($wa);
			} catch (e) {
				console.warn("vac_pos_print: button injection failed", e);
			}
		};
		return true;
	}
	function arm() {
		if (patch()) return;
		const timer = setInterval(() => { if (patch()) clearInterval(timer); }, 800);
		setTimeout(() => clearInterval(timer), 30000);
	}
	$(function () {
		if (!window.frappe) return;
		frappe.router?.on("change", () => {
			if ((frappe.get_route?.() || [])[0] === "point-of-sale") arm();
		});
		if ((frappe.get_route?.() || [])[0] === "point-of-sale") arm();
	});
})();
