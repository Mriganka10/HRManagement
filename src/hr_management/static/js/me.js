/* Employee portal: home, assistant, leave, attendance, payslips, requests, documents, policies, growth, team, profile. */
(function () {
  'use strict';
  const H = window.HRM;
  const { esc, api, toast, act, fmt, money, date, time, pill, table, bars, animateIn, formDialog, confirmDialog, options, openDrawer, closeDrawer, label } = H;
  let me = null;
  let content = null;
  const chatHistory = [];

  async function boot() {
    try { me = await api('/api/auth/me'); } catch (_) { return; }
    const nav = [
      { group: 'My work', items: [
        { path: '/', label: 'Home', icon: 'home' }, { path: '/assistant', label: 'HR assistant', icon: 'spark' },
        { path: '/leave', label: 'Leave', icon: 'calendar' }, { path: '/attendance', label: 'Attendance', icon: 'clock' },
        { path: '/payslips', label: 'Payslips', icon: 'wallet' }, { path: '/requests', label: 'HR requests', icon: 'inbox' }] },
      { group: 'Me', items: [
        { path: '/profile', label: 'Profile', icon: 'user' }, { path: '/documents', label: 'Documents', icon: 'doc' },
        { path: '/growth', label: 'Growth', icon: 'growth' }, { path: '/policies', label: 'Policies', icon: 'book' }] },
    ];
    if (me.is_manager) nav[0].items.push({ path: '/team', label: 'My team', icon: 'team' });
    if (me.is_hr) nav.push({ group: 'HR', items: [{ path: '/hr-portal', label: 'Open HR portal', icon: 'shield' }] });
    content = H.shell({ nav, me, subtitle: `${me.user_id}${me.employee ? ` – ${me.employee.designation}` : ''}`, onNotifications: showNotifications });
    refreshBell();
    H.router([
      { path: '/', view: home }, { path: '/assistant', view: assistant }, { path: '/leave', view: leave },
      { path: '/attendance', view: attendance }, { path: '/payslips', view: payslips }, { path: '/requests', view: requests },
      { path: '/requests/:id', view: requestDetail }, { path: '/profile', view: profile }, { path: '/documents', view: documents },
      { path: '/growth', view: growth }, { path: '/policies', view: policies }, { path: '/team', view: team },
      { path: '/hr-portal', view: () => { window.location.href = '/hr'; } },
    ], '#/');
  }

  async function refreshBell() {
    try {
      const n = await api('/api/me/notifications');
      const bell = document.getElementById('bell');
      bell.querySelector('.dot')?.remove();
      if (n.unread) bell.insertAdjacentHTML('beforeend', '<span class="dot"></span>');
    } catch (_) { /* ignore */ }
  }

  async function showNotifications() {
    const n = await api('/api/me/notifications');
    openDrawer(`<div class="drawer-head"><h2>Notifications</h2><button class="btn ghost small" data-close>Close</button></div>
      <div class="drawer-body"><ul class="notice-list">${n.notifications.map((x) => `<li class="${x.is_read ? '' : 'unread'}"><b>${esc(x.title)}</b>
        <div class="muted">${esc(x.body)}</div><div class="spread"><span class="faint">${date(x.created_at, true)}</span>${x.link ? `<a href="${esc(x.link)}" data-go>Open</a>` : ''}</div></li>`).join('') || '<li class="empty">No notifications yet.</li>'}</ul></div>`);
    document.querySelectorAll('[data-go]').forEach((a) => a.addEventListener('click', () => closeDrawer()));
    await api('/api/me/notifications/read', { method: 'POST' });
    refreshBell();
  }

  const view = (title, path, html) => { H.setPage(title, path); content.innerHTML = html; animateIn(content); };
  const loading = (title, path) => view(title, path, '<div class="empty">Loading…</div>');

  // ---------------------------------------------------------------- home
  async function home() {
    loading('Home', '/');
    const d = await api('/api/me/home');
    const p = d.profile;
    const hour = new Date().getHours();
    const greet = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
    view('Home', '/', `
      <div class="spread"><div><h2>${greet}, ${esc(p.full_name.split(' ')[0])}</h2><p class="muted" style="margin:.3rem 0 0">${esc(p.designation)}, ${esc(p.department || 'Kairoz')} – reports to ${esc(p.manager_name || 'HR')}</p></div>
        <a class="btn" href="#/assistant">${H.icon('spark')} Ask the HR assistant</a></div>
      <div class="grid-3">
        <div class="clock-card"><svg class="hourglass" width="70" height="90" viewBox="0 0 40 52" fill="none" stroke="#fff" stroke-width="2.5"><path d="M6 3h28M6 49h28M9 3c0 12 22 14 22 23S9 37 9 49M31 3c0 12-22 14-22 23s22 11 22 23"/></svg>
          <span class="faint" id="today-date"></span><div class="time" id="clock">--:--</div>
          <div id="check-state"></div><div class="row" id="check-actions"></div></div>
        <div class="panel"><div class="spread"><h3>Leave balance</h3><a href="#/leave">Apply</a></div>
          <div class="stack" style="margin-top:12px">${d.balances.filter((b) => b.paid).slice(0, 4).map((b) => `<div class="spread"><span>${esc(b.name)}</span><b class="num">${fmt(b.available)} <span class="faint">/ ${fmt(b.entitled)}</span></b></div>`).join('')}</div></div>
        <div class="panel"><h3>This month</h3>
          <div class="stack" style="margin-top:12px">${[['Present', d.month.present + d.month.late], ['Late', d.month.late], ['On leave', d.month.on_leave], ['Absent', d.month.absent]].map(([k, v]) => `<div class="spread"><span>${k}</span><b class="num">${v}</b></div>`).join('')}</div></div>
      </div>
      <div class="grid-2">
        <div class="panel"><h3>Waiting on others</h3>
          ${d.my_pending_leave.length || d.open_requests.length ? `<ul class="notice-list" style="margin-top:8px">
            ${d.my_pending_leave.map((l) => `<li><b>${esc(l.leave_name)}</b> ${date(l.start_date)}${l.end_date !== l.start_date ? ` – ${date(l.end_date)}` : ''} <span class="faint">with ${esc(l.approver_name || 'HR')}</span></li>`).join('')}
            ${d.open_requests.map((r) => `<li><a href="#/requests/${r.id}">${esc(r.ref)}</a> ${esc(r.subject)} ${pill(r.status)}</li>`).join('')}</ul>` : '<div class="empty">Nothing pending.</div>'}
          ${d.team_pending ? `<p style="margin-top:12px"><a class="btn small" href="#/team">Review ${d.team_pending} team leave request(s)</a></p>` : ''}</div>
        <div class="panel"><h3>Coming up</h3><ul class="notice-list" style="margin-top:8px">
          ${d.latest_payslip ? `<li>Latest payslip <b>${esc(d.latest_payslip.period)}</b>: ${money(d.latest_payslip.net_pay)} <a href="#/payslips">View</a></li>` : ''}
          ${d.holidays.map((h) => `<li>${pill('holiday', 'Holiday')} <b>${esc(h.name)}</b> <span class="faint">${date(h.holiday_date)}</span></li>`).join('') || '<li class="faint">No upcoming holidays.</li>'}
          ${p.status === 'probation' && p.probation_end ? `<li>${pill('probation')} Probation ends <b>${date(p.probation_end)}</b></li>` : ''}</ul></div>
      </div>`);
    clockWidget(d.today, d.is_working_day);
  }

  let clockTimer = null;
  function clockWidget(today, workingDay) {
    clearInterval(clockTimer);
    const tick = () => {
      const now = new Date();
      const node = document.getElementById('clock');
      if (!node) { clearInterval(clockTimer); return; }
      node.textContent = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
      document.getElementById('today-date').textContent = now.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' });
    };
    tick();
    clockTimer = setInterval(tick, 15000);
    const state = document.getElementById('check-state');
    const actions = document.getElementById('check-actions');
    if (!workingDay) { state.innerHTML = '<span class="faint">No check-in needed today.</span>'; return; }
    if (today && today.status === 'on_leave') { state.innerHTML = 'You are on leave today.'; return; }
    if (!today || !today.check_in) {
      state.innerHTML = '<span class="faint">You have not checked in yet.</span>';
      actions.innerHTML = '<button class="btn mint" id="check-in">Check in</button>';
      document.getElementById('check-in').addEventListener('click', async (e) => {
        const r = await act(e.currentTarget, 'Checking in…', () => api('/api/me/attendance/check-in', { method: 'POST' }));
        if (r) { toast(`Checked in at ${time(r.today.check_in)}${r.today.status === 'late' ? ' (late)' : ''}.`, 'ok'); clockWidget(r.today, true); }
      });
    } else if (!today.check_out) {
      state.innerHTML = `Checked in at <b>${time(today.check_in)}</b> ${today.status === 'late' ? pill('late') : ''}`;
      actions.innerHTML = '<button class="btn ghost" id="check-out">Check out</button>';
      document.getElementById('check-out').addEventListener('click', async (e) => {
        const r = await act(e.currentTarget, 'Checking out…', () => api('/api/me/attendance/check-out', { method: 'POST' }));
        if (r) { toast(`Checked out at ${time(r.today.check_out)}.`, 'ok'); clockWidget(r.today, true); }
      });
    } else {
      state.innerHTML = `Done for today: <b>${time(today.check_in)}</b> – <b>${time(today.check_out)}</b>`;
    }
  }

  // ---------------------------------------------------------------- assistant
  function assistant() {
    view('HR assistant', '/assistant', `
      <div class="chat"><div class="chat-log" id="log" aria-live="polite"></div>
        <form class="chat-input" id="chat-form"><input class="input" id="msg" placeholder="Ask about leave, payslips, policies, or ask me to raise a request…" autocomplete="off" maxlength="1000">
          <button class="btn" type="submit">Send</button></form></div>`);
    const log = document.getElementById('log');
    if (!chatHistory.length) {
      pushBot({ reply: `Hi ${me.full_name.split(' ')[0]}! I know your leave balances, payslips, requests and company policies, and I can act for you — I always ask before changing anything.`,
        suggestions: ['How many leaves do I have left?', 'Apply casual leave next Monday', 'Explain my last payslip', 'What is the reimbursement policy?', 'I need an employment certificate'] });
    } else chatHistory.forEach((m) => renderMsg(m));
    function renderMsg(m) {
      const node = document.createElement('div');
      node.className = `msg ${m.role}`;
      if (m.role === 'user') { node.textContent = m.text; log.appendChild(node); log.scrollTop = log.scrollHeight; return node; }
      const r = m.data;
      node.innerHTML = `<div>${esc(r.reply)}</div>${(r.cards || []).map((c) => {
        if (c.type === 'table') return `<table class="data"><thead><tr>${c.columns.map((x) => `<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${c.rows.map((row) => `<tr>${row.map((v) => `<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
        if (c.type === 'list') return `<ul>${c.items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`;
        if (c.type === 'link') return `<p style="margin:.5rem 0 0"><a href="${esc(c.href)}" target="_blank" rel="noopener">${esc(c.label)}</a></p>`;
        return '';
      }).join('')}${r.action && !m.done ? `<div class="action-card"><button class="btn small" data-confirm>${esc(r.action.label)}</button><button class="btn ghost small" data-cancel>Not now</button></div>` : ''}
      ${(r.suggestions || []).length ? `<div class="suggestions" style="margin-top:10px">${r.suggestions.map((s) => `<button type="button">${esc(s)}</button>`).join('')}</div>` : ''}`;
      node.querySelectorAll('.suggestions button').forEach((b) => b.addEventListener('click', () => send(b.textContent)));
      const ok = node.querySelector('[data-confirm]');
      if (ok) {
        ok.addEventListener('click', async () => {
          const res = await act(ok, 'Working…', () => api('/api/me/assistant/confirm', { json: { action: r.action } }));
          m.done = true;
          node.querySelector('.action-card').remove();
          if (res) { pushBot({ reply: res.reply }); refreshBell(); }
        });
        node.querySelector('[data-cancel]').addEventListener('click', () => { m.done = true; node.querySelector('.action-card').remove(); pushBot({ reply: 'Okay, I have not changed anything.' }); });
      }
      log.appendChild(node);
      log.scrollTop = log.scrollHeight;
      return node;
    }
    function pushBot(data) { const m = { role: 'bot', data, text: data.reply }; chatHistory.push(m); renderMsg(m); }
    async function send(text) {
      text = (text || '').trim();
      if (!text) return;
      const m = { role: 'user', text };
      chatHistory.push(m);
      renderMsg(m);
      const typing = document.createElement('div');
      typing.className = 'msg bot typing';
      typing.innerHTML = '<i></i><i></i><i></i>';
      log.appendChild(typing);
      log.scrollTop = log.scrollHeight;
      try {
        const data = await api('/api/me/assistant', { json: { message: text, history: chatHistory.slice(-10).map((x) => ({ role: x.role, text: x.text })) } });
        typing.remove();
        pushBot(data);
      } catch (error) { typing.remove(); pushBot({ reply: error.message }); }
    }
    document.getElementById('chat-form').addEventListener('submit', (e) => { e.preventDefault(); const input = document.getElementById('msg'); send(input.value); input.value = ''; });
    document.getElementById('msg').focus();
  }

  // ---------------------------------------------------------------- leave
  async function leave() {
    loading('Leave', '/leave');
    const d = await api('/api/me/leave');
    view('Leave', '/leave', `
      <div class="balance-grid">${d.balances.map((b) => `<div class="balance"><span class="faint">${esc(b.name)}</span><b class="num">${fmt(b.available)}</b>
        <span class="faint">of ${fmt(b.entitled)}${b.pending ? `, ${fmt(b.pending)} pending` : ''}</span>
        <div class="meter"><i style="width:${b.entitled ? Math.max(0, Math.min(100, (b.available / b.entitled) * 100)) : 0}%"></i></div></div>`).join('')}</div>
      <div class="grid-2">
        <form class="panel stack" id="leave-form" novalidate><h3>Apply for leave</h3>
          <label class="field">Leave type<select class="input" name="leave_type">${d.types.map((t) => `<option value="${esc(t.code)}">${esc(t.name)}</option>`).join('')}</select></label>
          <p class="faint" id="type-desc" style="margin:-6px 0 0"></p>
          <div class="two"><label class="field">From<input class="input" type="date" name="start_date" required></label><label class="field">To<input class="input" type="date" name="end_date"></label></div>
          <label class="check"><input type="checkbox" name="half_day"> Half day</label>
          <label class="field">Reason<textarea class="input" name="reason" rows="2" maxlength="500"></textarea></label>
          <div id="eligibility"></div>
          <div class="row"><button class="btn" type="submit" id="apply-btn" disabled>Apply</button><span class="faint">Goes to ${esc(me.employee ? 'your reporting manager' : 'HR')} for approval.</span></div></form>
        <div class="panel"><h3>Holidays</h3>${table([{ label: 'Date', render: (h) => date(h.holiday_date) }, { label: 'Holiday', render: (h) => esc(h.name) }],
          d.holidays.filter((h) => h.holiday_date >= new Date().toISOString().slice(0, 10)).slice(0, 8), { empty: 'No holidays published.' })}</div></div>
      <div class="panel"><h3>My requests</h3>${table([
        { label: 'Type', render: (r) => esc(r.leave_name) }, { label: 'Dates', render: (r) => `${date(r.start_date)}${r.end_date !== r.start_date ? ` – ${date(r.end_date)}` : ''}` },
        { label: 'Days', cls: 'n', render: (r) => fmt(r.days) }, { label: 'Approver', render: (r) => esc(r.approver_name || 'HR') },
        { label: 'Status', render: (r) => pill(r.status) + (r.decision_note ? `<div class="faint">${esc(r.decision_note)}</div>` : '') },
        { label: '', render: (r) => (['pending', 'approved'].includes(r.status) && r.start_date > new Date().toISOString().slice(0, 10) ? `<button class="btn ghost small" data-cancel="${r.id}">Cancel</button>` : '') },
      ], d.requests, { empty: 'You have not applied for leave yet.' })}</div>`);
    const form = document.getElementById('leave-form');
    const desc = () => { const t = d.types.find((x) => x.code === form.leave_type.value); document.getElementById('type-desc').textContent = t ? t.description : ''; };
    desc();
    let lastCheck = null;
    const check = async () => {
      const data = H.formObject(form);
      if (!data.start_date) { document.getElementById('eligibility').innerHTML = ''; document.getElementById('apply-btn').disabled = true; return; }
      try {
        lastCheck = await api('/api/me/leave/check', { json: data });
        document.getElementById('eligibility').innerHTML = lastCheck.eligible
          ? `<div class="eligibility ok">${fmt(lastCheck.days)} working day(s). You will have ${fmt(lastCheck.balance.available - lastCheck.days)} left.</div>`
          : `<div class="eligibility no"><b>Not eligible yet</b><ul>${lastCheck.problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul></div>`;
        document.getElementById('apply-btn').disabled = !lastCheck.eligible;
      } catch (error) { toast(error.message, 'error'); }
    };
    form.addEventListener('change', (e) => { if (e.target.name === 'leave_type') desc(); if (e.target.name === 'start_date' && !form.end_date.value) form.end_date.value = form.start_date.value; check(); });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const r = await act(document.getElementById('apply-btn'), 'Applying…', () => api('/api/me/leave', { json: H.formObject(form) }), 'Leave request sent for approval.');
      if (r) leave();
    });
    content.querySelectorAll('[data-cancel]').forEach((b) => b.addEventListener('click', async () => {
      if (!(await confirmDialog('Cancel this leave?', 'Your manager will see it as cancelled.', 'Cancel leave', 'Keep it'))) return;
      const r = await act(b, 'Cancelling…', () => api(`/api/me/leave/${b.dataset.cancel}/cancel`, { method: 'POST' }), 'Leave cancelled.');
      if (r) leave();
    }));
  }

  // ---------------------------------------------------------------- attendance
  let calMonth = null;
  async function attendance() {
    loading('Attendance', '/attendance');
    const now = new Date();
    calMonth = calMonth || { year: now.getFullYear(), month: now.getMonth() + 1 };
    const d = await api(`/api/me/attendance?year=${calMonth.year}&month=${calMonth.month}`);
    const first = new Date(calMonth.year, calMonth.month - 1, 1);
    const pad = (first.getDay() + 6) % 7;
    const todayIso = new Date().toISOString().slice(0, 10);
    const s = d.summary;
    view('Attendance', '/attendance', `
      <div class="kpis">${[['Present', s.present], ['Late', s.late], ['Half day', s.half_day], ['On leave', s.on_leave], ['Absent', s.absent], ['Holidays', s.holiday]].map(([k, v]) => `<div class="kpi"><b>${v}</b><span>${k}</span></div>`).join('')}</div>
      <div class="panel"><div class="spread"><div class="row"><button class="btn ghost small" id="prev">Previous</button>
          <h3>${first.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</h3><button class="btn ghost small" id="next">Next</button></div>
        <button class="btn ghost small" id="correct">Request a correction</button></div>
        <div class="calendar" style="margin-top:14px">${['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((x) => `<div class="dow">${x}</div>`).join('')}
          ${'<div></div>'.repeat(pad)}${d.days.map((x) => `<div class="day ${x.status} ${x.date === todayIso ? 'today' : ''}" title="${esc(label(x.status))}${x.holiday ? `: ${esc(x.holiday)}` : ''}">
            <b>${Number(x.date.slice(8))}</b><small>${x.check_in ? `${time(x.check_in)}${x.check_out ? `–${time(x.check_out)}` : ''}` : x.holiday ? esc(x.holiday) : ['weekend', 'upcoming', 'not_joined'].includes(x.status) ? '' : esc(label(x.status))}</small></div>`).join('')}</div></div>`);
    document.getElementById('prev').addEventListener('click', () => { calMonth.month -= 1; if (calMonth.month < 1) { calMonth.month = 12; calMonth.year -= 1; } attendance(); });
    document.getElementById('next').addEventListener('click', () => { calMonth.month += 1; if (calMonth.month > 12) { calMonth.month = 1; calMonth.year += 1; } attendance(); });
    document.getElementById('correct').addEventListener('click', () => newRequest('attendance_correction'));
  }

  // ---------------------------------------------------------------- payslips
  async function payslips() {
    loading('Payslips', '/payslips');
    const d = await api('/api/me/payslips');
    const st = d.structure;
    view('Payslips', '/payslips', `
      ${st ? `<div class="panel"><h3>Salary structure</h3><p class="muted">Annual CTC <b>${money(st.annual_ctc)}</b>, effective ${date(st.effective_from)}</p>
        <div class="kpis">${[['Basic', st.components.basic], ['HRA', st.components.hra], ['Special allowance', st.components.special_allowance], ['Employer PF', st.components.employer_pf]].map(([k, v]) => `<div class="kpi"><b class="num" style="font-size:1.35rem">${money(v)}</b><span>${k} / month</span></div>`).join('')}</div></div>` : ''}
      <div class="panel"><h3>Payslips</h3>${d.payslips.length ? d.payslips.map((p) => `<details class="policy" style="margin-top:10px"><summary><span>${new Date(`${p.period}-01`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</span>
          <span class="row"><b class="num">${money(p.net_pay)}</b><a href="/api/me/payslips/${p.id}/view" target="_blank" rel="noopener">Open</a></span></summary>
          <div><div class="grid-2"><div><h4>Earnings</h4>${Object.entries(p.earnings).map(([k, v]) => `<div class="spread"><span>${esc(k)}</span><span class="num">${money(v)}</span></div>`).join('')}</div>
            <div><h4>Deductions</h4>${Object.entries(p.deductions).map(([k, v]) => `<div class="spread"><span>${esc(k)}</span><span class="num">${money(v)}</span></div>`).join('') || '<span class="faint">None</span>'}</div></div>
            <h4 style="margin-top:12px">Explained</h4><ul>${p.explanation.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div></details>`).join('') : '<div class="empty">No payslips yet. They appear after HR runs payroll for the month.</div>'}</div>`);
  }

  // ---------------------------------------------------------------- requests
  let requestMeta = null;
  async function requests() {
    loading('HR requests', '/requests');
    const d = await api('/api/me/requests');
    requestMeta = d;
    view('HR requests', '/requests', `
      <div class="row">${Object.entries(d.kinds).map(([k, v]) => `<button class="btn ${k === 'ticket' ? '' : 'ghost'} small" data-new="${k}">${esc(v)}</button>`).join('')}</div>
      <div class="panel">${table([
        { label: 'Ref', render: (r) => `<b>${esc(r.ref)}</b>` }, { label: 'Type', render: (r) => esc(r.kind_label) },
        { label: 'Subject', render: (r) => esc(r.subject) }, { label: 'Amount', cls: 'n', render: (r) => (r.amount ? money(r.amount) : '') },
        { label: 'Status', render: (r) => pill(r.status) }, { label: 'Updated', render: (r) => date(r.updated_at) },
      ], d.requests, { empty: 'No requests yet. Raise one above or ask the HR assistant.', onClick: (r) => { window.location.hash = `#/requests/${r.id}`; } })}</div>`);
    content.querySelectorAll('[data-new]').forEach((b) => b.addEventListener('click', () => newRequest(b.dataset.new)));
  }

  async function newRequest(kind) {
    const meta = requestMeta || (await api('/api/me/requests'));
    requestMeta = meta;
    const kinds = {
      ticket: `<label class="field">Category<select class="input" name="category">${options(meta.ticket_categories)}</select></label>
        <label class="field">Subject<input class="input" name="subject" required maxlength="200"></label><label class="field">Details<textarea class="input" name="description" rows="4"></textarea></label>`,
      reimbursement: `<div class="two"><label class="field">Category<select class="input" name="category">${options(meta.reimbursement_categories)}</select></label>
        <label class="field">Amount (₹)<input class="input" name="amount" type="number" min="1" step="0.01" required></label></div>
        <label class="field">Description<textarea class="input" name="description" rows="3"></textarea></label><label class="field">Receipt <span class="hint">PDF, PNG or JPG</span><input class="input" name="attachment" type="file" accept=".pdf,.png,.jpg,.jpeg"></label>`,
      document: `<label class="field">Document<select class="input" name="category">${options(meta.document_types)}</select></label><label class="field">Purpose<textarea class="input" name="description" rows="2"></textarea></label>`,
      attendance_correction: `<div class="three"><label class="field">Date<input class="input" type="date" name="work_date" required max="${new Date().toISOString().slice(0, 10)}"></label>
        <label class="field">Check-in<input class="input" type="time" name="check_in_time" required value="09:30"></label><label class="field">Check-out<input class="input" type="time" name="check_out_time" value="18:30"></label></div>
        <label class="field">Reason<textarea class="input" name="description" rows="2"></textarea></label>`,
      exit: `<p class="muted">Your resignation goes to HR, who confirm your last working day. Notice period: 60 days (15 during probation).</p>
        <label class="field">Proposed last working day<input class="input" type="date" name="last_working_day" required></label><label class="field">Reason (optional)<textarea class="input" name="description" rows="3"></textarea></label>`,
    };
    formDialog(meta.kinds[kind], `<input type="hidden" name="kind" value="${kind}">${kinds[kind]}`, kind === 'exit' ? 'Submit resignation' : 'Submit', async (_, form) => {
      const r = await api('/api/me/requests', { method: 'POST', body: new FormData(form) });
      toast(`${r.request.ref} sent to HR.`, 'ok');
      if (window.location.hash.startsWith('#/requests')) requests();
      return true;
    });
  }

  async function requestDetail({ id }) {
    loading('HR requests', '/requests');
    const { request: r } = await api(`/api/me/requests/${id}`);
    view(`${r.ref}`, '/requests', `<div class="panel stack"><div class="spread"><div><h2>${esc(r.subject)}</h2><p class="muted" style="margin:.3rem 0 0">${esc(r.kind_label)} – raised ${date(r.created_at, true)}</p></div>${pill(r.status)}</div>
      ${r.description ? `<p style="white-space:pre-wrap">${esc(r.description)}</p>` : ''}
      <dl class="kv">${r.category ? `<dt>Category</dt><dd>${esc(r.category)}</dd>` : ''}${r.amount ? `<dt>Amount</dt><dd>${money(r.amount)}</dd>` : ''}
        ${Object.entries(r.payload || {}).map(([k, v]) => `<dt>${esc(label(k))}</dt><dd>${esc(v)}</dd>`).join('')}${r.resolution ? `<dt>HR response</dt><dd>${esc(r.resolution)}</dd>` : ''}</dl>
      <h3>Conversation</h3><div class="transcript">${r.comments.map((c) => `<article><b>${esc(c.author)}</b> <span class="faint">${date(c.created_at, true)}</span><p>${esc(c.body)}</p></article>`).join('') || '<span class="faint">No messages yet.</span>'}</div>
      ${['open', 'in_progress'].includes(r.status) ? `<form class="row" id="comment-form"><input class="input" name="body" placeholder="Add a message for HR" style="flex:1" maxlength="2000"><button class="btn">Send</button></form>` : ''}
      <div class="row"><a class="btn ghost" href="#/requests">Back to requests</a>${r.status === 'open' ? '<button class="btn ghost" id="cancel-req">Cancel request</button>' : ''}</div></div>`);
    const form = document.getElementById('comment-form');
    if (form) form.addEventListener('submit', async (e) => { e.preventDefault(); const r2 = await act(form.querySelector('button'), 'Sending…', () => api(`/api/me/requests/${id}/comments`, { json: H.formObject(form) })); if (r2) requestDetail({ id }); });
    const c = document.getElementById('cancel-req');
    if (c) c.addEventListener('click', async () => { if (await confirmDialog('Cancel this request?', 'HR will no longer act on it.', 'Cancel request', 'Keep it')) { const r2 = await act(c, 'Cancelling…', () => api(`/api/me/requests/${id}/cancel`, { method: 'POST' })); if (r2) requestDetail({ id }); } });
  }

  // ---------------------------------------------------------------- profile, documents, policies, growth
  async function profile(_, __, reveal = false) {
    loading('Profile', '/profile');
    const { profile: p } = await api(`/api/me/profile${reveal ? '?reveal=true' : ''}`);
    const list = (items, fn) => (items || []).map(fn).join('') || '<span class="faint">None</span>';
    view('Profile', '/profile', `<div class="grid-2">
      <div class="panel stack"><div class="spread"><h3>Employment</h3>${pill(p.status)}</div><dl class="kv">
        <dt>Employee ID</dt><dd>${esc(p.employee_code)}</dd><dt>User ID</dt><dd>${esc(p.user_id)}</dd><dt>Designation</dt><dd>${esc(p.designation)}</dd>
        <dt>Department</dt><dd>${esc(p.department || '–')}</dd><dt>Reporting manager</dt><dd>${esc(p.manager_name || 'HR')}</dd><dt>Joined</dt><dd>${date(p.date_of_joining)}</dd>
        <dt>Employment type</dt><dd>${esc(p.employment_type)}</dd><dt>Location</dt><dd>${esc(p.work_location || '–')}</dd>
        ${p.status === 'probation' ? `<dt>Probation ends</dt><dd>${date(p.probation_end)}</dd>` : ''}</dl>
        <h3>Bank and tax</h3><dl class="kv"><dt>PAN</dt><dd>${esc(p.pan_number || '–')}</dd><dt>Bank account</dt><dd>${esc(p.bank_account_number || '–')}</dd><dt>IFSC</dt><dd>${esc(p.bank_ifsc || '–')}</dd></dl>
        ${reveal ? '' : '<button class="btn ghost small" id="reveal" style="justify-self:start">Show full details</button>'}<p class="faint" style="margin:0">To change bank or tax details, raise an HR ticket.</p></div>
      <form class="panel stack" id="self-form"><h3>Personal details you can edit</h3>
        <div class="two"><label class="field">Phone<input class="input" name="phone" value="${esc(p.phone)}"></label><label class="field">Blood group<input class="input" name="blood_group" value="${esc(p.blood_group)}"></label></div>
        <label class="field">Address<input class="input" name="address" value="${esc(p.address)}"></label>
        <div class="two"><label class="field">Emergency contact<input class="input" name="emergency_contact_name" value="${esc(p.emergency_contact_name)}"></label><label class="field">Emergency phone<input class="input" name="emergency_contact_phone" value="${esc(p.emergency_contact_phone)}"></label></div>
        <label class="field">LinkedIn<input class="input" name="linkedin" value="${esc(p.linkedin)}"></label>
        <label class="field">Skills <span class="hint">comma separated — used for internal opportunities and project staffing</span><textarea class="input" name="skills" rows="3">${esc((p.skills || []).join(', '))}</textarea></label>
        <button class="btn" style="justify-self:start">Save changes</button></form></div>
      <div class="grid-2"><div class="panel"><h3>Education</h3><ul class="notice-list">${list(p.education, (e) => `<li><b>${esc(e.degree)}</b><div class="muted">${esc(e.institution)} ${esc(e.year)} ${esc(e.score)}</div></li>`)}</ul></div>
        <div class="panel"><h3>Experience before Kairoz</h3><ul class="notice-list">${list(p.experience, (e) => `<li><b>${esc(e.title)}</b><div class="muted">${esc(e.company)} ${esc(e.period)}</div></li>`)}</ul></div></div>`);
    const r = document.getElementById('reveal');
    if (r) r.addEventListener('click', () => profile(null, null, true));
    const form = document.getElementById('self-form');
    form.addEventListener('submit', async (e) => { e.preventDefault(); const res = await act(form.querySelector('button'), 'Saving…', () => api('/api/me/profile', { method: 'PUT', json: H.formObject(form) }), 'Profile updated.'); if (res) profile(); });
  }

  async function documents() {
    loading('Documents', '/documents');
    const d = await api('/api/me/documents');
    view('Documents', '/documents', `<div class="panel"><div class="spread"><h3>My documents</h3><button class="btn small" id="req-doc">Request a document</button></div>
      ${table([{ label: 'Document', render: (x) => `<b>${esc(x.title)}</b>` }, { label: 'Issued', render: (x) => date(x.created_at) },
        { label: '', render: (x) => `<a href="/api/me/documents/${x.id}" target="_blank" rel="noopener">Open</a>` }], d.documents, { empty: 'No documents yet. Request an employment or salary certificate and HR will issue it here.' })}</div>`);
    document.getElementById('req-doc').addEventListener('click', () => newRequest('document'));
  }

  async function policies() {
    loading('Policies', '/policies');
    const d = await api('/api/me/policies');
    view('Policies', '/policies', `<div class="stack">${d.policies.map((p) => `<details class="policy"><summary><span>${esc(p.title)}</span><span class="faint">${esc(p.category)} – updated ${date(p.updated_at)}</span></summary><div>${esc(p.body)}</div></details>`).join('')}</div>
      <p class="faint">Have a question the policies do not answer? <a href="#/assistant">Ask the HR assistant</a>.</p>`);
  }

  async function growth() {
    loading('Growth', '/growth');
    const d = await api('/api/me/growth');
    const g = d.skill_gap;
    view('Growth', '/growth', `<div class="grid-2">
      <div class="panel stack"><h3>Skills for your role${g.role ? ` (${esc(g.role)})` : ''}</h3>
        ${g.role ? `${bars([{ label: 'Role skill coverage', value: g.coverage, text: `${g.coverage}%` }])}
          <div><b>You have</b><div class="chips">${(g.matched || []).map((s) => `<span class="chip hit">${esc(s)}</span>`).join('') || '<span class="faint">None yet</span>'}</div></div>
          <div><b>To build</b><div class="chips">${(g.missing || []).map((s) => `<span class="chip miss">${esc(s)}</span>`).join('') || '<span class="faint">You cover every skill for your role.</span>'}</div></div>
          ${g.recommendations.length ? `<ul>${g.recommendations.map((r) => `<li><b>${esc(r.skill)}</b>: ${esc(r.suggestion)}</li>`).join('')}</ul>` : ''}` : '<p class="muted">Your role has no skill profile yet. Add your skills on your profile.</p>'}</div>
      <div class="panel stack"><h3>Internal opportunities</h3>${d.internal_roles.length ? d.internal_roles.map((r) => `<div class="spread"><div><b>${esc(r.title)}</b><div class="faint">${esc(r.department)} – missing: ${esc(r.missing.join(', ') || 'none')}</div></div>${pill(r.coverage >= 70 ? 'ok' : 'wait', `${r.coverage}% match`)}</div>`).join('') : '<p class="muted">No open roles match your skills closely yet.</p>'}
        <p class="faint" style="margin:0">Interested in a move? Raise an HR ticket so HR can discuss it with you and your manager.</p></div></div>
      <div class="panel"><h3>Performance check-ins</h3>${table([{ label: 'Period', render: (r) => esc(r.period_label) }, { label: 'Rating', render: (r) => `<b>${fmt(r.rating)}</b> / 5` },
        { label: 'Notes', render: (r) => esc(r.notes) }, { label: 'Date', render: (r) => date(r.created_at) }], d.reviews, { empty: 'Your 3-month check-in will appear here.' })}</div>`);
  }

  // ---------------------------------------------------------------- team (managers)
  async function team() {
    loading('My team', '/team');
    const d = await api('/api/me/team');
    view('My team', '/team', `
      <div class="panel"><h3>Leave waiting for you</h3>${table([
        { label: 'Employee', render: (r) => `<b>${esc(r.employee_name)}</b>` }, { label: 'Type', render: (r) => esc(r.leave_name) },
        { label: 'Dates', render: (r) => `${date(r.start_date)}${r.end_date !== r.start_date ? ` – ${date(r.end_date)}` : ''}` }, { label: 'Days', cls: 'n', render: (r) => fmt(r.days) },
        { label: 'Reason', render: (r) => esc(r.reason) },
        { label: '', render: (r) => `<div class="row"><button class="btn mint small" data-approve="${r.id}">Approve</button><button class="btn ghost small" data-reject="${r.id}">Reject</button></div>` },
      ], d.pending, { empty: 'No leave requests waiting.' })}</div>
      <div class="panel"><h3>Direct reports</h3>${table([
        { label: 'Name', render: (r) => `<b>${esc(r.full_name)}</b><div class="faint">${esc(r.employee_code)}</div>` }, { label: 'Designation', render: (r) => esc(r.designation) },
        { label: 'Today', render: (r) => pill(r.today) }, { label: 'Joined', render: (r) => date(r.date_of_joining) },
        { label: 'Latest review', render: (r) => (r.reviews[0] ? `${fmt(r.reviews[0].rating)}/5 (${esc(r.reviews[0].period_label)})` : '–') },
        { label: '', render: (r) => `<button class="btn ghost small" data-review="${r.id}" data-name="${esc(r.full_name)}">Add review</button>` },
      ], d.reports)}
        ${d.due_reviews.length ? `<p class="faint" style="margin-top:12px">Check-ins due: ${d.due_reviews.map((x) => `${esc(x.full_name)} (${esc(x.period_label)}, ${date(x.due_on)})`).join('; ')}</p>` : ''}</div>`);
    const decide = (id, approve, b) => formDialog(approve ? 'Approve leave' : 'Reject leave', '<label class="field">Note (optional)<textarea class="input" name="note" rows="2"></textarea></label>',
      approve ? 'Approve' : 'Reject', async (data) => { await api(`/api/me/team/leave/${id}/decision`, { json: { approve, note: data.note } }); toast(approve ? 'Approved.' : 'Rejected.', 'ok'); team(); return true; });
    content.querySelectorAll('[data-approve]').forEach((b) => b.addEventListener('click', () => decide(b.dataset.approve, true, b)));
    content.querySelectorAll('[data-reject]').forEach((b) => b.addEventListener('click', () => decide(b.dataset.reject, false, b)));
    content.querySelectorAll('[data-review]').forEach((b) => b.addEventListener('click', () => reviewDialog(b.dataset.review, b.dataset.name, `/api/me/team/${b.dataset.review}/reviews`, team)));
  }

  function reviewDialog(id, name, url, after) {
    const comps = ['Domain knowledge', 'Technical understanding', 'Problem solving', 'Communication', 'Ownership'];
    formDialog(`Performance review – ${name}`, `<div class="two"><label class="field">Period<select class="input" name="period">${options([{ value: '3m', label: '3-month check-in' }, { value: '6m', label: '6-month check-in' }, { value: '12m', label: '12-month review' }, { value: 'annual', label: 'Annual review' }])}</select></label>
      <label class="field">Overall rating (1–5)<input class="input" name="rating" type="number" min="1" max="5" step="0.5" value="3.5" required></label></div>
      <div class="three">${comps.map((c) => `<label class="field">${c}<input class="input" name="c_${c}" type="number" min="1" max="5" step="0.5"></label>`).join('')}</div>
      <label class="field">Notes<textarea class="input" name="notes" rows="3"></textarea></label>`, 'Save review', async (data) => {
      const competencies = {};
      comps.forEach((c) => { if (data[`c_${c}`]) competencies[c] = Number(data[`c_${c}`]); });
      await api(url, { json: { period: data.period, rating: Number(data.rating), competencies, notes: data.notes } });
      toast('Review saved.', 'ok');
      after();
      return true;
    }, { wide: true });
  }
  window.HRM_reviewDialog = reviewDialog;

  boot();
})();
