/* HR portal: overview, recruitment (pipeline, openings, benchmark, onboarding), people, leave, attendance,
   payroll, service desk, policies, talent, performance & recruitment intelligence, access, email & audit logs. */
(function () {
  'use strict';
  const H = window.HRM;
  const { esc, api, toast, act, fmt, money, date, time, pill, table, bars, animateIn, formDialog, confirmDialog, options, openDrawer, closeDrawer, label } = H;
  let me = null;
  let content = null;
  const STAGE_COLUMNS = [
    { title: 'Resume screen', stages: ['screening', 'ats_rejected'] },
    { title: 'Mock test', stages: ['test_pending', 'test_in_progress', 'test_rejected'] },
    { title: 'Interview', stages: ['interview_pending', 'interview_in_progress', 'interview_rejected'] },
    { title: 'Decision', stages: ['interview_passed', 'not_selected'] },
    { title: 'Selected & hired', stages: ['selected', 'hired'] },
  ];

  async function boot() {
    try { me = await api('/api/auth/me'); } catch (_) { return; }
    let dash = null;
    try { dash = await api('/api/hr/dashboard'); } catch (_) { /* counts optional */ }
    const p = (dash && dash.pending) || {};
    const nav = [
      { group: 'Overview', items: [{ path: '/', label: 'Dashboard', icon: 'home' }] },
      { group: 'Recruitment', items: [
        { path: '/recruitment', label: 'Hiring pipeline', icon: 'funnel', count: p.awaiting_decision },
        { path: '/openings', label: 'Job openings', icon: 'briefcase' }, { path: '/benchmark', label: 'Benchmarking', icon: 'chart' },
        { path: '/onboarding', label: 'Onboarding', icon: 'onboard', count: p.onboarding }] },
      { group: 'People', items: [
        { path: '/employees', label: 'Employees', icon: 'users' }, { path: '/leave', label: 'Leave', icon: 'calendar', count: p.leave_hr },
        { path: '/attendance', label: 'Attendance', icon: 'clock' }, { path: '/payroll', label: 'Payroll', icon: 'wallet' },
        { path: '/requests', label: 'Service desk', icon: 'inbox', count: p.requests }, { path: '/policies', label: 'Policies', icon: 'book' }] },
      { group: 'Intelligence', items: [
        { path: '/talent', label: 'Talent & skills', icon: 'spark' }, { path: '/performance', label: 'Performance', icon: 'star', count: p.reviews_due }] },
      { group: 'Admin', items: [
        { path: '/access', label: 'Access & accounts', icon: 'shield' }, { path: '/emails', label: 'Email log', icon: 'mail' }, { path: '/audit', label: 'Audit log', icon: 'audit' }] },
    ];
    if (me.employee_id) nav[0].items.push({ path: '/my-portal', label: 'My employee portal', icon: 'user' });
    content = H.shell({ nav, me, subtitle: `${me.user_id} – ${me.role === 'hr_admin' ? 'HR administrator' : 'HR'}`, onNotifications: showNotifications });
    refreshBell();
    H.router([
      { path: '/', view: dashboard }, { path: '/recruitment', view: recruitment }, { path: '/recruitment/:id', view: recruitment },
      { path: '/openings', view: openings }, { path: '/benchmark', view: benchmark }, { path: '/onboarding', view: onboarding },
      { path: '/employees', view: employees }, { path: '/employees/:id', view: employee }, { path: '/leave', view: leave },
      { path: '/attendance', view: attendance }, { path: '/payroll', view: payroll }, { path: '/requests', view: requests },
      { path: '/requests/:id', view: requestDetail }, { path: '/policies', view: policies }, { path: '/talent', view: talent },
      { path: '/performance', view: performance }, { path: '/access', view: access }, { path: '/emails', view: emails }, { path: '/audit', view: audit },
      { path: '/my-portal', view: () => { window.location.href = '/me'; } },
    ], '#/');
  }

  async function refreshBell() {
    try {
      const n = await api('/api/hr/notifications');
      const bell = document.getElementById('bell');
      bell.querySelector('.dot')?.remove();
      if (n.unread) bell.insertAdjacentHTML('beforeend', '<span class="dot"></span>');
    } catch (_) { /* ignore */ }
  }

  async function showNotifications() {
    const n = await api('/api/hr/notifications');
    openDrawer(`<div class="drawer-head"><h2>Notifications</h2><button class="btn ghost small" data-close>Close</button></div>
      <div class="drawer-body"><ul class="notice-list">${n.notifications.map((x) => `<li class="${x.is_read ? '' : 'unread'}"><b>${esc(x.title)}</b><div class="muted">${esc(x.body)}</div>
        <div class="spread"><span class="faint">${date(x.created_at, true)}</span>${x.link ? `<a href="${esc(x.link)}" data-go>Open</a>` : ''}</div></li>`).join('') || '<li class="empty">No notifications yet.</li>'}</ul></div>`);
    document.querySelectorAll('[data-go]').forEach((a) => a.addEventListener('click', () => closeDrawer()));
    await api('/api/hr/notifications/read', { method: 'POST' });
    refreshBell();
  }

  const view = (title, path, html) => { H.setPage(title, path); content.innerHTML = html; animateIn(content); };
  const loading = (title, path) => view(title, path, '<div class="empty">Loading…</div>');
  const scoreColour = (v, pass) => (v === null || v === undefined ? '' : Number(v) >= pass ? 'ok' : 'no');

  // ---------------------------------------------------------------- dashboard
  async function dashboard() {
    loading('Dashboard', '/');
    const d = await api('/api/hr/dashboard');
    const at = d.attendance_today;
    const maxFunnel = Math.max(1, ...d.funnel.map((f) => f.count));
    const ev = d.events;
    view('Dashboard', '/', `
      <div class="kpis">
        <a class="kpi" href="#/employees"><b>${d.headcount.total}</b><span>Employees (${d.headcount.probation} on probation)</span></a>
        <a class="kpi" href="#/attendance"><b>${(at.present || 0) + (at.late || 0)}</b><span>Checked in today (${at.late || 0} late, ${at.on_leave || 0} on leave)</span></a>
        <a class="kpi ${d.pending.leave ? 'alert' : ''}" href="#/leave"><b>${d.pending.leave}</b><span>Leave requests pending (${d.pending.leave_hr} with HR)</span></a>
        <a class="kpi ${d.pending.requests ? 'alert' : ''}" href="#/requests"><b>${d.pending.requests}</b><span>Open HR requests</span></a>
        <a class="kpi ${d.pending.awaiting_decision ? 'alert' : ''}" href="#/recruitment"><b>${d.pending.awaiting_decision}</b><span>Candidates awaiting your decision</span></a>
        <a class="kpi" href="#/onboarding"><b>${d.pending.onboarding}</b><span>Onboarding forms pending</span></a>
      </div>
      <div class="grid-2">
        <div class="panel"><div class="spread"><h3>Hiring funnel</h3><a href="#/recruitment">Open pipeline</a></div><div style="margin-top:14px">
          ${bars(d.funnel.map((f) => ({ label: f.label, value: f.count, max: maxFunnel, text: f.count })))}</div></div>
        <div class="panel"><div class="spread"><h3>Open roles</h3><a href="#/openings">Manage</a></div>${table([
          { label: 'Role', render: (r) => `<b>${esc(r.title)}</b><div class="faint">${esc(r.department)}</div>` },
          { label: 'Applicants', cls: 'n', render: (r) => r.applicants }, { label: 'Hired', cls: 'n', render: (r) => `${r.hired} / ${r.openings}` }],
          d.open_roles, { empty: 'No open roles.' })}</div></div>
      <div class="grid-3">
        <div class="panel"><h3>Headcount by department</h3><div style="margin-top:12px">${bars(d.headcount.by_department.map((x) => ({ label: x.department, value: x.count, max: Math.max(1, d.headcount.total), text: x.count })))}</div>
          <p class="faint" style="margin-top:12px">Joined in last 30 days: ${d.headcount.joined_30d}. Attrition (12 months): ${d.attrition_12m}%. On notice: ${d.headcount.notice}.</p></div>
        <div class="panel"><h3>On leave today</h3>${d.on_leave_today.length ? `<ul class="notice-list">${d.on_leave_today.map((x) => `<li><b>${esc(x.full_name)}</b> <span class="faint">${esc(x.leave_name)} until ${date(x.end_date)}</span></li>`).join('')}</ul>` : '<div class="empty">Everyone is in.</div>'}</div>
        <div class="panel"><h3>Next 30 days</h3><ul class="notice-list">
          ${ev.probation_ends.map((x) => `<li>${pill('probation', 'Probation ends')} <a href="#/employees/${x.id}">${esc(x.employee)}</a> <span class="faint">${date(x.date)}</span></li>`).join('')}
          ${ev.birthdays.map((x) => `<li>${pill('info', 'Birthday')} ${esc(x.employee)} <span class="faint">${date(x.date)}</span></li>`).join('')}
          ${ev.anniversaries.map((x) => `<li>${pill('ok', `${x.years} yr`)} ${esc(x.employee)} <span class="faint">${date(x.date)}</span></li>`).join('')}
          ${!ev.probation_ends.length && !ev.birthdays.length && !ev.anniversaries.length ? '<li class="faint">Nothing scheduled.</li>' : ''}</ul></div></div>
      <div class="panel"><div class="spread"><h3>Recent hires</h3><a href="#/employees">All employees</a></div>${table([
        { label: 'Employee', render: (e) => `<b>${esc(e.full_name)}</b> <span class="faint">${esc(e.employee_code)}</span>` },
        { label: 'Designation', render: (e) => esc(e.designation) }, { label: 'Joining', render: (e) => date(e.date_of_joining) }],
        d.recent_hires, { onClick: (e) => { window.location.hash = `#/employees/${e.id}`; } })}</div>`);
  }

  // ---------------------------------------------------------------- recruitment
  let pipelineRole = '';
  async function recruitment(params = {}) {
    loading('Hiring pipeline', '/recruitment');
    const d = await api(`/api/hr/recruitment/overview?role=${encodeURIComponent(pipelineRole)}`);
    const t = d.thresholds;
    const draw = () => {
      const q = (document.getElementById('cand-search')?.value || '').toLowerCase();
      const apps = d.applications.filter((a) => !q || a.full_name.toLowerCase().includes(q) || a.email.includes(q));
      document.getElementById('board').innerHTML = STAGE_COLUMNS.map((col) => {
        const rows = apps.filter((a) => col.stages.includes(a.stage.key));
        return `<div class="column"><header>${col.title}<span>${rows.length}</span></header>${rows.map((a) => `<button class="cand tone-${a.stage.tone}" data-id="${a.id}">
          <div class="n">${esc(a.full_name || a.email)}</div><div class="r">${esc(a.role_title)} – ${esc(a.stage.label)}</div>
          <div class="scores">${a.ats_score !== null ? pill(scoreColour(a.ats_score, t.ats), `ATS ${fmt(a.ats_score)}`) : ''}${a.test_percent !== null ? pill(scoreColour(a.test_percent, t.test), `Test ${fmt(a.test_percent)}%`) : ''}${a.interview_score !== null ? pill(scoreColour(a.interview_score, t.interview), `Interview ${fmt(a.interview_score)}`) : ''}</div></button>`).join('') || '<div class="empty" style="padding:14px 4px">None</div>'}</div>`;
      }).join('');
      document.querySelectorAll('.cand').forEach((b) => b.addEventListener('click', () => candidate(Number(b.dataset.id))));
    };
    view('Hiring pipeline', '/recruitment', `
      <div class="spread"><p class="muted" style="margin:0">Pass marks: resume ${fmt(t.ats)}, mock test ${fmt(t.test)}%, interview ${fmt(t.interview)}. The agent screens, tests, interviews and emails candidates automatically.</p>
        <div class="toolbar"><select class="input" id="role-filter">${options(d.roles, pipelineRole, { valueKey: 'key', labelKey: 'title', blank: 'All roles' })}</select>
          <input class="input" type="search" id="cand-search" placeholder="Search candidates"></div></div>
      <div class="board" id="board"></div>`);
    draw();
    document.getElementById('cand-search').addEventListener('input', draw);
    document.getElementById('role-filter').addEventListener('change', (e) => { pipelineRole = e.target.value; recruitment(); });
    if (params.id) candidate(Number(params.id));
  }

  async function candidate(id) {
    let app;
    try { app = (await api(`/api/hr/recruitment/applications/${id}`)).application; } catch (error) { toast(error.message, 'error'); return; }
    const ats = app.ats_report || {};
    const ev = app.evaluation;
    const iv = app.interview;
    const test = app.test;
    const integ = (i) => (i ? Object.entries(i).filter(([, v]) => v).map(([k, v]) => `${label(k)}: ${v === true ? 'yes' : v}`).join(', ') || 'No flags' : '–');
    const drawer = openDrawer(`
      <div class="drawer-head"><div><h2>${esc(app.full_name)}</h2><span class="faint">${esc(app.role_title)} – ${esc(app.stage.label)}</span></div><button class="btn ghost small" data-close>Close</button></div>
      <div class="drawer-body">
        ${app.stage.key === 'interview_passed' ? `<div class="stage-band action"><div><h3>Your decision</h3><p>This candidate cleared every round. Selecting sends the offer email with the prefilled onboarding form.</p></div>
          <div class="row"><button class="btn mint" id="select">Select</button><button class="btn ghost" id="reject">Not selected</button></div></div>` : ''}
        ${app.stage.key === 'selected' ? `<div class="stage-band passed"><div><h3>Selected – onboarding form sent</h3><p>The employee account is created automatically when the candidate submits the form.</p></div><button class="btn ghost" id="reject">Withdraw selection</button></div>` : ''}
        ${app.onboarding && app.onboarding.employee_code ? `<div class="stage-band passed"><div><h3>Hired as ${esc(app.onboarding.employee_code)}</h3><p>Joining ${date(app.onboarding.date_of_joining)}.</p></div></div>` : ''}
        <section><dl class="kv"><dt>Email</dt><dd>${esc(app.email)}</dd><dt>Phone</dt><dd>${esc(app.phone || '–')}</dd><dt>Experience</dt><dd>${fmt(app.experience_years)} years</dd>
          <dt>Applied</dt><dd>${date(app.created_at, true)}</dd><dt>Resume</dt><dd><a href="/api/hr/recruitment/applications/${app.id}/resume">${esc(app.resume_name)}</a></dd></dl></section>
        ${ev ? `<section><h3>Competency scorecard ${ev.scorecard.overall !== null ? `<span class="pill info">overall ${fmt(ev.scorecard.overall)}</span>` : ''}</h3>
          ${bars(ev.scorecard.competencies.filter((c) => c.score !== null).map((c) => ({ label: c.name, value: c.score, text: fmt(c.score) })), { colour: (v) => (v >= 75 ? 'var(--mint)' : v >= 55 ? 'var(--brand)' : 'var(--coral)') })}
          <p class="faint" style="margin-top:8px">${ev.scorecard.competencies.map((c) => `${esc(c.name)}: ${esc(c.evidence)}`).join('<br>')}</p></section>
          <section><h3>SWOT (evidence-based)</h3><div class="swot">
            <div class="s"><b>Strengths</b><ul>${ev.swot.strengths.map((x) => `<li>${esc(x)}</li>`).join('') || '<li>–</li>'}</ul></div>
            <div class="w"><b>Development areas</b><ul>${ev.swot.weaknesses.map((x) => `<li>${esc(x)}</li>`).join('') || '<li>–</li>'}</ul></div>
            <div class="o"><b>Opportunities</b><ul>${ev.swot.opportunities.map((x) => `<li>${esc(x)}</li>`).join('') || '<li>–</li>'}</ul></div>
            <div class="t"><b>Concerns</b><ul>${ev.swot.threats.map((x) => `<li>${esc(x)}</li>`).join('') || '<li>–</li>'}</ul></div></div>
          ${ev.scorecard.integrity.length ? `<div class="eligibility no" style="margin-top:10px"><b>Integrity signals for human review</b><ul>${ev.scorecard.integrity.map((f) => `<li>${esc(f.text)}</li>`).join('')}</ul></div>` : ''}</section>` : ''}
        <section><h3>Resume screen – ATS ${fmt(app.ats_score)}</h3>
          ${bars((ats.score_breakdown || []).map((b) => ({ label: b.name, value: b.points, max: b.max, text: `${b.points} / ${b.max}` })))}
          <div class="chips">${(ats.matched_keywords || []).slice(0, 14).map((k) => `<span class="chip hit">${esc(k)}</span>`).join('')}${(ats.missing_keywords || []).slice(0, 10).map((k) => `<span class="chip miss">${esc(k)}</span>`).join('')}</div></section>
        <section><h3>Mock test${test && test.percent !== null ? ` – ${fmt(test.percent)}%` : ''}</h3>${test ? `<dl class="kv"><dt>Status</dt><dd>${esc(test.status)}</dd><dt>Finished</dt><dd>${date(test.completed_at, true)}</dd><dt>Integrity</dt><dd>${esc(integ(test.integrity))}</dd></dl>
          <div style="margin-top:10px">${bars((test.scorecard.topic_breakdown || []).map((x) => ({ label: x.label, value: x.correct, max: x.total, text: `${x.correct} / ${x.total}` })))}</div>` : '<span class="faint">Not started</span>'}</section>
        <section><h3>Interview${iv && iv.score !== null ? ` – ${fmt(iv.score)}` : ''}</h3>${iv ? `<dl class="kv"><dt>Status</dt><dd>${esc(iv.status)}</dd><dt>Finished</dt><dd>${date(iv.completed_at, true)}</dd><dt>Integrity</dt><dd>${esc(integ(iv.integrity))}</dd></dl>
          ${iv.report && iv.report.summary ? `<p style="margin-top:10px">${esc(iv.report.summary)}</p>` : ''}
          <div class="transcript" style="margin-top:10px">${(iv.transcript || []).map((x) => `<article><b>${esc(x.question)}</b>${x.answer_type === 'code' ? `<pre class="code"><code>${esc(x.answer)}</code></pre>` : `<p>${esc(x.answer || '(no answer)')}</p>`}</article>`).join('')}</div>` : '<span class="faint">Not started</span>'}</section>
        <section><h3>Emails sent</h3>${table([{ label: 'Sent', render: (e) => date(e.created_at, true) }, { label: 'Email', render: (e) => esc(e.subject) }, { label: '', render: (e) => pill(e.status === 'sent' ? 'ok' : 'no', e.status) }], app.emails, { empty: 'None yet.' })}</section>
        <section><h3>Timeline</h3><ol class="timeline">${app.events.map((e) => `<li><b>${esc(label(e.event))}</b> <span class="faint">${date(e.created_at, true)} by ${esc(e.actor)}</span></li>`).join('')}</ol></section>
      </div>`);
    const decide = (select) => formDialog(select ? `Select ${app.full_name}?` : `Not selecting ${app.full_name}`,
      `<p class="muted">${select ? 'The candidate receives the selection email with the onboarding form.' : 'The candidate receives a polite rejection email.'}</p><label class="field">Internal note (optional)<textarea class="input" name="note" rows="2"></textarea></label>`,
      select ? 'Select and send offer' : 'Confirm', async (data) => {
        await api(`/api/hr/recruitment/applications/${app.id}/decision`, { json: { select, note: data.note } });
        toast(select ? 'Selected. Offer and onboarding form sent.' : 'Decision recorded and candidate informed.', 'ok');
        closeDrawer(); recruitment(); return true;
      });
    drawer.querySelector('#select')?.addEventListener('click', () => decide(true));
    drawer.querySelector('#reject')?.addEventListener('click', () => decide(false));
  }

  async function openings() {
    loading('Job openings', '/openings');
    const d = await api('/api/hr/recruitment/openings');
    view('Job openings', '/openings', `<div class="spread"><p class="muted" style="margin:0">Candidates are scored against the job description and required skills you set here.</p><button class="btn" id="new-opening">New opening</button></div>
      <div class="panel">${table([
        { label: 'Role', render: (r) => `<b>${esc(r.title)}</b><div class="faint">${esc(r.department)}, ${esc(r.location)}</div>` },
        { label: 'Experience', render: (r) => esc(r.experience) }, { label: 'Offer CTC', cls: 'n', render: (r) => money(r.annual_ctc) },
        { label: 'Applicants', cls: 'n', render: (r) => r.applicants }, { label: 'Hired', cls: 'n', render: (r) => `${r.hired} / ${r.openings}` },
        { label: 'Status', render: (r) => pill(r.status === 'open' ? 'open-role' : 'cancelled', r.status) },
      ], d.openings, { onClick: (r) => openingDialog(r) })}</div>`);
    document.getElementById('new-opening').addEventListener('click', () => openingDialog(null));
  }

  function openingDialog(r) {
    const desc = r ? r.description : '';
    formDialog(r ? `Edit ${r.title}` : 'New job opening', `
      <div class="two"><label class="field">Title<input class="input" name="title" required value="${esc(r ? r.title : '')}"></label>
        <label class="field">Department<input class="input" name="department" value="${esc(r ? r.department : '')}"></label></div>
      <div class="three"><label class="field">Location<input class="input" name="location" value="${esc(r ? r.location : '')}"></label>
        <label class="field">Minimum years<input class="input" name="min_years" type="number" min="0" step="0.5" value="${esc(r ? r.min_years : 0)}"></label>
        <label class="field">Openings<input class="input" name="openings" type="number" min="1" value="${esc(r ? r.openings : 1)}"></label></div>
      <div class="two"><label class="field">Offer CTC (₹ per year)<input class="input" name="annual_ctc" type="number" min="0" step="1000" value="${esc(r ? r.annual_ctc : '')}"></label>
        <label class="field">Employment type<select class="input" name="employment_type">${options(['Full-time', 'Contract', 'Internship'], r ? r.employment_type : 'Full-time')}</select></label></div>
      <label class="field">Required skills <span class="hint">comma separated; the ATS scores resumes against these</span><input class="input" name="skills" required value="${esc(r ? r.skills.join(', ') : '')}"></label>
      ${r ? `<label class="field">Job description<textarea class="input" name="description" rows="6">${esc(desc)}</textarea></label>
        <label class="field">Status<select class="input" name="status">${options(['open', 'closed'], r.status)}</select></label>`
        : `<label class="field">Summary<input class="input" name="summary" placeholder="One line about the role"></label>
        <label class="field">Responsibilities<textarea class="input" name="responsibilities" rows="3" placeholder="build REST APIs, review code, mentor juniors"></textarea></label>`}`,
    r ? 'Save' : 'Publish opening', async (data) => {
      if (r) await api(`/api/hr/recruitment/openings/${r.key}`, { method: 'PUT', json: data });
      else await api('/api/hr/recruitment/openings', { json: data });
      toast(r ? 'Opening updated.' : 'Opening published on the careers portal.', 'ok');
      openings(); return true;
    }, { wide: true });
  }

  let benchRole = '';
  async function benchmark() {
    loading('Benchmarking', '/benchmark');
    const { openings: roles } = await api('/api/hr/recruitment/openings');
    benchRole = benchRole || (roles[0] && roles[0].key) || '';
    const d = benchRole ? await api(`/api/hr/recruitment/benchmark/${benchRole}`) : { candidates: [], averages: {} };
    const comps = Object.keys(d.averages || {});
    view('Benchmarking', '/benchmark', `<div class="spread"><p class="muted" style="margin:0">Candidates for one role ranked on the same criteria. Competency scores come from the resume, test and interview evidence.</p>
      <select class="input" id="bench-role" style="width:auto">${options(roles, benchRole, { valueKey: 'key', labelKey: 'title' })}</select></div>
      <div class="panel">${table([
        { label: '#', render: (c) => c.rank }, { label: 'Candidate', render: (c) => `<b>${esc(c.name)}</b><div class="faint">${esc(label(c.stage))}</div>` },
        { label: 'Overall', cls: 'n', render: (c) => `<b>${fmt(c.overall)}</b>` }, { label: 'ATS', cls: 'n', render: (c) => fmt(c.ats) },
        { label: 'Test', cls: 'n', render: (c) => fmt(c.test) }, { label: 'Interview', cls: 'n', render: (c) => fmt(c.interview) },
        ...comps.map((name) => ({ label: name, cls: 'n', render: (c) => { const v = c.competencies[name]; const avg = d.averages[name]; return v === null || v === undefined ? '–' : `<span style="color:${avg !== null && v >= avg ? 'var(--mint)' : 'var(--coral)'}">${fmt(v)}</span>`; } })),
        { label: 'Flags', cls: 'n', render: (c) => (c.flags ? pill('wait', c.flags) : '') },
      ], d.candidates, { empty: 'No candidate for this role has taken the mock test yet.', onClick: (c) => { window.location.hash = `#/recruitment/${c.id}`; } })}
      ${comps.length && d.candidates.length ? `<p class="faint" style="margin-top:10px">Role averages: ${comps.map((n) => `${esc(n)} ${fmt(d.averages[n])}`).join(', ')}. Green is at or above the average.</p>` : ''}</div>`);
    document.getElementById('bench-role').addEventListener('change', (e) => { benchRole = e.target.value; benchmark(); });
  }

  async function onboarding() {
    loading('Onboarding', '/onboarding');
    const d = await api('/api/hr/recruitment/onboarding');
    view('Onboarding', '/onboarding', `<p class="muted" style="margin:0">Selected candidates fill a form prefilled from their resume. When they submit, the employee record, account and salary structure are created and credentials are emailed.</p>
      <div class="panel">${table([
        { label: 'Candidate', render: (o) => `<b>${esc(o.full_name)}</b><div class="faint">${esc(o.email)}</div>` }, { label: 'Role', render: (o) => esc(o.role_title) },
        { label: 'Status', render: (o) => pill(o.status === 'completed' ? 'completed' : 'pending', o.status === 'completed' ? 'Completed' : 'Waiting for candidate') },
        { label: 'Employee ID', render: (o) => (o.employee_id ? `<a href="#/employees/${o.employee_id}">${esc(o.employee_code)}</a>` : '–') },
        { label: 'Joining', render: (o) => date(o.date_of_joining) }, { label: 'Selected', render: (o) => date(o.created_at) },
      ], d.onboarding, { empty: 'No selected candidates yet.' })}</div>`);
  }

  // ---------------------------------------------------------------- employees
  let empFilter = { q: '', department: '', status: '' };
  async function employees() {
    loading('Employees', '/employees');
    const d = await api(`/api/hr/employees?q=${encodeURIComponent(empFilter.q)}&department=${encodeURIComponent(empFilter.department)}&status=${empFilter.status}`);
    view('Employees', '/employees', `<div class="spread"><div class="toolbar"><input class="input" type="search" id="emp-q" placeholder="Search name, ID, email, designation" value="${esc(empFilter.q)}">
        <select class="input" id="emp-dept">${options(d.departments, empFilter.department, { blank: 'All departments' })}</select>
        <select class="input" id="emp-status">${options(['probation', 'active', 'notice', 'exited'], empFilter.status, { blank: 'All statuses' })}</select></div>
        <button class="btn" id="add-emp">Add employee</button></div>
      <div class="panel">${table([
        { label: 'Employee', render: (e) => `<b>${esc(e.full_name)}</b><div class="faint">${esc(e.employee_code)} – ${esc(e.email)}</div>` },
        { label: 'Designation', render: (e) => `${esc(e.designation)}<div class="faint">${esc(e.department)}</div>` },
        { label: 'Manager', render: (e) => esc(e.manager_name || '–') }, { label: 'Joined', render: (e) => date(e.date_of_joining) }, { label: 'Status', render: (e) => pill(e.status) },
      ], d.employees, { empty: 'No employees match.', onClick: (e) => { window.location.hash = `#/employees/${e.id}`; } })}</div>`);
    let timer;
    document.getElementById('emp-q').addEventListener('input', (e) => { clearTimeout(timer); timer = setTimeout(() => { empFilter.q = e.target.value; employees(); }, 350); });
    document.getElementById('emp-dept').addEventListener('change', (e) => { empFilter.department = e.target.value; employees(); });
    document.getElementById('emp-status').addEventListener('change', (e) => { empFilter.status = e.target.value; employees(); });
    document.getElementById('add-emp').addEventListener('click', () => formDialog('Add an existing employee', `
      <p class="muted">For staff who joined before this portal. Candidates hired through the portal are created automatically.</p>
      <div class="two"><label class="field">Full name<input class="input" name="full_name" required></label><label class="field">Email<input class="input" name="email" type="email" required></label></div>
      <div class="three"><label class="field">Designation<input class="input" name="designation"></label><label class="field">Department<input class="input" name="department" list="depts"></label>
        <label class="field">Date of joining<input class="input" name="date_of_joining" type="date"></label></div>
      <div class="three"><label class="field">Phone<input class="input" name="phone"></label><label class="field">Location<input class="input" name="work_location"></label>
        <label class="field">Annual CTC (₹)<input class="input" name="annual_ctc" type="number" min="0" step="1000"></label></div>
      <label class="field">Skills <span class="hint">comma separated</span><input class="input" name="skills"></label>
      <datalist id="depts">${d.departments.map((x) => `<option value="${esc(x)}">`).join('')}</datalist>`, 'Create and email credentials', async (data) => {
      const r = await api('/api/hr/employees', { json: data });
      toast(r.message, 'ok');
      window.location.hash = `#/employees/${r.employee.id}`;
      return true;
    }, { wide: true }));
  }

  async function employee({ id }) {
    loading('Employees', '/employees');
    const d = await api(`/api/hr/employees/${id}`);
    const e = d.employee;
    let tab = sessionStorage.getItem('emp-tab') || 'overview';
    const tabs = { overview: 'Overview', job: 'Job & access', leave: 'Leave', pay: 'Payroll', requests: 'Requests', reviews: 'Performance', docs: 'Documents' };
    const panes = {
      overview: () => `<div class="grid-2"><div class="panel"><h3>Personal</h3><dl class="kv">
          <dt>Email</dt><dd>${esc(e.email)}</dd><dt>Phone</dt><dd>${esc(e.phone || '–')}</dd><dt>Date of birth</dt><dd>${date(e.date_of_birth)}</dd>
          <dt>Address</dt><dd>${esc(e.address || '–')}</dd><dt>Emergency</dt><dd>${esc(e.emergency_contact_name || '–')} ${esc(e.emergency_contact_phone)}</dd>
          <dt>PAN</dt><dd>${esc(e.pan_number || '–')}</dd><dt>Bank</dt><dd>${esc(e.bank_account_number || '–')} ${esc(e.bank_ifsc)}</dd><dt>LinkedIn</dt><dd>${esc(e.linkedin || '–')}</dd></dl></div>
        <div class="panel stack"><h3>Skills</h3><div class="chips">${(e.skills || []).map((s) => `<span class="chip">${esc(s)}</span>`).join('') || '<span class="faint">None</span>'}</div>
          ${d.skill_gap.role ? `<h4>Gap vs ${esc(d.skill_gap.role)} (${d.skill_gap.coverage}% covered)</h4><div class="chips">${d.skill_gap.missing.map((s) => `<span class="chip miss">${esc(s)}</span>`).join('') || '<span class="faint">No gaps</span>'}</div>` : ''}
          <h4>Education</h4><ul class="notice-list">${(e.education || []).map((x) => `<li><b>${esc(x.degree)}</b> <span class="faint">${esc(x.institution)} ${esc(x.year)}</span></li>`).join('') || '<li class="faint">–</li>'}</ul>
          <h4>Previous experience</h4><ul class="notice-list">${(e.experience || []).map((x) => `<li><b>${esc(x.title)}</b> <span class="faint">${esc(x.company)} ${esc(x.period)}</span></li>`).join('') || '<li class="faint">–</li>'}</ul></div></div>`,
      job: () => `<div class="grid-2"><form class="panel stack" id="job-form"><h3>Job details</h3>
          <div class="two"><label class="field">Designation<input class="input" name="designation" value="${esc(e.designation)}"></label><label class="field">Department<input class="input" name="department" value="${esc(e.department)}"></label></div>
          <div class="two"><label class="field">Reporting manager<select class="input" name="manager_id">${options(d.managers.map((m) => ({ value: m.id, label: `${m.full_name} (${m.employee_code})` })), e.manager_id || '', { blank: 'None (HR approves leave)' })}</select></label>
            <label class="field">Status<select class="input" name="status">${options(['probation', 'active', 'notice', 'exited'], e.status)}</select></label></div>
          <div class="three"><label class="field">Joined<input class="input" type="date" name="date_of_joining" value="${esc(e.date_of_joining)}"></label>
            <label class="field">Probation ends<input class="input" type="date" name="probation_end" value="${esc(e.probation_end || '')}"></label>
            <label class="field">Exit date<input class="input" type="date" name="exit_date" value="${esc(e.exit_date || '')}"></label></div>
          <div class="two"><label class="field">Location<input class="input" name="work_location" value="${esc(e.work_location)}"></label><label class="field">Employment type<select class="input" name="employment_type">${options(['Full-time', 'Contract', 'Internship'], e.employment_type)}</select></label></div>
          <button class="btn" style="justify-self:start">Save job details</button></form>
        <div class="panel stack"><h3>Portal access</h3><dl class="kv"><dt>User ID</dt><dd>${esc(e.user_id || '–')}</dd><dt>Account</dt><dd>${e.account_active ? pill('active') : pill('exited', 'deactivated')}</dd><dt>Last sign-in</dt><dd>${date(e.last_login_at, true)}</dd></dl>
          ${e.account_id ? `<div class="row"><button class="btn ghost" id="reset-pw">Reset password</button><button class="btn ghost" id="toggle-acc">${e.account_active ? 'Deactivate account' : 'Reactivate account'}</button></div>` : ''}
          <p class="faint" style="margin:0">Setting status to exited deactivates the account automatically.</p>
          <h3>Direct reports</h3>${(e.reports || []).map((r) => `<div><a href="#/employees/${r.id}">${esc(r.full_name)}</a> <span class="faint">${esc(r.designation)}</span></div>`).join('') || '<span class="faint">None</span>'}</div></div>`,
      leave: () => `<div class="balance-grid">${d.leave_balances.map((b) => `<div class="balance"><span class="faint">${esc(b.name)}</span><b>${fmt(b.available)}</b><span class="faint">of ${fmt(b.entitled)}, used ${fmt(b.used)}</span></div>`).join('')}</div>
        <div class="panel">${leaveTable(d.leave_requests, false)}</div><p><a href="#/attendance" data-emp-att="${e.id}">Attendance calendar</a></p><div id="emp-att"></div>`,
      pay: () => `<div class="grid-2"><form class="panel stack" id="salary-form"><h3>Salary</h3>
          ${d.salary ? `<p class="muted">Current CTC <b>${money(d.salary.annual_ctc)}</b> from ${date(d.salary.effective_from)}; monthly TDS ${money(d.salary.monthly_tds)}.</p>` : '<p class="muted">No salary structure yet.</p>'}
          <div class="three"><label class="field">Annual CTC (₹)<input class="input" name="annual_ctc" type="number" min="1" step="1000" value="${d.salary ? d.salary.annual_ctc : ''}" required></label>
            <label class="field">Monthly TDS (₹)<input class="input" name="monthly_tds" type="number" min="0" step="1" value="${d.salary ? d.salary.monthly_tds : 0}"></label>
            <label class="field">Effective from<input class="input" name="effective_from" type="date" value="${new Date().toISOString().slice(0, 10)}"></label></div>
          <button class="btn" style="justify-self:start">Save salary</button></form>
        <div class="panel"><h3>Payslips</h3>${table([{ label: 'Month', render: (p) => esc(p.period) }, { label: 'Gross', cls: 'n', render: (p) => money(p.gross) }, { label: 'Net', cls: 'n', render: (p) => `<b>${money(p.net_pay)}</b>` },
          { label: '', render: (p) => `<a href="/api/hr/payslips/${p.id}/view" target="_blank" rel="noopener">Open</a>` }], d.payslips, { empty: 'No payslips yet.' })}</div></div>`,
      requests: () => `<div class="panel">${requestTable(d.requests)}</div>`,
      reviews: () => `<div class="panel"><div class="spread"><h3>Performance reviews</h3><button class="btn small" id="add-review">Add review</button></div>${table([
          { label: 'Period', render: (r) => esc(r.period_label) }, { label: 'Rating', render: (r) => `<b>${fmt(r.rating)}</b>/5` },
          { label: 'Competencies', render: (r) => esc(Object.entries(r.competencies || {}).map(([k, v]) => `${k} ${v}`).join(', ')) }, { label: 'Notes', render: (r) => esc(r.notes) },
          { label: 'By', render: (r) => esc(r.reviewer) }, { label: 'Date', render: (r) => date(r.created_at) }], d.reviews, { empty: 'No reviews yet.' })}</div>`,
      docs: () => `<div class="panel"><div class="spread"><h3>Documents</h3><div class="row"><select class="input" id="doc-kind" style="width:auto">${options(['Employment certificate', 'Salary certificate', 'Address proof letter', 'Experience letter'])}</select><button class="btn small" id="gen-doc">Generate</button></div></div>
        ${table([{ label: 'Document', render: (x) => esc(x.title) }, { label: 'Issued', render: (x) => date(x.created_at) }], d.documents, { empty: 'No documents yet.' })}</div>`,
    };
    const render = () => {
      view(e.full_name, '/employees', `<div class="spread"><div><h2>${esc(e.full_name)}</h2><p class="muted" style="margin:.3rem 0 0">${esc(e.employee_code)} – ${esc(e.designation)}, ${esc(e.department || 'no department')} – reports to ${esc(e.manager_name || 'HR')} – joined ${date(e.date_of_joining)}</p></div>${pill(e.status)}</div>
        <div><div class="tabs" role="tablist">${Object.entries(tabs).map(([k, v]) => `<button role="tab" data-tab="${k}" aria-selected="${k === tab}">${v}</button>`).join('')}</div><div id="tab-pane" class="stack">${panes[tab]()}</div></div>`);
      content.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => { tab = b.dataset.tab; sessionStorage.setItem('emp-tab', tab); render(); }));
      wire();
    };
    const wire = () => {
      const jobForm = document.getElementById('job-form');
      if (jobForm) jobForm.addEventListener('submit', async (ev) => { ev.preventDefault(); const r = await act(jobForm.querySelector('button'), 'Saving…', () => api(`/api/hr/employees/${id}`, { method: 'PUT', json: H.formObject(jobForm) }), 'Saved.'); if (r) employee({ id }); });
      document.getElementById('reset-pw')?.addEventListener('click', async (ev) => { if (await confirmDialog('Reset password?', `${e.full_name} gets a temporary password by email and must set a new one.`, 'Reset and email')) act(ev.target, 'Resetting…', () => api(`/api/hr/accounts/${e.account_id}/reset-password`, { method: 'POST' }), 'Temporary password emailed.'); });
      document.getElementById('toggle-acc')?.addEventListener('click', async (ev) => { const r = await act(ev.target, 'Saving…', () => api(`/api/hr/accounts/${e.account_id}/active`, { json: { active: !e.account_active } }), 'Account updated.'); if (r) employee({ id }); });
      const salary = document.getElementById('salary-form');
      if (salary) salary.addEventListener('submit', async (ev) => { ev.preventDefault(); const r = await act(salary.querySelector('button'), 'Saving…', () => api(`/api/hr/employees/${id}/salary`, { json: H.formObject(salary) }), 'Salary saved.'); if (r) employee({ id }); });
      document.getElementById('add-review')?.addEventListener('click', () => reviewDialog(id, e.full_name));
      document.getElementById('gen-doc')?.addEventListener('click', async (ev) => { const r = await act(ev.target, 'Generating…', () => api(`/api/hr/employees/${id}/documents`, { json: { kind: document.getElementById('doc-kind').value } }), 'Document issued to the employee.'); if (r) employee({ id }); });
      wireLeaveButtons(() => employee({ id }));
      const attLink = document.querySelector('[data-emp-att]');
      if (attLink) attLink.addEventListener('click', async (ev) => { ev.preventDefault(); const now = new Date(); const m = await api(`/api/hr/attendance/${id}?year=${now.getFullYear()}&month=${now.getMonth() + 1}`); document.getElementById('emp-att').innerHTML = `<div class="panel"><div class="calendar">${m.days.map((x) => `<div class="day ${x.status}"><b>${Number(x.date.slice(8))}</b><small>${x.check_in ? time(x.check_in) : esc(label(x.status))}</small></div>`).join('')}</div></div>`; });
    };
    render();
  }

  function reviewDialog(id, name) {
    const comps = ['Domain knowledge', 'Technical understanding', 'Problem solving', 'Communication', 'Ownership'];
    formDialog(`Performance review – ${name}`, `<div class="two"><label class="field">Period<select class="input" name="period">${options([{ value: '3m', label: '3-month check-in' }, { value: '6m', label: '6-month check-in' }, { value: '12m', label: '12-month review' }, { value: 'annual', label: 'Annual review' }])}</select></label>
      <label class="field">Overall rating (1–5)<input class="input" name="rating" type="number" min="1" max="5" step="0.5" value="3.5" required></label></div>
      <div class="three">${comps.map((c) => `<label class="field">${c}<input class="input" name="c_${c}" type="number" min="1" max="5" step="0.5"></label>`).join('')}</div>
      <label class="field">Notes<textarea class="input" name="notes" rows="3"></textarea></label>`, 'Save review', async (data) => {
      const competencies = {};
      comps.forEach((c) => { if (data[`c_${c}`]) competencies[c] = Number(data[`c_${c}`]); });
      await api(`/api/hr/employees/${id}/reviews`, { json: { period: data.period, rating: Number(data.rating), competencies, notes: data.notes } });
      toast('Review saved.', 'ok');
      employee({ id });
      return true;
    }, { wide: true });
  }

  // ---------------------------------------------------------------- leave
  function leaveTable(rows, withEmployee = true) {
    return table([
      ...(withEmployee ? [{ label: 'Employee', render: (r) => `<b>${esc(r.employee_name)}</b><div class="faint">${esc(r.employee_code)} ${esc(r.department || '')}</div>` }] : []),
      { label: 'Type', render: (r) => esc(r.leave_name) }, { label: 'Dates', render: (r) => `${date(r.start_date)}${r.end_date !== r.start_date ? ` – ${date(r.end_date)}` : ''}` },
      { label: 'Days', cls: 'n', render: (r) => fmt(r.days) }, { label: 'Reason', render: (r) => esc(r.reason) }, { label: 'Approver', render: (r) => esc(r.approver_name || 'HR') },
      { label: 'Status', render: (r) => pill(r.status) },
      { label: '', render: (r) => (r.status === 'pending' ? `<div class="row"><button class="btn mint small" data-approve="${r.id}">Approve</button><button class="btn ghost small" data-reject="${r.id}">Reject</button></div>` : '') },
    ], rows, { empty: 'No leave requests.' });
  }

  function wireLeaveButtons(after) {
    const decide = (rid, approve) => formDialog(approve ? 'Approve leave' : 'Reject leave', '<label class="field">Note to the employee (optional)<textarea class="input" name="note" rows="2"></textarea></label>',
      approve ? 'Approve' : 'Reject', async (data) => { await api(`/api/hr/leave/${rid}/decision`, { json: { approve, note: data.note } }); toast(approve ? 'Leave approved.' : 'Leave rejected.', 'ok'); after(); return true; });
    content.querySelectorAll('[data-approve]').forEach((b) => b.addEventListener('click', () => decide(b.dataset.approve, true)));
    content.querySelectorAll('[data-reject]').forEach((b) => b.addEventListener('click', () => decide(b.dataset.reject, false)));
  }

  let leaveStatus = 'pending';
  async function leave() {
    loading('Leave', '/leave');
    const [d, h] = await Promise.all([api(`/api/hr/leave?status=${leaveStatus}`), api('/api/hr/holidays')]);
    view('Leave', '/leave', `<div class="panel"><div class="spread"><h3>Leave requests</h3><select class="input" id="leave-status" style="width:auto">${options([{ value: 'pending', label: 'Pending' }, { value: 'approved', label: 'Approved' }, { value: 'rejected', label: 'Rejected' }, { value: 'all', label: 'All' }], leaveStatus)}</select></div>
        <p class="faint">Requests go to the reporting manager first; HR can decide any request. Requests without a manager wait for HR.</p>${leaveTable(d.requests)}</div>
      <div class="grid-2"><div class="panel"><h3>Leave types and quotas</h3>${table([
          { label: 'Type', render: (t) => `<b>${esc(t.name)}</b> <span class="faint">${esc(t.code)}</span>` }, { label: 'Per year', cls: 'n', render: (t) => fmt(t.annual_quota) },
          { label: 'Notice', cls: 'n', render: (t) => `${t.min_notice_days}d` }, { label: 'Max at once', cls: 'n', render: (t) => `${t.max_consecutive_days}d` },
          { label: 'Paid', render: (t) => (t.paid ? 'Yes' : 'No') }, { label: 'Probation', render: (t) => (t.allowed_in_probation ? 'Allowed' : 'After') }, { label: '', render: (t) => pill(t.active ? 'ok' : 'cancelled', t.active ? 'active' : 'off') },
        ], d.types, { onClick: (t) => leaveTypeDialog(t) })}</div>
        <div class="panel"><div class="spread"><h3>Holidays</h3><button class="btn small" id="add-holiday">Add holiday</button></div>${table([
          { label: 'Date', render: (x) => date(x.holiday_date) }, { label: 'Holiday', render: (x) => esc(x.name) }, { label: '', render: (x) => `<button class="btn ghost small" data-del-holiday="${x.id}">Remove</button>` },
        ], h.holidays)}</div></div>`);
    document.getElementById('leave-status').addEventListener('change', (e) => { leaveStatus = e.target.value; leave(); });
    wireLeaveButtons(leave);
    document.getElementById('add-holiday').addEventListener('click', () => formDialog('Add holiday', '<div class="two"><label class="field">Date<input class="input" type="date" name="date" required></label><label class="field">Name<input class="input" name="name" required></label></div>',
      'Add', async (data) => { await api('/api/hr/holidays', { json: data }); toast('Holiday added.', 'ok'); leave(); return true; }));
    content.querySelectorAll('[data-del-holiday]').forEach((b) => b.addEventListener('click', async () => { if (await confirmDialog('Remove holiday?', 'Leave and payroll calculations will treat it as a working day.', 'Remove')) { await api(`/api/hr/holidays/${b.dataset.delHoliday}`, { method: 'DELETE' }); leave(); } }));
  }

  function leaveTypeDialog(t) {
    formDialog(`Edit ${t.name}`, `<div class="three"><label class="field">Days per year<input class="input" type="number" name="annual_quota" min="0" step="0.5" value="${t.annual_quota}"></label>
      <label class="field">Notice (days)<input class="input" type="number" name="min_notice_days" min="0" value="${t.min_notice_days}"></label>
      <label class="field">Max consecutive days<input class="input" type="number" name="max_consecutive_days" min="0" value="${t.max_consecutive_days}"></label></div>
      <label class="field">Description<textarea class="input" name="description" rows="2">${esc(t.description)}</textarea></label>
      <label class="check"><input type="checkbox" name="paid" ${t.paid ? 'checked' : ''}> Paid leave</label><label class="check"><input type="checkbox" name="allow_half_day" ${t.allow_half_day ? 'checked' : ''}> Half days allowed</label>
      <label class="check"><input type="checkbox" name="allowed_in_probation" ${t.allowed_in_probation ? 'checked' : ''}> Allowed during probation</label><label class="check"><input type="checkbox" name="active" ${t.active ? 'checked' : ''}> Active</label>`,
    'Save', async (data) => { await api(`/api/hr/leave/types/${t.id}`, { method: 'PUT', json: data }); toast('Leave type saved.', 'ok'); leave(); return true; });
  }

  // ---------------------------------------------------------------- attendance
  let attDay = '';
  async function attendance() {
    loading('Attendance', '/attendance');
    const d = await api(`/api/hr/attendance${attDay ? `?day=${attDay}` : ''}`);
    const c = d.counts;
    view('Attendance', '/attendance', `<div class="spread"><div class="kpis" style="flex:1">${[['Present', c.present || 0], ['Late', c.late || 0], ['Half day', c.half_day || 0], ['On leave', c.on_leave || 0], ['Not marked', c.not_marked || 0]].map(([k, v]) => `<div class="kpi"><b>${v}</b><span>${k}</span></div>`).join('')}</div></div>
      <div class="panel"><div class="spread"><h3>${date(d.date)}</h3><input class="input" type="date" id="att-day" value="${d.date}" style="width:auto"></div>${table([
        { label: 'Employee', render: (r) => `<b>${esc(r.full_name)}</b><div class="faint">${esc(r.employee_code)}</div>` }, { label: 'Department', render: (r) => esc(r.department) },
        { label: 'Status', render: (r) => pill(r.status === 'not_marked' ? 'absent' : r.status, label(r.status)) }, { label: 'Check-in', render: (r) => time(r.check_in) }, { label: 'Check-out', render: (r) => time(r.check_out) },
      ], d.rows, { onClick: (r) => { window.location.hash = `#/employees/${r.id}`; } })}
      <p class="faint" style="margin-top:10px">Corrections requested by employees appear in the service desk; approving one updates the record.</p></div>`);
    document.getElementById('att-day').addEventListener('change', (e) => { attDay = e.target.value; attendance(); });
  }

  // ---------------------------------------------------------------- payroll
  let payPeriod = '';
  async function payroll() {
    loading('Payroll', '/payroll');
    const d = await api(`/api/hr/payroll${payPeriod ? `?period=${payPeriod}` : ''}`);
    const lastMonth = new Date(); lastMonth.setDate(0);
    const suggested = `${lastMonth.getFullYear()}-${String(lastMonth.getMonth() + 1).padStart(2, '0')}`;
    view('Payroll', '/payroll', `<div class="panel"><div class="spread"><div><h3>Run payroll</h3><p class="muted" style="margin:.3rem 0 0">Generates payslips for every active employee: pro-rated for joining date and unpaid leave, with PF, professional tax and TDS.</p></div>
        <form class="row" id="run-form"><input class="input" type="month" name="period" value="${suggested}" style="width:auto"><button class="btn">Generate payslips</button></form></div></div>
      <div class="panel"><div class="spread"><h3>Payslips ${d.period ? `– ${esc(d.period)}` : ''}</h3>${d.periods.length ? `<select class="input" id="pay-period" style="width:auto">${options(d.periods, d.period)}</select>` : ''}</div>
        ${d.payslips.length ? `<div class="kpis" style="margin:12px 0"><div class="kpi"><b class="num" style="font-size:1.4rem">${money(d.totals.gross)}</b><span>Gross</span></div><div class="kpi"><b class="num" style="font-size:1.4rem">${money(d.totals.total_deductions)}</b><span>Deductions</span></div><div class="kpi"><b class="num" style="font-size:1.4rem">${money(d.totals.net_pay)}</b><span>Net payout</span></div></div>` : ''}
        ${table([{ label: 'Employee', render: (p) => `<b>${esc(p.full_name)}</b><div class="faint">${esc(p.employee_code)}</div>` }, { label: 'Paid days', cls: 'n', render: (p) => `${fmt(p.paid_days)} / ${fmt(p.working_days)}` },
          { label: 'LOP', cls: 'n', render: (p) => fmt(p.lop_days) }, { label: 'Gross', cls: 'n', render: (p) => money(p.gross) }, { label: 'Deductions', cls: 'n', render: (p) => money(p.total_deductions) },
          { label: 'Net', cls: 'n', render: (p) => `<b>${money(p.net_pay)}</b>` }, { label: '', render: (p) => `<a href="/api/hr/payslips/${p.id}/view" target="_blank" rel="noopener">Open</a>` }], d.payslips, { empty: 'No payslips generated yet.' })}</div>
      <div class="panel"><h3>Salary structures</h3>${table([{ label: 'Employee', render: (s) => `<b>${esc(s.full_name)}</b> <span class="faint">${esc(s.employee_code)}</span>` }, { label: 'Designation', render: (s) => esc(s.designation) },
        { label: 'Annual CTC', cls: 'n', render: (s) => (s.annual_ctc ? money(s.annual_ctc) : pill('wait', 'not set')) }, { label: 'Monthly TDS', cls: 'n', render: (s) => money(s.monthly_tds) }],
        d.structures, { onClick: (s) => { sessionStorage.setItem('emp-tab', 'pay'); window.location.hash = `#/employees/${s.id}`; } })}</div>`);
    document.getElementById('run-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const period = e.target.period.value;
      if (!(await confirmDialog(`Run payroll for ${period}?`, 'Existing payslips for this month are recalculated. Employees are notified of new payslips.', 'Generate'))) return;
      const r = await act(e.target.querySelector('button'), 'Generating…', () => api('/api/hr/payroll/run', { json: { period } }));
      if (r) { toast(`${r.generated} payslip(s) generated${r.skipped.length ? `, ${r.skipped.length} skipped` : ''}.`, 'ok'); if (r.skipped.length) toast(r.skipped.map((s) => `${s.employee}: ${s.reason}`).join(' '), 'error'); payPeriod = period; payroll(); }
    });
    document.getElementById('pay-period')?.addEventListener('change', (e) => { payPeriod = e.target.value; payroll(); });
  }

  // ---------------------------------------------------------------- service desk
  function requestTable(rows) {
    return table([{ label: 'Ref', render: (r) => `<b>${esc(r.ref)}</b>` }, { label: 'Employee', render: (r) => esc(r.employee_name || '') }, { label: 'Type', render: (r) => esc(r.kind_label) },
      { label: 'Subject', render: (r) => esc(r.subject) }, { label: 'Amount', cls: 'n', render: (r) => (r.amount ? money(r.amount) : '') }, { label: 'Status', render: (r) => pill(r.status) },
      { label: 'Raised', render: (r) => date(r.created_at) }], rows, { empty: 'No requests.', onClick: (r) => { window.location.hash = `#/requests/${r.id}`; } });
  }

  let reqFilter = { status: 'active', kind: '' };
  async function requests() {
    loading('Service desk', '/requests');
    const d = await api(`/api/hr/requests?status=${reqFilter.status}&kind=${reqFilter.kind}`);
    view('Service desk', '/requests', `<div class="toolbar"><select class="input" id="rq-status">${options([{ value: 'active', label: 'Open & in progress' }, { value: 'approved', label: 'Approved' }, { value: 'resolved', label: 'Resolved' }, { value: 'rejected', label: 'Rejected' }, { value: 'all', label: 'All' }], reqFilter.status)}</select>
      <select class="input" id="rq-kind">${options(Object.entries(d.kinds).map(([k, v]) => ({ value: k, label: v })), reqFilter.kind, { blank: 'All types' })}</select></div>
      <div class="panel">${requestTable(d.requests)}</div>`);
    document.getElementById('rq-status').addEventListener('change', (e) => { reqFilter.status = e.target.value; requests(); });
    document.getElementById('rq-kind').addEventListener('change', (e) => { reqFilter.kind = e.target.value; requests(); });
  }

  async function requestDetail({ id }) {
    loading('Service desk', '/requests');
    const { request: r } = await api(`/api/hr/requests/${id}`);
    const open = ['open', 'in_progress'].includes(r.status);
    const approveLabel = { reimbursement: 'Approve claim', attendance_correction: 'Approve and correct attendance', document: 'Issue document', exit: 'Accept resignation', ticket: 'Mark resolved' }[r.kind];
    view(r.ref, '/requests', `<div class="grid-2"><div class="panel stack"><div class="spread"><div><h2>${esc(r.subject)}</h2><p class="muted" style="margin:.3rem 0 0">${esc(r.kind_label)} from <a href="#/employees/${r.employee_id}">${esc(r.employee_name)}</a> (${esc(r.employee_code)}) – ${date(r.created_at, true)}</p></div>${pill(r.status)}</div>
        ${r.description ? `<p style="white-space:pre-wrap">${esc(r.description)}</p>` : ''}
        <dl class="kv">${r.category ? `<dt>Category</dt><dd>${esc(r.category)}</dd>` : ''}${r.amount ? `<dt>Amount</dt><dd>${money(r.amount)}</dd>` : ''}
          ${Object.entries(r.payload || {}).map(([k, v]) => `<dt>${esc(label(k))}</dt><dd>${esc(v)}</dd>`).join('')}${r.attachment_key ? `<dt>Attachment</dt><dd><a href="/api/hr/requests/${r.id}/attachment" target="_blank" rel="noopener">Open attachment</a></dd>` : ''}
          ${r.resolution ? `<dt>Resolution</dt><dd>${esc(r.resolution)}</dd>` : ''}${r.handled_by ? `<dt>Handled by</dt><dd>${esc(r.handled_by)}</dd>` : ''}</dl>
        ${open ? `<form class="stack" id="resolve-form"><label class="field">Response to the employee<textarea class="input" name="resolution" rows="3"></textarea></label>
          <div class="row"><button class="btn mint" data-status="approved">${esc(approveLabel)}</button>${r.status === 'open' ? '<button class="btn ghost" data-status="in_progress">Mark in progress</button>' : ''}${r.kind !== 'ticket' ? '<button class="btn ghost" data-status="rejected">Reject</button>' : ''}</div></form>` : ''}
        <a class="btn ghost" href="#/requests" style="justify-self:start">Back to service desk</a></div>
      <div class="panel stack"><h3>Conversation</h3><div class="transcript">${r.comments.map((c) => `<article><b>${esc(c.author)}</b> <span class="faint">${esc(c.author_role)} – ${date(c.created_at, true)}</span><p>${esc(c.body)}</p></article>`).join('') || '<span class="faint">No messages yet.</span>'}</div>
        <form class="row" id="hr-comment"><input class="input" name="body" placeholder="Reply to the employee" style="flex:1"><button class="btn">Send</button></form></div></div>`);
    const form = document.getElementById('resolve-form');
    if (form) form.querySelectorAll('[data-status]').forEach((b) => b.addEventListener('click', async (e) => {
      e.preventDefault();
      const res = await act(b, 'Saving…', () => api(`/api/hr/requests/${id}/resolve`, { json: { status: b.dataset.status, resolution: form.resolution.value } }), 'Request updated and employee notified.');
      if (res) requestDetail({ id });
    }));
    const c = document.getElementById('hr-comment');
    c.addEventListener('submit', async (e) => { e.preventDefault(); const res = await act(c.querySelector('button'), 'Sending…', () => api(`/api/hr/requests/${id}/comments`, { json: H.formObject(c) })); if (res) requestDetail({ id }); });
  }

  // ---------------------------------------------------------------- policies
  async function policies() {
    loading('Policies', '/policies');
    const d = await api('/api/hr/policies');
    view('Policies', '/policies', `<div class="spread"><p class="muted" style="margin:0">Employees read these in their portal, and the HR assistant answers questions from them word for word.</p><button class="btn" id="new-policy">New policy</button></div>
      <div class="stack">${d.policies.map((p) => `<details class="policy"><summary><span>${esc(p.title)}</span><span class="row"><span class="faint">${esc(p.category)} – updated ${date(p.updated_at)}</span><button class="btn ghost small" data-edit="${p.id}">Edit</button></span></summary><div>${esc(p.body)}</div></details>`).join('')}</div>`);
    const dialog = (p) => formDialog(p ? `Edit ${p.title}` : 'New policy', `<div class="two"><label class="field">Title<input class="input" name="title" required value="${esc(p ? p.title : '')}"></label>
      <label class="field">Category<input class="input" name="category" value="${esc(p ? p.category : 'General')}"></label></div>
      <label class="field">Policy text <span class="hint">one rule per line works best for the assistant</span><textarea class="input" name="body" rows="12">${esc(p ? p.body : '')}</textarea></label>
      ${p ? '<button type="button" class="btn ghost small" id="del-policy" style="justify-self:start">Delete policy</button>' : ''}`, 'Save policy', async (data) => {
      if (p) await api(`/api/hr/policies/${p.id}`, { method: 'PUT', json: data }); else await api('/api/hr/policies', { json: data });
      toast('Policy saved.', 'ok'); policies(); return true;
    }, { wide: true });
    document.getElementById('new-policy').addEventListener('click', () => dialog(null));
    content.querySelectorAll('[data-edit]').forEach((b) => b.addEventListener('click', (e) => {
      e.preventDefault();
      const p = d.policies.find((x) => String(x.id) === b.dataset.edit);
      const dlg = dialog(p);
      dlg.querySelector('#del-policy')?.addEventListener('click', async () => { if (await confirmDialog('Delete this policy?', 'Employees and the assistant will no longer see it.', 'Delete')) { await api(`/api/hr/policies/${p.id}`, { method: 'DELETE' }); dlg.close(); policies(); } });
    }));
  }

  // ---------------------------------------------------------------- talent & performance
  async function talent() {
    loading('Talent & skills', '/talent');
    const [map, roles] = await Promise.all([api('/api/hr/talent/skills'), api('/api/hr/recruitment/openings')]);
    view('Talent & skills', '/talent', `<div class="panel stack"><h3>Find people inside Kairoz first</h3><p class="muted" style="margin:0">Search existing employees by the skills a project or opening needs, before hiring externally.</p>
        <form class="stack" id="talent-form"><div class="two"><label class="field">Required skills <span class="hint">comma separated</span><input class="input" name="required" placeholder="Python, Machine Learning, AWS"></label>
          <label class="field">Or use an opening's skills<select class="input" name="role_key">${options(roles.openings, '', { valueKey: 'key', labelKey: 'title', blank: 'Choose an opening' })}</select></label></div>
          <label class="field">Nice to have<input class="input" name="nice_to_have" placeholder="Docker, MLOps"></label><button class="btn" style="justify-self:start">Search employees</button></form>
        <div id="talent-results"></div></div>
      <div class="grid-2"><div class="panel"><h3>Top skills across the company</h3><div style="margin-top:12px">${bars(map.top_skills.slice(0, 12).map((s) => ({ label: s.skill, value: s.employees, max: Math.max(1, map.total_employees), text: `${s.employees} people` })))}</div></div>
        <div class="panel"><h3>Skills by department</h3>${Object.entries(map.departments).map(([dep, skills]) => `<h4 style="margin-top:12px">${esc(dep)}</h4><div class="chips">${skills.map((s) => `<span class="chip">${esc(s.skill)} ${s.employees}</span>`).join('')}</div>`).join('') || '<div class="empty">No employees yet.</div>'}</div></div>`);
    document.getElementById('talent-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const r = await act(e.target.querySelector('button'), 'Searching…', () => api('/api/hr/talent/search', { json: H.formObject(e.target) }));
      if (!r) return;
      const card = (x) => `<div class="panel" style="box-shadow:inset 0 0 0 1.5px var(--line)"><div class="spread"><div><a href="#/employees/${x.id}"><b>${esc(x.name)}</b></a><div class="faint">${esc(x.designation)}, ${esc(x.department)}${x.rating ? ` – rated ${x.rating}/5` : ''}</div></div>${pill(x.coverage === 100 ? 'ok' : 'wait', `${x.coverage}% match`)}</div>
        <div class="chips">${x.matched.map((s) => `<span class="chip hit">${esc(s)}</span>`).join('')}${x.missing.map((s) => `<span class="chip miss">${esc(s)}</span>`).join('')}</div>
        ${x.training.length ? `<ul class="faint" style="margin:.5rem 0 0">${x.training.map((t) => `<li>${esc(t.skill)}: ${esc(t.suggestion)}</li>`).join('')}</ul>` : ''}</div>`;
      document.getElementById('talent-results').innerHTML = `<h4>Ready now (${r.ready.length})</h4><div class="grid-2">${r.ready.map(card).join('') || '<p class="faint">Nobody covers every skill yet.</p>'}</div>
        <h4 style="margin-top:14px">Could be ready with training (${r.trainable.length})</h4><div class="grid-2">${r.trainable.map(card).join('') || '<p class="faint">No close matches.</p>'}</div>`;
    });
  }

  async function performance() {
    loading('Performance', '/performance');
    const [due, intel] = await Promise.all([api('/api/hr/performance/due'), api('/api/hr/performance/intelligence')]);
    view('Performance', '/performance', `<div class="panel"><h3>Check-ins due</h3><p class="faint">3, 6 and 12 months after joining. Managers can record them from their team page; HR from the employee profile.</p>${table([
        { label: 'Employee', render: (x) => `<b>${esc(x.full_name)}</b> <span class="faint">${esc(x.employee_code)}</span>` }, { label: 'Designation', render: (x) => esc(x.designation) },
        { label: 'Check-in', render: (x) => esc(x.period_label) }, { label: 'Due', render: (x) => date(x.due_on) },
        { label: '', render: (x) => `<button class="btn small" data-review="${x.id}" data-name="${esc(x.full_name)}">Record</button>` }], due.due, { empty: 'No check-ins due.' })}</div>
      <div class="panel"><h3>Recruitment intelligence</h3><p class="muted">How well did each recruitment signal predict on-the-job ratings for the ${intel.hires_with_reviews} reviewed hire(s) made through this portal? ${esc(intel.note)}</p>
        ${table([{ label: 'Recruitment signal', render: (s) => `<b>${esc(s.signal)}</b>` }, { label: 'Hires', cls: 'n', render: (s) => s.n },
          { label: 'Correlation with performance', cls: 'n', render: (s) => (s.correlation === null ? '<span class="faint">not enough data</span>' : `<b>${s.correlation > 0 ? '+' : ''}${s.correlation}</b>`) },
          { label: 'Strength', render: (s) => (s.strength ? pill(s.strength === 'strong' ? 'ok' : s.strength === 'moderate' ? 'info' : 'wait', s.strength) : '') }], intel.signals)}
        ${intel.people.length ? `<h4 style="margin-top:16px">Reviewed hires</h4>${table([{ label: 'Employee', render: (p) => esc(p.name) }, { label: 'Role', render: (p) => esc(p.role) },
          { label: 'Avg rating', cls: 'n', render: (p) => fmt(p.rating) }, { label: 'ATS', cls: 'n', render: (p) => fmt(p.ats) }, { label: 'Test', cls: 'n', render: (p) => fmt(p.test) }, { label: 'Interview', cls: 'n', render: (p) => fmt(p.interview) }], intel.people)}` : ''}</div>`);
    content.querySelectorAll('[data-review]').forEach((b) => b.addEventListener('click', () => reviewDialog(b.dataset.review, b.dataset.name)));
  }

  // ---------------------------------------------------------------- admin
  async function access() {
    loading('Access & accounts', '/access');
    const d = await api('/api/hr/accounts');
    view('Access & accounts', '/access', `<div class="spread"><p class="muted" style="margin:0">Every person signs in with a unique user ID. Employee accounts are created at onboarding; add HR colleagues here.</p><button class="btn" id="new-hr">Add HR user</button></div>
      <div class="panel">${table([{ label: 'User ID', render: (a) => `<b>${esc(a.user_id)}</b>` }, { label: 'Name', render: (a) => `${esc(a.full_name)}<div class="faint">${esc(a.email)}</div>` },
        { label: 'Role', render: (a) => esc({ hr_admin: 'HR administrator', hr: 'HR', employee: 'Employee' }[a.role]) },
        { label: 'Status', render: (a) => (a.is_active ? (a.must_change_password ? pill('wait', 'temporary password') : pill('active')) : pill('exited', 'deactivated')) + (a.locked_until && new Date(a.locked_until) > new Date() ? ` ${pill('no', 'locked')}` : '') },
        { label: 'Last sign-in', render: (a) => date(a.last_login_at, true) },
        { label: '', render: (a) => (a.id === me.id ? '<span class="faint">you</span>' : `<div class="row"><button class="btn ghost small" data-reset="${a.id}">Reset password</button><button class="btn ghost small" data-toggle="${a.id}" data-active="${a.is_active}">${a.is_active ? 'Deactivate' : 'Reactivate'}</button></div>`) }], d.accounts)}</div>`);
    document.getElementById('new-hr').addEventListener('click', () => formDialog('Add HR user', `<div class="two"><label class="field">Full name<input class="input" name="full_name" required></label><label class="field">Work email<input class="input" type="email" name="email" required></label></div>
      <label class="field">Role<select class="input" name="role">${options([{ value: 'hr', label: 'HR' }, ...(me.role === 'hr_admin' ? [{ value: 'hr_admin', label: 'HR administrator' }] : [])])}</select></label>
      <p class="faint">They receive a KZH user ID and a temporary password by email.</p>`, 'Create and email', async (data) => { const r = await api('/api/hr/accounts', { json: data }); toast(r.message, 'ok'); access(); return true; }));
    content.querySelectorAll('[data-reset]').forEach((b) => b.addEventListener('click', async () => { if (await confirmDialog('Reset password?', 'A temporary password is emailed; all their sessions are signed out.', 'Reset')) act(b, 'Resetting…', () => api(`/api/hr/accounts/${b.dataset.reset}/reset-password`, { method: 'POST' }), 'Temporary password emailed.'); }));
    content.querySelectorAll('[data-toggle]').forEach((b) => b.addEventListener('click', async () => { const r = await act(b, 'Saving…', () => api(`/api/hr/accounts/${b.dataset.toggle}/active`, { json: { active: b.dataset.active !== '1' } }), 'Account updated.'); if (r) access(); }));
  }

  async function emails() {
    loading('Email log', '/emails');
    const d = await api('/api/hr/recruitment/emails');
    view('Email log', '/emails', `<div class="panel">${table([{ label: 'Sent', render: (e) => date(e.created_at, true) }, { label: 'To', render: (e) => esc(e.recipient) }, { label: 'Email', render: (e) => esc(e.subject) },
      { label: 'Via', render: (e) => esc(e.backend) }, { label: 'Status', render: (e) => pill(e.status === 'sent' ? 'ok' : 'no', e.status) + (e.error ? `<div class="faint">${esc(e.error)}</div>` : '') }], d.emails, { empty: 'No emails yet.' })}</div>`);
  }

  async function audit() {
    loading('Audit log', '/audit');
    const d = await api('/api/hr/audit');
    view('Audit log', '/audit', `<div class="panel"><p class="faint">Who did what: sign-ins, profile views, salary changes, approvals and account changes.</p>${table([{ label: 'When', render: (e) => date(e.created_at, true) }, { label: 'Actor', render: (e) => esc(e.actor) },
      { label: 'Action', render: (e) => esc(label(e.action)) }, { label: 'Record', render: (e) => `${esc(e.entity)} ${esc(e.entity_id)}` }, { label: 'Detail', render: (e) => `<span class="faint">${esc(JSON.stringify(e.detail || {})).slice(0, 140)}</span>` }], d.events)}</div>`);
  }

  boot();
})();
