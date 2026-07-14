/* Fast Journal — keyboard-first dialog that posts NATIVE Payment Entry /
 * Journal Entry for payment / receipt / contra / journal, without leaving the
 * current screen. Exposed globally as window.__fast_journal_open() so it can be
 * opened from the POS header (pos_cash_desk.js), a desk button, or a shortcut.
 *
 * Backend: two API Server Scripts, fast_voucher_config (enable gate + drawers /
 * modes / threshold) and fast_voucher_post (the single write path — builds and
 * submits the native doc, with the server-side blocklist + Asset-only drawer +
 * journal control-account guards). This file is UI only; it invents no ledger.
 *
 * Self-gating: opens only where fast_voucher_config returns enabled=1, so
 * shipping this to the shared bench surfaces nothing on production until that
 * site's Server Scripts are created (staging-first). Content-hashed .bundle.js
 * so an edit busts the immutable /assets cache.
 */
(function () {
  function fv_flow(vt) {
    if (vt === 'Payment') return ['party', 'mode', 'from_account', 'amount'];
    if (vt === 'Receipt') return ['party', 'mode', 'to_account', 'amount'];
    return ['from_account', 'to_account', 'amount']; // Contra / Journal
  }

  function fv_acct_query(d) {
    var vt = d.get_value('vtype') || 'Payment';
    var f = { company: 'Vijay Agro Centre', is_group: 0, disabled: 0 };
    f.name = ['not in', ['Suspense Account - Unaccounted Cash - VAC', 'Cash - VAC', 'Debtors - VAC', 'Creditors - VAC']];
    if (vt === 'Payment' || vt === 'Receipt' || vt === 'Contra') {
      f.account_type = ['in', ['Cash', 'Bank']];
      f.root_type = 'Asset';
    } else {
      f.account_type = ['not in', ['Tax', 'Receivable', 'Payable']];
    }
    return { filters: f };
  }

  function fv_relayout(d) {
    var vt = d.get_value('vtype') || 'Payment';
    var show = function (fn, on) { d.set_df_property(fn, 'hidden', on ? 0 : 1); };
    d.set_value('party', '');
    ['party', 'mode', 'from_account', 'to_account'].forEach(function (fn) { show(fn, false); });
    if (vt === 'Payment') {
      d.set_df_property('party', 'label', 'Supplier');
      d.set_df_property('party', 'options', 'Supplier');
      show('party', true); show('mode', true); show('from_account', true);
      d.set_df_property('from_account', 'label', 'Paid from (drawer)');
    } else if (vt === 'Receipt') {
      d.set_df_property('party', 'label', 'Customer');
      d.set_df_property('party', 'options', 'Customer');
      show('party', true); show('mode', true); show('to_account', true);
      d.set_df_property('to_account', 'label', 'Deposit to (drawer)');
    } else if (vt === 'Contra') {
      show('from_account', true); show('to_account', true);
      d.set_df_property('from_account', 'label', 'From (drawer)');
      d.set_df_property('to_account', 'label', 'To (drawer)');
    } else if (vt === 'Journal') {
      show('from_account', true); show('to_account', true);
      d.set_df_property('from_account', 'label', 'Credit account');
      d.set_df_property('to_account', 'label', 'Debit account');
    } else {
      show('from_account', true); show('to_account', true);
      d.set_df_property('from_account', 'label', 'From');
      d.set_df_property('to_account', 'label', 'To');
    }
    if (d.fields_dict.party.refresh) d.fields_dict.party.refresh();
    fv_ref_toggle(d);
    fv_bind_enter(d);
    fv_preview(d);
  }

  function fv_ref_toggle(d) {
    var vt = d.get_value('vtype') || 'Payment';
    var acct = null;
    if (vt === 'Payment') acct = d.get_value('from_account');
    else if (vt === 'Receipt') acct = d.get_value('to_account');
    var dt = d.drawerType || {};
    var isBank = acct && dt[acct] === 'Bank';
    if (d.fields_dict.reference_no) d.set_df_property('reference_no', 'hidden', isBank ? 0 : 1);
  }

  // current balance of an account (read-only), cached per dialog, shown in the preview
  function fv_fetch_balance(d, acct) {
    if (!acct) return;
    if (!d.__bal) d.__bal = {};
    if (acct in d.__bal) { fv_preview(d); return; }  // already fetched or in flight
    d.__bal[acct] = null;  // in-flight marker (renders as "…")
    frappe.call({
      method: 'fast_voucher_balance',
      args: { account: acct, date: d.get_value('posting_date') || frappe.datetime.get_today() },
      callback: function (r) {
        d.__bal[acct] = (r && r.message !== null && r.message !== undefined) ? flt(r.message) : null;
        fv_preview(d);
      },
      error: function () { d.__bal[acct] = false; fv_preview(d); }  // method absent on this site — hide gracefully
    });
  }

  function fv_bind_enter(d) {
    ['party', 'mode', 'from_account', 'to_account', 'reference_no', 'amount', 'remark'].forEach(function (fn) {
      var fd = d.fields_dict[fn];
      if (fd && fd.$input) fd.$input.off('keydown.fv');
    });
    var flow = fv_flow(d.get_value('vtype') || 'Payment');
    if (d.fields_dict.reference_no && !d.fields_dict.reference_no.df.hidden) {
      var ai = flow.indexOf('amount');
      if (ai >= 0) flow.splice(ai, 0, 'reference_no');
    }
    flow.forEach(function (fn, idx) {
      var fd = d.fields_dict[fn];
      if (!fd || !fd.$input) return;
      fd.$input.on('keydown.fv', function (e) {
        if (e.which !== 13) return;
        var aw = fd.awesomplete;
        if (aw && aw.ul && aw.ul.hasAttribute('hidden') === false) return; // let it pick
        e.preventDefault();
        if (idx === flow.length - 1) { fv_submit(d, d.cfg); }
        else { var nxt = d.fields_dict[flow[idx + 1]]; if (nxt && nxt.$input) nxt.$input.focus(); }
      });
    });
  }

  function fv_sides(d) {
    var cfg = d.cfg, vt = d.get_value('vtype');
    var from = d.get_value('from_account'), to = d.get_value('to_account');
    if (vt === 'Payment') return { cr: from || '(drawer)', dr: cfg.payable };
    if (vt === 'Receipt') return { cr: cfg.receivable, dr: to || '(drawer)' };
    return { cr: from || '(from)', dr: to || '(to)' };
  }

  function fv_preview(d) {
    var cfg = d.cfg, amt = flt(d.get_value('amount')), party = d.get_value('party');
    var s = fv_sides(d);
    var warn = amt >= (cfg.amount_confirm_threshold || 100000);
    var line = 'Dr <b>' + frappe.utils.escape_html(s.dr || '?') + '</b> &nbsp;/&nbsp; Cr <b>'
      + frappe.utils.escape_html(s.cr || '?') + '</b> &nbsp;&nbsp; ' + (amt ? format_currency(amt, 'INR') : '&#8377;0');
    if (party) line += ' &nbsp;&middot;&nbsp; ' + frappe.utils.escape_html(party);
    var warnOn = warn && amt;
    if (warnOn) line += ' &nbsp;&middot;&nbsp; <b style="color:var(--red-600, #c0392b)">confirm required</b>';
    var bg = warnOn ? 'rgba(220,53,69,0.14)' : 'var(--control-bg, var(--bg-light-gray, #f4f5f6))';
    var bd = warnOn ? 'var(--red-500, #dc3545)' : 'var(--border-color, transparent)';
    // current balance of the VISIBLE from/to accounts
    var bal = d.__bal || {}, accs = [];
    var vfrom = d.get_value('from_account'), vto = d.get_value('to_account');
    if (vfrom && d.fields_dict.from_account && !d.fields_dict.from_account.df.hidden) accs.push(vfrom);
    if (vto && vto !== vfrom && d.fields_dict.to_account && !d.fields_dict.to_account.df.hidden) accs.push(vto);
    if (accs.length) {
      var parts = [];
      accs.forEach(function (a) {
        var b = bal[a];
        if (b === false) return;  // unavailable on this site — hide
        var t = (b === null || b === undefined) ? '…' : format_currency(b, 'INR');
        parts.push(frappe.utils.escape_html(a) + ': <b>' + t + '</b>');
      });
      if (parts.length) line += '<div style="margin-top:5px;font-size:12px;opacity:.8">Balance &nbsp; ' + parts.join(' &nbsp;·&nbsp; ') + '</div>';
    }
    d.fields_dict.preview.$wrapper.html(
      '<div style="padding:8px 10px;border-radius:6px;background:' + bg + ';color:var(--text-color);border:1px solid ' + bd + ';font-size:13px;line-height:1.6">' + line + '</div>');
  }

  function fv_after_post(d) {
    var vt = d.get_value('vtype');
    ['party', 'mode', 'from_account', 'to_account', 'reference_no', 'amount', 'remark'].forEach(function (fn) { d.set_value(fn, ''); });
    d.__bal = {};  // posting changed balances — refetch on next selection
    var first = d.fields_dict[fv_flow(vt)[0]];
    setTimeout(function () { if (first && first.$input) first.$input.focus(); }, 150);
    fv_preview(d);
  }

  function fv_submit(d, cfg) {
    var vt = (d.get_value('vtype') || '').toLowerCase();
    var amt = flt(d.get_value('amount'));
    if (!amt || amt <= 0) { frappe.show_alert({ message: 'Amount must be greater than zero', indicator: 'red' }); return; }
    var payload = { vtype: vt, amount: amt, remark: d.get_value('remark') || '', posting_date: d.get_value('posting_date') || frappe.datetime.get_today(), reference_no: d.get_value('reference_no') || '' };
    if (vt === 'payment') {
      payload.party = d.get_value('party'); payload.from_account = d.get_value('from_account');
      if (!payload.party) { frappe.show_alert({ message: 'Supplier is required', indicator: 'red' }); return; }
      if (!payload.from_account) { frappe.show_alert({ message: 'Drawer is required', indicator: 'red' }); return; }
    } else if (vt === 'receipt') {
      payload.party = d.get_value('party'); payload.to_account = d.get_value('to_account');
      if (!payload.party) { frappe.show_alert({ message: 'Customer is required', indicator: 'red' }); return; }
      if (!payload.to_account) { frappe.show_alert({ message: 'Drawer is required', indicator: 'red' }); return; }
    } else {
      payload.from_account = d.get_value('from_account'); payload.to_account = d.get_value('to_account');
      if (!payload.from_account || !payload.to_account) { frappe.show_alert({ message: 'Both accounts are required', indicator: 'red' }); return; }
    }
    var doPost = function () {
      if (d.disable_primary_action) d.disable_primary_action();
      frappe.call({
        method: 'fast_voucher_post', args: payload,
        callback: function (r) {
          if (d.enable_primary_action) d.enable_primary_action();
          if (r && r.message && r.message.name) {
            var m = r.message;
            frappe.show_alert({
              message: 'Posted <a href="/app/' + frappe.router.slug(m.doctype) + '/' + encodeURIComponent(m.name) + '">' + m.name + '</a>',
              indicator: 'green'
            }, 7);
            fv_after_post(d);
          }
        },
        error: function () { if (d.enable_primary_action) d.enable_primary_action(); }
      });
    };
    if (amt >= (cfg.amount_confirm_threshold || 100000)) {
      var s = fv_sides(d);
      frappe.confirm('Post ' + format_currency(amt, 'INR') + ' &mdash; Dr <b>' + s.dr + '</b> / Cr <b>' + s.cr + '</b> ?', doPost);
    } else { doPost(); }
  }

  function fv_dialog(cfg) {
    var modeMap = {}; (cfg.modes || []).forEach(function (m) { if (m.account) modeMap[m.mode] = m.account; });
    var modeNames = (cfg.modes || []).filter(function (m) { return m.account; }).map(function (m) { return m.mode; });
    var drawerType = {}; (cfg.drawers || []).forEach(function (dd) { drawerType[dd.account] = dd.type; });
    var d = new frappe.ui.Dialog({
      title: '⚡ Fast Journal',
      fields: [
        { fieldname: 'vtype', fieldtype: 'Select', label: 'Type', reqd: 1, options: ['Payment', 'Receipt', 'Contra', 'Journal'].join('\n'), default: 'Payment' },
        { fieldname: 'party', fieldtype: 'Link', label: 'Supplier', options: 'Supplier' },
        { fieldname: 'mode', fieldtype: 'Select', label: 'Mode (fills drawer)', options: [''].concat(modeNames).join('\n') },
        { fieldname: 'from_account', fieldtype: 'Link', label: 'From', options: 'Account', get_query: function () { return fv_acct_query(d); } },
        { fieldname: 'to_account', fieldtype: 'Link', label: 'To', options: 'Account', get_query: function () { return fv_acct_query(d); } },
        { fieldname: 'reference_no', fieldtype: 'Data', label: 'Ref No (UPI / cheque / UTR)', hidden: 1 },
        { fieldname: 'amount', fieldtype: 'Currency', label: 'Amount', reqd: 1 },
        { fieldname: 'remark', fieldtype: 'Data', label: 'Remark (optional)' },
        { fieldname: 'posting_date', fieldtype: 'Date', label: 'Date', default: frappe.datetime.get_today() },
        { fieldname: 'preview', fieldtype: 'HTML' }
      ],
      primary_action_label: 'Post  (Enter)',
      primary_action: function () { fv_submit(d, cfg); }
    });
    d.cfg = cfg;
    d.drawerType = drawerType;
    d.__bal = {};
    d.show();
    d.fields_dict.vtype.$input.on('change', function () { fv_relayout(d); });
    if (d.fields_dict.mode.$input) {
      d.fields_dict.mode.$input.on('change', function () {
        var acct = modeMap[d.get_value('mode')];
        if (acct) {
          if (d.get_value('vtype') === 'Receipt') d.set_value('to_account', acct); else d.set_value('from_account', acct);
          fv_ref_toggle(d); fv_bind_enter(d); fv_fetch_balance(d, acct); fv_preview(d);
        }
      });
    }
    ['from_account', 'to_account'].forEach(function (fn) {
      var fd = d.fields_dict[fn];
      if (fd && fd.$input) fd.$input.on('change', function () { fv_ref_toggle(d); fv_bind_enter(d); fv_fetch_balance(d, d.get_value(fn)); fv_preview(d); });
    });
    if (d.fields_dict.party.$input) d.fields_dict.party.$input.on('change', function () { fv_ref_toggle(d); fv_bind_enter(d); fv_preview(d); });
    if (d.fields_dict.amount.$input) d.fields_dict.amount.$input.on('change', function () { fv_preview(d); });
    setTimeout(function () {
      if (!d.get_value('vtype')) d.set_value('vtype', 'Payment');
      fv_relayout(d);
      if (d.fields_dict.vtype.$input) d.fields_dict.vtype.$input.focus();
    }, 120);
  }

  window.__fast_journal_open = function () {
    frappe.call({ method: 'fast_voucher_config' }).then(function (r) {
      var cfg = (r && r.message) || {};
      if (!cfg.enabled) { frappe.msgprint('Fast Journal is not enabled on this site.'); return; }
      fv_dialog(cfg);
    });
  };
  // back-compat alias for the existing PE/JE list Client Scripts
  window.__fast_voucher_open = window.__fast_journal_open;
})();
