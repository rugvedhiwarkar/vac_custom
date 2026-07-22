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
    if (vt === 'Employee Advance' || vt === 'Interparty Expense') return ['party', 'mode', 'from_account', 'amount'];
    if (vt === 'Expense') return ['mode', 'from_account', 'to_account', 'amount'];
    return ['from_account', 'to_account', 'amount']; // Contra / Journal
  }

  // display label -> backend vtype code (spaces -> underscore): 'Employee Advance' -> 'employee_advance'
  function fv_code(vt) { return (vt || '').toLowerCase().replace(/ /g, '_'); }

  // interparty: the recoverable head configured for a related-party customer (from cfg map)
  function fv_ip_head(d, party) {
    if (!party) return null;
    var rows = (d.cfg.interparty_parties || []).filter(function (p) { return p.party === party; });
    return rows.length ? rows[0].account : null;
  }

  /* Party-type support (Customer / Supplier / Employee / Shareholder).
   * Gated on cfg.party_types from fast_voucher_config: absent -> the selector
   * never renders and the payload carries no party_type, i.e. the original
   * fixed Payment=Supplier / Receipt=Customer behaviour (prod stays inert
   * until its config + post scripts are promoted). */
  function fv_pt_enabled(cfg) { return !!(cfg.party_types && cfg.party_types.length); }

  function fv_pt_default(vt) { return vt === 'Receipt' ? 'Customer' : 'Supplier'; }

  // DOM-first: the select's DOM value reflects the user's pick instantly, while
  // the model value updates through an async set_value chain (and a v16 refresh
  // can even reset it to df.default mid-pass — see fv_toggle).
  function fv_pt_current(d) {
    var vt = d.get_value('vtype') || 'Payment';
    if (!fv_pt_enabled(d.cfg)) return fv_pt_default(vt);
    var f = d.fields_dict.party_type;
    var v = (f && f.$input && f.$input.val()) || d.get_value('party_type');
    return v || fv_pt_default(vt);
  }

  function fv_pt_req_at(d) {
    var pt = fv_pt_current(d);
    var rows = (d.cfg.party_types || []).filter(function (r) { return r.party_type === pt; });
    return rows.length ? rows[0].account_type : null;
  }

  // Party-side account the server will use (for the Dr/Cr preview); null means
  // the type has no default and the dialog must collect an explicit pick.
  function fv_party_default_acct(d, pt) {
    var cfg = d.cfg;
    if (!fv_pt_enabled(cfg)) return (d.get_value('vtype') === 'Receipt') ? cfg.receivable : cfg.payable;
    return (cfg.party_defaults || {})[pt] || null;
  }

  // v16 (verified in the desk console 2026-07-16): set_df_property('hidden', ...)
  // refreshes the control even when the flag did not change, and a refreshed
  // Select RESETS to df.default — flipping both DOM and model mid-pass. Only
  // touch hidden when it actually changes.
  function fv_toggle(d, fn, show) {
    var f = d.fields_dict[fn];
    if (f && !f.df.hidden === !!show) return;
    d.set_df_property(fn, 'hidden', show ? 0 : 1);
  }

  function fv_party_acct_query(d) {
    var f = { company: 'Vijay Agro Centre', is_group: 0, disabled: 0 };
    var at = fv_pt_req_at(d);
    if (at) f.account_type = at;
    return { filters: f };
  }

  function fv_party_apply(d) {
    var vt = d.get_value('vtype') || 'Payment';
    var on = vt === 'Payment' || vt === 'Receipt';
    var ptOn = on && fv_pt_enabled(d.cfg);
    var pt = fv_pt_current(d);  // computed ONCE; threaded through the whole pass
    fv_toggle(d, 'party_type', ptOn);
    d.set_df_property('party', 'label', pt);
    d.set_df_property('party', 'options', pt);
    var needAcct = ptOn && !fv_party_default_acct(d, pt);
    fv_toggle(d, 'party_account', needAcct);
    d.set_df_property('party_account', 'label', pt + ' account');
    if (d.fields_dict.party.refresh) d.fields_dict.party.refresh();
    if (ptOn) fv_pt_wire(d, pt);
  }

  /* v16 quirk (verified on staging 2026-07-16): a dialog Select created with
   * hidden:1 renders NO <option>s — set_options() caches last_options before
   * the input exists, then every later call early-returns as "unchanged". And
   * hidden fields have no $input at dialog-creation time, so change handlers
   * bound there never attach. So wire options + handlers HERE, after
   * set_df_property('hidden', 0) has made the inputs (that part is sync). */
  function fv_pt_wire(d, pt) {
    var ptf = d.fields_dict.party_type;
    if (ptf && ptf.$input) {
      if (ptf.set_options && !ptf.$input.find('option').length) {
        ptf.last_options = null;
        ptf.set_options();
      }
      d.set_value('party_type', pt);  // sync model + display now that options exist
      ptf.$input.off('change.fvpt').on('change.fvpt', function () {
        d.set_value('party', ''); d.set_value('party_account', '');
        fv_party_apply(d); fv_bind_enter(d); fv_preview(d);
        var p = d.fields_dict.party;
        setTimeout(function () { if (p && p.$input) p.$input.focus(); }, 80);
      });
    }
    var paf = d.fields_dict.party_account;
    if (paf && paf.$input) {
      paf.$input.off('change.fvpt').on('change.fvpt', function () { fv_bind_enter(d); fv_preview(d); });
    }
  }

  function fv_acct_query(d, fieldname) {
    var vt = d.get_value('vtype') || 'Payment';
    var f = { company: 'Vijay Agro Centre', is_group: 0, disabled: 0 };
    f.name = ['not in', ['Suspense Account - Unaccounted Cash - VAC', 'Cash - VAC', 'Debtors - VAC', 'Creditors - VAC']];
    if (vt === 'Payment' || vt === 'Receipt' || vt === 'Contra'
        || vt === 'Employee Advance' || vt === 'Interparty Expense') {
      f.account_type = ['in', ['Cash', 'Bank']];  // drawer only
      f.root_type = 'Asset';
    } else if (vt === 'Expense') {
      if (fieldname === 'from_account') { f.account_type = ['in', ['Cash', 'Bank']]; f.root_type = 'Asset'; }
      else { f.root_type = 'Expense'; }  // to_account = ANY P&L expense head, incl. accounts made later
    } else {
      f.account_type = ['not in', ['Tax', 'Receivable', 'Payable']];  // Journal
    }
    return { filters: f };
  }

  // party Link filter: Interparty limits the picker to the configured related parties
  function fv_party_link_query(d) {
    if (d.get_value('vtype') === 'Interparty Expense') {
      var names = (d.cfg.interparty_parties || []).map(function (p) { return p.party; });
      return { filters: { name: ['in', names.length ? names : ['__none__']] } };
    }
    return {};
  }

  function fv_relayout(d) {
    var vt = d.get_value('vtype') || 'Payment';
    var pr = (vt === 'Payment' || vt === 'Receipt');
    var show = function (fn, on) { d.set_df_property(fn, 'hidden', on ? 0 : 1); };
    d.set_value('party', '');
    d.set_value('party_account', '');
    if (fv_pt_enabled(d.cfg) && pr) {
      var ptf0 = d.fields_dict.party_type;
      if (ptf0 && ptf0.$input) ptf0.$input.val(fv_pt_default(vt));  // DOM now — set_value lands async
      d.set_value('party_type', fv_pt_default(vt));
    }
    ['party', 'party_type', 'party_account', 'mode', 'from_account', 'to_account'].forEach(function (fn) { show(fn, false); });
    if (vt === 'Payment') {
      show('party', true); show('mode', true); show('from_account', true);
      d.set_df_property('from_account', 'label', 'Paid from (drawer)');
    } else if (vt === 'Receipt') {
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
    } else if (vt === 'Expense') {
      show('mode', true); show('from_account', true); show('to_account', true);
      d.set_df_property('from_account', 'label', 'Paid from (drawer)');
      d.set_df_property('to_account', 'label', 'Expense head');
    } else if (vt === 'Employee Advance') {
      show('party', true); show('mode', true); show('from_account', true);
      d.set_df_property('party', 'label', 'Employee');
      d.set_df_property('party', 'options', 'Employee');
      d.set_df_property('from_account', 'label', 'Paid from (drawer)');
    } else if (vt === 'Interparty Expense') {
      show('party', true); show('mode', true); show('from_account', true);
      d.set_df_property('party', 'label', 'Related party');
      d.set_df_property('party', 'options', 'Customer');
      d.set_df_property('from_account', 'label', 'Paid from (drawer)');
    } else {
      show('from_account', true); show('to_account', true);
      d.set_df_property('from_account', 'label', 'From');
      d.set_df_property('to_account', 'label', 'To');
    }
    if (pr) fv_party_apply(d);
    else if (d.fields_dict.party.refresh) d.fields_dict.party.refresh();  // apply new options/get_query
    fv_ref_toggle(d);
    fv_bind_enter(d);
    fv_preview(d);
  }

  function fv_ref_toggle(d) {
    var vt = d.get_value('vtype') || 'Payment';
    var acct = null;
    if (vt === 'Payment' || vt === 'Employee Advance' || vt === 'Interparty Expense') acct = d.get_value('from_account');
    else if (vt === 'Receipt') acct = d.get_value('to_account');
    var dt = d.drawerType || {};
    var isBank = acct && dt[acct] === 'Bank';
    if (d.fields_dict.reference_no) {
      d.set_df_property('reference_no', 'hidden', isBank ? 0 : 1);
      // never carry a bank ref (UTR/cheque) onto a cash voucher after switching drawer
      if (!isBank && d.get_value('reference_no')) d.set_value('reference_no', '');
    }
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

  /* Party-side account the SERVER will actually use, resolved per party so the
   * Dr/Cr line shows that party's OWN head (e.g. "Dealerships Payables - VAC")
   * instead of the generic global default. Cached per (type, party); if the
   * endpoint is absent on a site it degrades silently to the global default. */
  function fv_fetch_party_acct(d, pt, party) {
    if (!pt || !party) return;
    var key = pt + '::' + party;
    if (!d.__pacct) d.__pacct = {};
    if (key in d.__pacct) { fv_preview(d); return; }
    d.__pacct[key] = null;  // in-flight
    frappe.call({
      method: 'fast_voucher_party_account', args: { party_type: pt, party: party },
      callback: function (r) { d.__pacct[key] = (r && r.message) || false; fv_preview(d); },
      error: function () { d.__pacct[key] = false; fv_preview(d); }
    });
  }

  function fv_party_acct_resolved(d, pt, party) {
    if (!pt || !party) return null;
    var v = (d.__pacct || {})[pt + '::' + party];
    return (v && typeof v === 'string') ? v : null;
  }

  function fv_bind_enter(d) {
    ['party', 'party_account', 'mode', 'from_account', 'to_account', 'reference_no', 'amount', 'remark'].forEach(function (fn) {
      var fd = d.fields_dict[fn];
      if (fd && fd.$input) fd.$input.off('keydown.fv');
    });
    var flow = fv_flow(d.get_value('vtype') || 'Payment');
    if (d.fields_dict.party_account && !d.fields_dict.party_account.df.hidden) {
      var pi = flow.indexOf('party');
      if (pi >= 0) flow.splice(pi + 1, 0, 'party_account');
    }
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
    var vt = d.get_value('vtype');
    var from = d.get_value('from_account'), to = d.get_value('to_account');
    var pt0 = fv_pt_current(d), pty = d.get_value('party');
    var pacc = d.get_value('party_account')
      || fv_party_acct_resolved(d, pt0, pty)
      || fv_party_default_acct(d, pt0) || '(party account)';
    if (vt === 'Payment') return { cr: from || '(drawer)', dr: pacc };
    if (vt === 'Receipt') return { cr: pacc, dr: to || '(drawer)' };
    if (vt === 'Expense') return { cr: from || '(drawer)', dr: to || '(expense head)' };
    if (vt === 'Employee Advance') return { cr: from || '(drawer)', dr: (d.cfg.employee_advance_account || 'Employee Advances - VAC') };
    if (vt === 'Interparty Expense') return { cr: from || '(drawer)', dr: fv_ip_head(d, d.get_value('party')) || '(recoverable head)' };
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
    var vt = d.get_value('vtype');  // party_type stays sticky for batch entry
    ['party', 'party_account', 'mode', 'from_account', 'to_account', 'reference_no', 'amount', 'remark'].forEach(function (fn) { d.set_value(fn, ''); });
    d.__bal = {};  // posting changed balances — refetch on next selection
    var first = d.fields_dict[fv_flow(vt)[0]];
    setTimeout(function () { if (first && first.$input) first.$input.focus(); }, 150);
    fv_preview(d);
  }

  function fv_submit(d, cfg) {
    if (d.__posting) return;  // reentrancy guard: a second Enter / key-repeat must not double-post
    var vt = fv_code(d.get_value('vtype'));
    var amt = flt(d.get_value('amount'));
    if (!amt || amt <= 0) { frappe.show_alert({ message: 'Amount must be greater than zero', indicator: 'red' }); return; }
    var payload = { vtype: vt, amount: amt, remark: d.get_value('remark') || '', posting_date: d.get_value('posting_date') || frappe.datetime.get_today(), reference_no: d.get_value('reference_no') || '' };
    if (vt === 'payment' || vt === 'receipt') {
      var pt = fv_pt_current(d);
      payload.party = d.get_value('party');
      if (!payload.party) { frappe.show_alert({ message: pt + ' is required', indicator: 'red' }); return; }
      if (vt === 'payment') {
        payload.from_account = d.get_value('from_account');
        if (!payload.from_account) { frappe.show_alert({ message: 'Drawer is required', indicator: 'red' }); return; }
      } else {
        payload.to_account = d.get_value('to_account');
        if (!payload.to_account) { frappe.show_alert({ message: 'Drawer is required', indicator: 'red' }); return; }
      }
      if (fv_pt_enabled(cfg)) {
        payload.party_type = pt;
        var pacc = d.get_value('party_account');
        if (pacc) payload.party_account = pacc;
        if (!pacc && d.fields_dict.party_account && !d.fields_dict.party_account.df.hidden) {
          frappe.show_alert({ message: 'Pick the ' + pt + ' account', indicator: 'red' }); return;
        }
      }
    } else if (vt === 'employee_advance' || vt === 'interparty_expense') {
      payload.party = d.get_value('party');
      payload.from_account = d.get_value('from_account');
      var plabel = (vt === 'employee_advance') ? 'Employee' : 'Related party';
      if (!payload.party) { frappe.show_alert({ message: plabel + ' is required', indicator: 'red' }); return; }
      if (!payload.from_account) { frappe.show_alert({ message: 'Drawer is required', indicator: 'red' }); return; }
    } else if (vt === 'expense') {
      payload.from_account = d.get_value('from_account'); payload.to_account = d.get_value('to_account');
      if (!payload.from_account) { frappe.show_alert({ message: 'Drawer is required', indicator: 'red' }); return; }
      if (!payload.to_account) { frappe.show_alert({ message: 'Expense head is required', indicator: 'red' }); return; }
    } else {
      payload.from_account = d.get_value('from_account'); payload.to_account = d.get_value('to_account');
      if (!payload.from_account || !payload.to_account) { frappe.show_alert({ message: 'Both accounts are required', indicator: 'red' }); return; }
    }
    var doPost = function () {
      d.__posting = true;  // set BEFORE the async call so a second Enter is blocked at fv_submit
      if (d.disable_primary_action) d.disable_primary_action();
      frappe.call({
        method: 'fast_voucher_post', args: payload,
        callback: function (r) {
          d.__posting = false;
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
        error: function () { d.__posting = false; if (d.enable_primary_action) d.enable_primary_action(); }
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
    var ptNames = (cfg.party_types || []).map(function (p) { return p.party_type; });
    var d = new frappe.ui.Dialog({
      title: '⚡ Fast Journal',
      fields: [
        { fieldname: 'vtype', fieldtype: 'Select', label: 'Type', reqd: 1, options: ['Payment', 'Receipt', 'Contra', 'Journal'].concat(cfg.extra_types || []).join('\n'), default: 'Payment' },
        { fieldname: 'party_type', fieldtype: 'Select', label: 'Party type', options: ptNames.join('\n'), default: ptNames.length ? 'Supplier' : '', hidden: 1 },
        { fieldname: 'party', fieldtype: 'Link', label: 'Supplier', options: 'Supplier', get_query: function () { return fv_party_link_query(d); } },
        { fieldname: 'party_account', fieldtype: 'Link', label: 'Party account', options: 'Account', hidden: 1, get_query: function () { return fv_party_acct_query(d); } },
        { fieldname: 'mode', fieldtype: 'Select', label: 'Mode (fills drawer)', options: [''].concat(modeNames).join('\n') },
        { fieldname: 'from_account', fieldtype: 'Link', label: 'From', options: 'Account', get_query: function () { return fv_acct_query(d, 'from_account'); } },
        { fieldname: 'to_account', fieldtype: 'Link', label: 'To', options: 'Account', get_query: function () { return fv_acct_query(d, 'to_account'); } },
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
    // party_type / party_account handlers are wired in fv_pt_wire — their
    // inputs do not exist yet here (created hidden, made lazily on unhide).
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
    if (d.fields_dict.party.$input) d.fields_dict.party.$input.on('change', function () {
      fv_ref_toggle(d); fv_bind_enter(d);
      fv_fetch_party_acct(d, fv_pt_current(d), d.get_value('party'));  // preview the party's OWN head
      fv_preview(d);
    });
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
