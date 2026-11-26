/* HR board: candidates grouped by pipeline step, detail drawer, email log. */
(function () {
  'use strict';
  const { esc, api, toast, logout, fmt } = window.HRM;
  const $ = (id) => document.getElementById(id);
  let data = null;

  // Board columns follow the hiring journey.
  const COLUMNS = [
    { key: 'resume', title: 'Resume screen', stages: ['screening', 'ats_rejected'] },
    { key: 'test', title: 'Mock test', stages: ['test_pending', 'test_in_progress', 'test_rejected'] },
    { key: 'interview', title: 'Interview', stages: ['interview_pending', 'interview_in_progress', 'interview_rejected'] },
    { key: 'done', title: 'Cleared – next steps', stages: ['interview_passed'] },
  ];

  $('logout-btn').addEventListener('click', logout);
  $('reload').addEventListener('click', load);
  $('role-filter').addEventListener('change', load);
  $('search').addEventListener('input', drawBoard);
  $('scrim').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
  document.querySelectorAll('[data-tab]').forEach((tab) => tab.addEventListener('click', () => {
    document.querySelectorAll('[data-tab]').forEach((t) => t.setAttribute('aria-selected', String(t === tab)));
    $('tab-board').classList.toggle('hidden', tab.dataset.tab !== 'board');
    $('tab-emails').classList.toggle('hidden', tab.dataset.tab !== 'emails');
    if (tab.dataset.tab === 'emails') loadEmails();
  }));

  async function load() {
    try {
      if (!$('me-email').textContent) {
        const me = await api('/api/auth/me');
        $('me-email').textContent = me.email;
        $('me-avatar').textContent = me.email.slice(0, 1).toUpperCase();
      }
      data = await api(`/api/hr/overview?role=${encodeURIComponent($('role-filter').value)}`);
      if ($('role-filter').options.length === 1) {
        data.roles.forEach((r) => { const o = document.createElement('option'); o.value = r.key; o.textContent = r.title; $('role-filter').appendChild(o); });
      }
      const t = data.thresholds;
      $('rules').textContent = `Pass marks: resume ATS ${fmt(t.ats)}, mock test ${fmt(t.test)}%, interview ${fmt(t.interview)}.`;
      drawStats();
      drawBoard();
    } catch (error) { toast(error.message, 'error'); }
  }

  function drawStats() {
    const apps = data.applications;
    const count = (stages) => apps.filter((a) => stages.includes(a.stage.key)).length;
    const items = [
      ['s1', apps.length, 'Applications'],
      ['s2', count(['test_pending', 'test_in_progress', 'interview_pending', 'interview_in_progress', 'test_rejected', 'interview_rejected', 'interview_passed']), 'Cleared the resume screen'],
      ['s3', count(['interview_pending', 'interview_in_progress', 'interview_rejected', 'interview_passed']), 'Reached the interview'],
      ['s4', count(['interview_passed']), 'Ready for next steps'],
    ];
    $('stats').innerHTML = items.map(([cls, n, label]) => `<div class="stat ${cls}"><b>${n}</b><span>${label}</span></div>`).join('');
  }

  function scorePill(label, value, pass) {
    if (value === null || value === undefined) return '';
    return `<span class="pill ${Number(value) >= pass ? 'ok' : 'no'}">${label} ${fmt(value)}</span>`;
  }

  function drawBoard() {
    if (!data) return;
    const q = $('search').value.trim().toLowerCase();
    const apps = data.applications.filter((a) => !q || a.full_name.toLowerCase().includes(q) || a.email.includes(q));
    const t = data.thresholds;
    $('board').innerHTML = COLUMNS.map((col) => {
      const rows = apps.filter((a) => col.stages.includes(a.stage.key));
      return `<div class="column"><header>${col.title}<span>${rows.length}</span></header>
        ${rows.map((a) => `<button class="cand tone-${a.stage.tone}" data-id="${a.id}">
          <div class="n">${esc(a.full_name || a.email)}</div>
          <div class="r">${esc(a.role_title)} – ${esc(a.stage.label)}</div>
          <div class="scores">${scorePill('ATS', a.ats_score, t.ats)}${scorePill('Test', a.test_percent, t.test)}${scorePill('Interview', a.interview_score, t.interview)}</div>
        </button>`).join('') || '<div class="empty" style="padding:16px 6px">No candidates here yet</div>'}
      </div>`;
    }).join('');
    document.querySelectorAll('.cand').forEach((b) => b.addEventListener('click', () => openDrawer(Number(b.dataset.id))));
  }

  function bullets(items) {
    const rows = (items || []).filter(Boolean);
    return rows.length ? `<ul style="margin:.3rem 0 0;padding-left:1.1rem">${rows.slice(0, 6).map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '<span class="faint">None</span>';
  }

  function integrityLine(integrity) {
    if (!integrity) return '<span class="faint">No data</span>';
    const parts = [];
    if (integrity.tab_switches !== undefined) parts.push(`${integrity.tab_switches} tab switch(es)`);
    if (integrity.copy_attempts) parts.push(`${integrity.copy_attempts} copy attempt(s)`);
    if (integrity.paste_events) parts.push(`${integrity.paste_events} paste(s)`);
    if (integrity.late_submission) parts.push('submitted after the time limit');
    return esc(parts.join(', ') || 'No flags');
  }

  async function openDrawer(id) {
    let app;
    try { app = (await api(`/api/hr/applications/${id}`)).application; } catch (error) { toast(error.message, 'error'); return; }
    const ats = app.ats_report || {};
    const test = app.test;
    const iv = app.interview;
    const when = (v) => (v ? new Date(v).toLocaleString() : '–');
    $('drawer').innerHTML = `
      <div class="drawer-head"><div><h2 id="drawer-title">${esc(app.full_name)}</h2>
        <span class="faint">${esc(app.role_title)} – ${esc(app.stage.label)}</span></div>
        <button class="btn ghost small" id="close-drawer">Close</button></div>
      <div class="drawer-body">
        <section><dl class="kv">
          <dt>Email</dt><dd>${esc(app.email)}</dd>
          <dt>Phone</dt><dd>${esc(app.phone || '–')}</dd>
          <dt>Experience</dt><dd>${fmt(app.experience_years)} years</dd>
          <dt>Applied</dt><dd>${when(app.created_at)}</dd>
          <dt>Resume</dt><dd><a href="/api/hr/applications/${app.id}/resume">${esc(app.resume_name)}</a></dd>
        </dl></section>

        <section><h3>Resume screen – ATS ${fmt(app.ats_score)}</h3>
          ${(ats.score_breakdown || []).map((b) => `<div class="bar-row" style="margin-bottom:8px"><header><span>${esc(b.name)}</span><span>${b.points} / ${b.max}</span></header><div class="bar"><i style="width:${Math.round((b.points / b.max) * 100)}%"></i></div></div>`).join('')}
          <p class="faint" style="margin:.4rem 0 0">Role profile: ${esc(ats.role_profile || '–')}, confidence ${esc(ats.confidence_label || '–')}</p>
          <div class="chips">${(ats.matched_keywords || []).slice(0, 14).map((k) => `<span class="chip hit">${esc(k)}</span>`).join('')}${(ats.missing_keywords || []).slice(0, 10).map((k) => `<span class="chip miss">${esc(k)}</span>`).join('')}</div>
        </section>

        <section><h3>Mock test${test && test.percent !== null && test.percent !== undefined ? ` – ${fmt(test.percent)}%` : ''}</h3>
          ${test ? `<dl class="kv"><dt>Status</dt><dd>${esc(test.status)}</dd><dt>Started</dt><dd>${when(test.started_at)}</dd><dt>Finished</dt><dd>${when(test.completed_at)}</dd><dt>Integrity</dt><dd>${integrityLine(test.integrity)}</dd></dl>
            ${(test.scorecard.topic_breakdown || []).map((t) => `<div class="bar-row" style="margin-top:8px"><header><span>${esc(t.label)}</span><span>${t.correct} / ${t.total}</span></header><div class="bar"><i style="width:${t.percent}%"></i></div></div>`).join('')}` : '<span class="faint">Not started</span>'}
        </section>

        <section><h3>Interview${iv && iv.score !== null && iv.score !== undefined ? ` – ${fmt(iv.score)}` : ''}</h3>
          ${iv ? `<dl class="kv"><dt>Status</dt><dd>${esc(iv.status)}</dd><dt>Finished</dt><dd>${when(iv.completed_at)}</dd><dt>Integrity</dt><dd>${integrityLine(iv.integrity)}</dd></dl>
            ${iv.report && iv.report.summary ? `<p style="margin-top:.8rem">${esc(iv.report.summary)}</p>` : ''}
            ${Object.entries((iv.report || {}).rubric || {}).map(([k, v]) => `<div class="bar-row" style="margin-top:8px"><header><span>${esc(k)}</span><span>${v}</span></header><div class="bar"><i style="width:${v}%"></i></div></div>`).join('')}
            <div class="lists" style="margin-top:14px"><div><b>Strengths</b>${bullets((iv.report || {}).strengths)}</div><div><b>Weaknesses</b>${bullets((iv.report || {}).weaknesses)}</div></div>
            <h3 style="margin-top:18px">Transcript</h3><div class="transcript">${(iv.transcript || []).map((t) => `<article><b>${esc(t.question)}</b>
              ${t.answer_type === 'code' ? `<pre class="code"><code>${esc(t.answer)}</code></pre>` : `<p>${esc(t.answer || '(no answer)')}</p>`}</article>`).join('') || '<span class="faint">No answers yet</span>'}</div>` : '<span class="faint">Not started</span>'}
        </section>

        <section><h3>Emails</h3>
          <table class="log"><tr><th>Sent</th><th>Email</th><th>Status</th></tr>
          ${app.emails.map((e) => `<tr><td>${when(e.created_at)}</td><td>${esc(e.subject)}</td><td><span class="pill ${e.status === 'sent' ? 'ok' : 'no'}">${esc(e.status)}</span></td></tr>`).join('') || '<tr><td colspan="3" class="faint">None yet</td></tr>'}</table>
        </section>

        <section><h3>Timeline</h3><ol class="timeline">${app.events.map((e) => `<li><b>${esc(e.event.replace(/_/g, ' '))}</b> <span class="faint">${when(e.created_at)}</span>${e.detail && e.detail.score !== undefined ? ` – score ${fmt(e.detail.score)}` : ''}${e.detail && e.detail.percent !== undefined ? ` – ${fmt(e.detail.percent)}%` : ''}</li>`).join('')}</ol></section>
      </div>`;
    $('close-drawer').addEventListener('click', closeDrawer);
    $('drawer').classList.add('open');
    $('drawer').setAttribute('aria-hidden', 'false');
    $('scrim').classList.remove('hidden');
    $('close-drawer').focus();
  }

  function closeDrawer() {
    $('drawer').classList.remove('open');
    $('drawer').setAttribute('aria-hidden', 'true');
    $('scrim').classList.add('hidden');
  }

  async function loadEmails() {
    try {
      const result = await api('/api/hr/emails');
      $('email-backend').textContent = data && data.email_backend === 'console'
        ? 'Email backend: console. Emails are printed in the server terminal and saved to data/outbox; set SMTP settings in .env to send real emails.'
        : 'Email backend: SMTP.';
      $('email-table').innerHTML = `<tr><th>Sent</th><th>To</th><th>Email</th><th>Status</th></tr>${result.emails.filter((e) => e.kind !== 'otp').map((e) => `
        <tr><td>${new Date(e.created_at).toLocaleString()}</td><td>${esc(e.recipient)}</td><td>${esc(e.subject)}</td>
        <td><span class="pill ${e.status === 'sent' ? 'ok' : 'no'}">${esc(e.status)}</span>${e.error ? `<div class="faint">${esc(e.error)}</div>` : ''}</td></tr>`).join('') || '<tr><td colspan="4" class="faint">No emails yet</td></tr>'}`;
    } catch (error) { toast(error.message, 'error'); }
  }

  load();
})();
