/* Candidate app: apply with a resume, follow the journey, take the mock test and the interview. */
(function () {
  'use strict';
  const { esc, api, toast, busy, confetti, confirmDialog, logout, fmt, dial, animateIn } = window.HRM;
  const main = document.getElementById('main');
  const focus = document.getElementById('focus');
  const state = { me: null, roles: [], thresholds: {}, apps: [], currentId: null, view: 'app' };

  const PASSED_ATS = ['test_pending', 'test_in_progress', 'test_rejected', 'interview_pending', 'interview_in_progress', 'interview_rejected', 'interview_passed'];
  const PASSED_TEST = ['interview_pending', 'interview_in_progress', 'interview_rejected', 'interview_passed'];

  document.getElementById('logout-btn').addEventListener('click', logout);

  // ------------------------------------------------------------------ boot
  async function boot() {
    try {
      const [me, roles, apps] = await Promise.all([api('/api/auth/me'), api('/api/roles'), api('/api/applications')]);
      state.me = me;
      state.roles = roles.roles;
      state.thresholds = roles.thresholds;
      state.apps = apps.applications;
      document.getElementById('me-email').textContent = me.email;
      document.getElementById('me-avatar').textContent = me.email.slice(0, 1).toUpperCase();
      if (state.apps.length) { state.currentId = state.apps[0].id; renderApplication(); } else { renderApply(); }
    } catch (error) {
      main.innerHTML = `<div class="panel empty">${esc(error.message)}</div>`;
    }
  }

  async function refresh(id) {
    const [roles, apps] = await Promise.all([api('/api/roles'), api('/api/applications')]);
    state.roles = roles.roles;
    state.apps = apps.applications;
    state.currentId = id || state.currentId || (state.apps[0] && state.apps[0].id);
    renderApplication();
  }

  const current = () => state.apps.find((a) => a.id === state.currentId) || state.apps[0];

  // ------------------------------------------------------------------ apply
  function renderApply() {
    state.view = 'apply';
    const open = state.roles.filter((r) => !r.applied);
    const back = state.apps.length ? '<button class="btn ghost" id="back-apps">Back to my applications</button>' : '';
    main.innerHTML = `
      <div class="page-head">
        <div><h1>${state.apps.length ? 'Apply for another role' : 'Pick a role and upload your resume'}</h1>
        <p class="muted">Your resume is scored against the role's requirements. A score of ${fmt(state.thresholds.ats)} or more unlocks the mock test.</p></div>
        ${back}
      </div>
      <div class="apply-grid">
        <section class="panel">
          <h2 style="margin-bottom:14px">Open roles</h2>
          <div class="role-list" role="list">
            ${state.roles.map((r) => `
              <button class="role" role="listitem" data-key="${esc(r.key)}" aria-pressed="false" ${r.applied ? 'disabled' : ''}>
                <span class="title">${esc(r.title)}</span>
                <span class="meta">${esc(r.department)}, ${esc(r.location)}${r.applied ? ' – already applied' : ''}</span>
                <span class="exp">${esc(r.experience)}</span>
              </button>`).join('')}
          </div>
        </section>
        <section class="panel">
          <h2 id="apply-title" style="margin-bottom:12px">${open.length ? 'Choose a role' : 'You have applied for every open role'}</h2>
          <div id="role-detail" class="role-detail hidden"></div>
          <form class="apply" id="apply-form" novalidate>
            <input type="hidden" name="role_key" id="role-key">
            <label class="field">Full name <input class="input" name="full_name" autocomplete="name" required></label>
            <div class="two">
              <label class="field">Years of experience <input class="input" name="experience_years" type="number" min="0" max="50" step="0.5" value="0"></label>
              <label class="field">Phone (optional) <input class="input" name="phone" autocomplete="tel"></label>
            </div>
            <div class="drop" id="drop" tabindex="0" role="button" aria-label="Upload resume">
              <strong id="drop-title">Drop your resume here or click to browse</strong>
              <span class="faint" id="drop-sub">PDF, DOCX, TXT or MD – up to 5 MB</span>
              <input type="file" id="file" name="resume" accept=".pdf,.docx,.txt,.md" hidden>
            </div>
            <button class="btn" type="submit" id="apply-btn" disabled>Submit application</button>
          </form>
        </section>
      </div>`;
    if (state.apps.length) document.getElementById('back-apps').addEventListener('click', () => renderApplication());

    const form = document.getElementById('apply-form');
    const fileInput = document.getElementById('file');
    const drop = document.getElementById('drop');
    let file = null;
    const ready = () => { document.getElementById('apply-btn').disabled = !(file && form.role_key.value); };

    main.querySelectorAll('.role:not([disabled])').forEach((button) => button.addEventListener('click', () => {
      main.querySelectorAll('.role').forEach((b) => b.setAttribute('aria-pressed', 'false'));
      button.setAttribute('aria-pressed', 'true');
      const role = state.roles.find((r) => r.key === button.dataset.key);
      form.role_key.value = role.key;
      document.getElementById('apply-title').textContent = role.title;
      const detail = document.getElementById('role-detail');
      detail.innerHTML = `<p style="margin:0 0 .6rem">${esc(role.description)}</p><div class="chips">${role.skills.map((s) => `<span class="chip">${esc(s)}</span>`).join('')}</div>`;
      detail.classList.remove('hidden');
      ready();
    }));

    const pick = (picked) => {
      if (!picked) return;
      file = picked;
      drop.classList.add('filled');
      document.getElementById('drop-title').textContent = picked.name;
      document.getElementById('drop-sub').textContent = `${(picked.size / 1024).toFixed(0)} KB – click to change`;
      ready();
    };
    drop.addEventListener('click', () => fileInput.click());
    drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); } });
    fileInput.addEventListener('change', () => pick(fileInput.files[0]));
    ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', (e) => pick(e.dataTransfer.files[0]));

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (form.full_name.value.trim().length < 2) { toast('Enter your full name.', 'error'); form.full_name.focus(); return; }
      const body = new FormData(form);
      body.set('resume', file);
      const overlay = showScan();
      busy(document.getElementById('apply-btn'), true, 'Scoring…');
      try {
        const [data] = await Promise.all([api('/api/applications', { method: 'POST', body }), overlay.minimum]);
        overlay.close();
        await refresh(data.application.id);
        const passed = data.application.stage.key === 'test_pending';
        if (passed) { confetti(); toast('You cleared the resume screen. The mock test is unlocked.', 'ok'); }
        else toast('Your result is ready. We have also emailed it to you.');
      } catch (error) {
        overlay.close();
        toast(error.message, 'error');
        busy(document.getElementById('apply-btn'), false);
      }
    });
  }

  function showScan() {
    const node = document.createElement('div');
    node.className = 'scan';
    node.innerHTML = `<div class="scan-card" role="status">
      <div class="paper" aria-hidden="true">${[18, 34, 50, 66, 82, 98, 114, 130].map((t, i) => `<i style="top:${t}px;right:${16 + (i % 3) * 18}px"></i>`).join('')}<div class="beam"></div></div>
      <h3>Scoring your resume</h3>
      <ul class="scan-steps">
        <li>Reading your resume</li><li>Matching skills to the role</li><li>Checking experience and impact</li><li>Reviewing structure and writing</li>
      </ul></div>`;
    document.body.appendChild(node);
    const steps = node.querySelectorAll('li');
    let i = 0;
    steps[0].classList.add('on');
    const timer = setInterval(() => { i = Math.min(i + 1, steps.length - 1); steps[i].classList.add('on'); }, 650);
    return {
      minimum: new Promise((r) => setTimeout(r, 2600)),
      close: () => { clearInterval(timer); node.remove(); },
    };
  }

  // ------------------------------------------------------------------ application view
  function stations(app) {
    const s = app.stage.key;
    const t = app.thresholds;
    const atsNote = app.ats ? `ATS ${fmt(app.ats.score)} / ${fmt(t.ats)}` : 'Scoring…';
    const testNote = app.test && app.test.percent !== null && app.test.percent !== undefined ? `${fmt(app.test.percent)}% / ${fmt(t.test)}%` : `Pass mark ${fmt(t.test)}%`;
    const ivNote = app.interview && app.interview.score !== null && app.interview.score !== undefined ? `${fmt(app.interview.score)} / ${fmt(t.interview)}` : `Pass mark ${fmt(t.interview)}`;
    const list = [
      { name: 'Resume screen', note: atsNote, cls: s === 'ats_rejected' ? 'stopped' : PASSED_ATS.includes(s) ? 'done' : 'current' },
      { name: 'Mock test', note: PASSED_ATS.includes(s) ? testNote : '', cls: s === 'test_rejected' ? 'stopped' : PASSED_TEST.includes(s) ? 'done' : ['test_pending', 'test_in_progress'].includes(s) ? `current ${s === 'test_pending' ? 'action' : ''}` : '' },
      { name: 'Interview', note: PASSED_TEST.includes(s) ? ivNote : '', cls: s === 'interview_rejected' ? 'stopped' : s === 'interview_passed' ? 'done' : ['interview_pending', 'interview_in_progress'].includes(s) ? `current ${s === 'interview_pending' ? 'action' : ''}` : '' },
      { name: 'Next steps', note: s === 'interview_passed' ? 'HR will contact you' : '', cls: s === 'interview_passed' ? 'finished' : '' },
    ];
    const reached = Math.max(0, list.map((x) => x.cls).reduce((acc, cls, idx) => (cls ? idx : acc), 0));
    const stopped = list.some((x) => x.cls === 'stopped');
    const icons = ['1', '2', '3', '4'];
    return `<div class="journey ${stopped ? 'stopped' : ''}" aria-label="Application progress">
      <div class="fill" data-w="${(reached / 3) * 75}%"></div>
      ${list.map((x, i) => `<div class="station ${x.cls}">
        <span class="dot">${x.cls.includes('done') || x.cls === 'finished' ? '✓' : x.cls === 'stopped' ? '✕' : icons[i]}</span>
        <span class="name">${x.name}</span><span class="note">${esc(x.note)}</span></div>`).join('')}
    </div>`;
  }

  function stageBand(app) {
    const s = app.stage.key;
    const t = app.thresholds;
    const role = esc(app.role_title);
    const bands = {
      test_pending: ['action', 'You are shortlisted for the mock test', `A timed multiple-choice test on the skills a ${role} needs. Score ${fmt(t.test)}% or more to reach the interview. The timer starts when you begin, so pick a quiet moment.`, '<button class="btn" data-act="test">Start mock test</button>'],
      test_in_progress: ['active', 'Your mock test is running', 'Your answers are saved as you go. Pick up where you left off before the timer runs out.', '<button class="btn" data-act="test">Resume mock test</button>'],
      interview_pending: ['action', 'You are through to the interview', `Questions are based on the ${role} role. Answer by typing or speaking; coding questions open an editor. Score ${fmt(t.interview)} or more to clear this round.`, '<button class="btn" data-act="interview">Start interview</button>'],
      interview_in_progress: ['active', 'Your interview is in progress', 'Your answers are saved after every question. Continue whenever you are ready.', '<button class="btn" data-act="interview">Resume interview</button>'],
      ats_rejected: ['rejected', 'Thank you for applying', `Your resume scored below the ${fmt(t.ats)} needed for this role, so we are not moving forward this time. The suggestions below show what would strengthen it.`, ''],
      test_rejected: ['rejected', 'Thank you for taking the mock test', `Your score was below the ${fmt(t.test)}% needed for the interview round, so we are not moving forward this time.`, ''],
      interview_rejected: ['rejected', 'Thank you for attending the interview', `Your interview score was below ${fmt(t.interview)}, so we are not moving forward this time. We appreciate the effort you put into every round.`, ''],
      interview_passed: ['passed', 'Thank you for attending the interview', 'You cleared every round. Our HR team will review your results and share the next steps soon.', ''],
      screening: ['active', 'Scoring your resume', 'This takes a few seconds.', ''],
    };
    const [tone, title, text, action] = bands[s] || bands.screening;
    return `<div class="stage-band ${tone}"><div><h3>${title}</h3><p>${text}</p>
      ${['ats_rejected', 'test_rejected', 'interview_rejected', 'interview_passed', 'test_pending', 'interview_pending'].includes(s) ? '<p class="faint" style="margin-top:.5rem">We have emailed you this update.</p>' : ''}</div>${action}</div>`;
  }

  function list(items, empty) {
    const rows = (items || []).filter(Boolean);
    return rows.length ? `<ul>${rows.slice(0, 6).map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : `<p class="faint">${empty}</p>`;
  }

  function atsSection(app) {
    const ats = app.ats;
    if (!ats) return '';
    const passed = Number(ats.score) >= Number(app.thresholds.ats);
    return `<section class="panel"><h2>Resume screen</h2>
      <p class="muted" style="margin-top:.4rem">Scored against the ${esc(app.role_title)} requirements.</p>
      <div class="results">${dial(ats.score, app.thresholds.ats, passed ? '#12b886' : '#f0525c')}
        <div class="bars">${(ats.score_breakdown || []).map((b) => `<div class="bar-row"><header><span>${esc(b.name)}</span><span>${b.points} / ${b.max}</span></header>
          <div class="bar"><i data-w="${Math.round((b.points / b.max) * 100)}%"></i></div></div>`).join('')}
          <div><b style="font-size:.94rem">Skills found</b><div class="chips">${(ats.matched_keywords || []).slice(0, 14).map((k) => `<span class="chip hit">${esc(k)}</span>`).join('') || '<span class="faint">None matched</span>'}</div></div>
          ${(ats.missing_keywords || []).length ? `<div><b style="font-size:.94rem">Skills the role asks for that we could not find</b><div class="chips">${ats.missing_keywords.slice(0, 12).map((k) => `<span class="chip miss">${esc(k)}</span>`).join('')}</div></div>` : ''}
        </div></div>
      <div class="lists"><div><h3>What works</h3>${list(ats.strengths, 'Nothing stood out yet.')}</div>
        <div><h3>How to improve</h3>${list(ats.improvements, 'No major issues found.')}</div></div></section>`;
  }

  function testSection(app) {
    const test = app.test;
    if (!test || !test.summary) return '';
    const sum = test.summary;
    const passed = Number(sum.percent) >= Number(app.thresholds.test);
    return `<section class="panel"><h2>Mock test</h2>
      <p class="muted" style="margin-top:.4rem">${sum.correct} of ${sum.total} correct, ${sum.unanswered} unanswered.</p>
      <div class="results">${dial(sum.percent, app.thresholds.test, passed ? '#12b886' : '#f0525c')}
        <div class="bars">${(sum.topic_breakdown || []).map((t) => `<div class="bar-row"><header><span>${esc(t.label)}</span><span>${t.correct} / ${t.total}</span></header>
          <div class="bar"><i data-w="${Math.round(t.percent)}%" style="background:${t.percent >= 70 ? 'var(--mint)' : t.percent >= 40 ? 'var(--amber)' : 'var(--coral)'}"></i></div></div>`).join('')}</div></div></section>`;
  }

  function interviewSection(app) {
    const iv = app.interview;
    if (!iv || !iv.summary) return '';
    const sum = iv.summary;
    const passed = Number(sum.score) >= Number(app.thresholds.interview);
    return `<section class="panel"><h2>Interview</h2>
      <p class="muted" style="margin-top:.4rem">${sum.answered} of ${sum.question_count} questions answered.</p>
      <div class="results">${dial(sum.score, app.thresholds.interview, passed ? '#12b886' : '#f0525c')}
        <div class="bars">${Object.entries(sum.rubric || {}).map(([name, value]) => `<div class="bar-row"><header><span>${esc(name)}</span><span>${value}</span></header>
          <div class="bar"><i data-w="${value}%"></i></div></div>`).join('')}</div></div>
      <div class="lists"><div><h3>Strengths</h3>${list(sum.strengths, 'Keep answering with specific examples.')}</div>
        <div><h3>To work on</h3>${list(sum.improvements, 'No major gaps found.')}</div></div></section>`;
  }

  function renderApplication() {
    state.view = 'app';
    const app = current();
    if (!app) { renderApply(); return; }
    const canApplyMore = state.roles.some((r) => !r.applied);
    main.innerHTML = `
      <div class="page-head">
        <div><h1>${esc(app.role_title)}</h1><p class="muted">Applied ${new Date(app.created_at).toLocaleDateString()} with ${esc(app.resume_name)}</p></div>
        ${canApplyMore ? '<button class="btn ghost" id="apply-more">Apply for another role</button>' : ''}
      </div>
      ${state.apps.length > 1 ? `<div class="app-tabs" role="tablist">${state.apps.map((a) => `<button class="app-tab" role="tab" data-id="${a.id}" aria-selected="${a.id === app.id}">${esc(a.role_title)}</button>`).join('')}</div>` : ''}
      <section class="panel">${stations(app)}${stageBand(app)}</section>
      ${interviewSection(app)}${testSection(app)}${atsSection(app)}`;
    animateIn(main);
    const more = document.getElementById('apply-more');
    if (more) more.addEventListener('click', renderApply);
    main.querySelectorAll('.app-tab').forEach((tab) => tab.addEventListener('click', () => { state.currentId = Number(tab.dataset.id); renderApplication(); }));
    main.querySelectorAll('[data-act="test"]').forEach((b) => b.addEventListener('click', () => openTest(app, b)));
    main.querySelectorAll('[data-act="interview"]').forEach((b) => b.addEventListener('click', () => openInterview(app, b)));
  }

  // ------------------------------------------------------------------ focus mode helpers
  let leaveGuard = null;
  function enterFocus(html) {
    focus.innerHTML = html;
    focus.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    leaveGuard = (e) => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', leaveGuard);
  }
  function exitFocus() {
    focus.classList.add('hidden');
    focus.innerHTML = '';
    document.body.style.overflow = '';
    if (leaveGuard) window.removeEventListener('beforeunload', leaveGuard);
    leaveGuard = null;
  }

  // ------------------------------------------------------------------ mock test
  async function openTest(app, button) {
    if (app.stage.key === 'test_pending') {
      const ok = await confirmDialog('Start the mock test?', 'The timer starts as soon as you begin and keeps running if you close the tab. Your answers are saved as you go.', 'Start now');
      if (!ok) return;
    }
    busy(button, true, 'Preparing your test…');
    let test;
    try { test = (await api(`/api/applications/${app.id}/test/start`, { method: 'POST' })).test; } catch (error) {
      toast(error.message, 'error'); busy(button, false); await refresh(app.id); return;
    }
    busy(button, false);
    runTest(app, test);
  }

  function runTest(app, test) {
    const qs = test.questions;
    const answers = { ...(test.answers || {}) };
    const flagged = new Set();
    const integrity = { tab_switches: 0, copy_attempts: 0 };
    let index = Math.max(0, qs.findIndex((q) => answers[q.id] === undefined || answers[q.id] === null));
    let remaining = test.remaining_seconds;
    const total = test.time_limit_seconds;
    let saveTimer = null; let submitted = false; let clock = null;

    enterFocus(`
      <div class="focus-bar">
        <div><h3 id="focus-title">${esc(app.role_title)} mock test</h3><span class="faint">${qs.length} questions – pass mark ${fmt(app.thresholds.test)}%</span></div>
        <div class="timer" id="timer"><svg width="38" height="38" viewBox="0 0 38 38"><circle class="t-bg" cx="19" cy="19" r="15"/><circle class="t-fg" id="t-fg" cx="19" cy="19" r="15" stroke-dasharray="94.25"/></svg><span id="t-text">--:--</span></div>
        <button class="btn" id="submit-test">Submit test</button>
      </div>
      <div class="focus-body"><div class="test-layout">
        <aside class="qmap"><b>Questions</b><span class="faint" id="answered-count" style="display:block"></span><div class="qmap-grid" id="qmap"></div>
          <p class="faint" style="margin:12px 0 0">Keys 1–4 pick an answer, arrow keys move between questions.</p></aside>
        <section class="question-card" id="qcard" aria-live="polite"></section>
      </div></div>`);

    const tick = () => {
      remaining = Math.max(0, remaining - 1);
      const m = Math.floor(remaining / 60); const s = remaining % 60;
      document.getElementById('t-text').textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
      document.getElementById('t-fg').style.strokeDashoffset = String(94.25 * (1 - remaining / total));
      document.getElementById('timer').classList.toggle('low', remaining <= 60);
      if (remaining === 300) toast('5 minutes left.');
      if (remaining <= 0) { clearInterval(clock); submit(true); }
    };

    const autosave = () => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => api(`/api/applications/${app.id}/test/autosave`, { json: { answers, integrity } }).catch(() => {}), 800);
    };
    const onVisibility = () => { if (document.hidden) { integrity.tab_switches += 1; autosave(); } };
    const onCopy = (e) => { integrity.copy_attempts += 1; e.preventDefault(); };
    document.addEventListener('visibilitychange', onVisibility);
    focus.addEventListener('copy', onCopy);

    function drawMap() {
      document.getElementById('qmap').innerHTML = qs.map((q, i) => {
        const done = answers[q.id] !== undefined && answers[q.id] !== null;
        return `<button class="${done ? 'answered' : ''} ${flagged.has(q.id) ? 'flagged' : ''} ${i === index ? 'here' : ''}" data-i="${i}" aria-label="Question ${i + 1}${done ? ', answered' : ''}">${i + 1}</button>`;
      }).join('');
      const count = qs.filter((q) => answers[q.id] !== undefined && answers[q.id] !== null).length;
      document.getElementById('answered-count').textContent = `${count} of ${qs.length} answered`;
      document.querySelectorAll('#qmap button').forEach((b) => b.addEventListener('click', () => { index = Number(b.dataset.i); draw(); }));
    }

    function draw() {
      const q = qs[index];
      document.getElementById('qcard').innerHTML = `
        <div class="q-meta"><span class="pill">Question ${index + 1} of ${qs.length}</span><span class="pill">${esc(q.topic_label)}</span><span class="pill">${esc(q.difficulty)}</span></div>
        <div class="q-text">${esc(q.question)}</div>
        ${q.code ? `<pre class="code"><code>${esc(q.code)}</code></pre>` : ''}
        <div class="options" role="radiogroup" aria-label="Answer options">
          ${q.options.map((o, i) => `<button class="option" role="radio" aria-checked="${answers[q.id] === i}" data-i="${i}"><span class="key">${i + 1}</span><span>${esc(o)}</span></button>`).join('')}
        </div>
        <div class="q-nav">
          <button class="btn ghost" id="prev" ${index === 0 ? 'disabled' : ''}>Previous</button>
          <button class="btn ghost" id="flag">${flagged.has(q.id) ? 'Remove flag' : 'Flag for review'}</button>
          ${index < qs.length - 1 ? '<button class="btn" id="next">Next question</button>' : '<button class="btn mint" id="finish">Review and submit</button>'}
        </div>`;
      document.querySelectorAll('.option').forEach((b) => b.addEventListener('click', () => choose(Number(b.dataset.i))));
      document.getElementById('prev').addEventListener('click', () => move(-1));
      document.getElementById('flag').addEventListener('click', () => { flagged.has(q.id) ? flagged.delete(q.id) : flagged.add(q.id); draw(); });
      const next = document.getElementById('next'); if (next) next.addEventListener('click', () => move(1));
      const fin = document.getElementById('finish'); if (fin) fin.addEventListener('click', () => submit(false));
      drawMap();
    }

    function choose(i) { answers[qs[index].id] = i; autosave(); draw(); }
    function move(step) { index = Math.min(qs.length - 1, Math.max(0, index + step)); draw(); }

    const onKey = (e) => {
      if (focus.classList.contains('hidden') || document.querySelector('dialog[open]')) return;
      if (['1', '2', '3', '4'].includes(e.key)) choose(Number(e.key) - 1);
      if (e.key === 'ArrowRight') move(1);
      if (e.key === 'ArrowLeft') move(-1);
    };
    document.addEventListener('keydown', onKey);

    async function submit(auto) {
      if (submitted) return;
      const unanswered = qs.filter((q) => answers[q.id] === undefined || answers[q.id] === null).length;
      if (!auto) {
        const ok = await confirmDialog('Submit your test?', unanswered ? `${unanswered} question(s) are unanswered. You cannot change answers after submitting.` : 'You cannot change answers after submitting.', 'Submit test');
        if (!ok) return;
      }
      submitted = true;
      clearInterval(clock); clearTimeout(saveTimer);
      const button = document.getElementById('submit-test');
      busy(button, true, 'Grading…');
      try {
        const data = await api(`/api/applications/${app.id}/test/submit`, { json: { answers, integrity } });
        cleanup();
        await refresh(app.id);
        if (data.application.stage.key === 'interview_pending') { confetti(); toast('You passed the mock test. The interview is unlocked.', 'ok'); }
        else toast('Your test has been graded. We have emailed you the result.');
      } catch (error) {
        submitted = false; busy(button, false); toast(error.message, 'error');
      }
    }

    function cleanup() {
      document.removeEventListener('visibilitychange', onVisibility);
      document.removeEventListener('keydown', onKey);
      focus.removeEventListener('copy', onCopy);
      exitFocus();
    }
    document.getElementById('submit-test').addEventListener('click', () => submit(false));
    draw();
    remaining += 1; tick();  // paint the clock immediately (and auto-submit if time already ran out)
    if (!submitted) clock = setInterval(tick, 1000);
  }

  // ------------------------------------------------------------------ mock interview
  async function openInterview(app, button) {
    if (app.stage.key === 'interview_pending') {
      const ok = await confirmDialog('Start the interview?', 'You will get a set of questions for this role. Answers are saved after each question, so you can take your time.', 'Start interview');
      if (!ok) return;
    }
    busy(button, true, 'Preparing questions…');
    let interview;
    try { interview = (await api(`/api/applications/${app.id}/interview/start`, { method: 'POST' })).interview; } catch (error) {
      toast(error.message, 'error'); busy(button, false); await refresh(app.id); return;
    }
    busy(button, false);
    runInterview(app, interview);
  }

  function runInterview(app, interview) {
    const qs = interview.questions;
    const answers = {};
    Object.entries(interview.answers || {}).forEach(([id, a]) => { answers[id] = a.answer || ''; });
    const integrity = { tab_switches: 0, paste_events: 0 };
    let index = Math.max(0, qs.findIndex((q) => !(answers[q.id] || '').trim()));
    let voiceOn = 'speechSynthesis' in window;
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    let recognizer = null; let listening = false; let finished = false;

    enterFocus(`
      <div class="focus-bar">
        <div><h3 id="focus-title">${esc(app.role_title)} interview</h3><span class="faint">${qs.length} questions – pass mark ${fmt(app.thresholds.interview)}</span></div>
        <button class="btn ghost small" id="voice-toggle" ${'speechSynthesis' in window ? '' : 'disabled'}>${voiceOn ? 'Mute interviewer' : 'Unmute interviewer'}</button>
      </div>
      <div class="focus-body"><div class="studio">
        <aside class="interviewer"><div class="orb" id="orb"></div><div class="status" id="iv-status">Ready when you are</div>
          <div class="progress-dots" id="dots"></div>
          <p style="color:#9ea1c7;font-size:.86rem;margin:18px 0 0">Answer with a real example: the situation, what you did, and the result. Coding answers are reviewed for approach, correctness and complexity.</p></aside>
        <section class="question-card" id="iv-card" aria-live="polite"></section>
      </div></div>`);

    const save = () => api(`/api/applications/${app.id}/interview/autosave`, { json: { answers: { [qs[index].id]: answers[qs[index].id] || '' }, integrity } }).catch(() => {});
    const onVisibility = () => { if (document.hidden) integrity.tab_switches += 1; };
    document.addEventListener('visibilitychange', onVisibility);

    function setOrb(mode, text) {
      const orb = document.getElementById('orb');
      if (!orb) return;
      orb.className = `orb ${mode}`;
      document.getElementById('iv-status').textContent = text;
    }

    function speak(text) {
      if (!voiceOn || !('speechSynthesis' in window)) return;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text.replace(/\s+/g, ' ').slice(0, 600));
      utterance.rate = 1;
      utterance.onstart = () => setOrb('speaking', 'Interviewer is asking…');
      utterance.onend = () => setOrb('', 'Your turn');
      window.speechSynthesis.speak(utterance);
    }

    function stopListening() {
      if (recognizer) { try { recognizer.stop(); } catch (_) { /* already stopped */ } }
      listening = false;
    }

    function draw() {
      stopListening();
      const q = qs[index];
      const code = q.answer_mode === 'code';
      const coding = q.coding || {};
      if (code && !answers[q.id]) answers[q.id] = coding.starter_code || '';
      document.getElementById('dots').innerHTML = qs.map((x, i) => `<i class="${i === index ? 'here' : (answers[x.id] || '').trim() ? 'done' : ''}" title="Question ${i + 1}"></i>`).join('');
      document.getElementById('iv-card').innerHTML = `
        <div class="q-meta"><span class="pill">Question ${index + 1} of ${qs.length}</span><span class="pill">${esc(q.category)}</span></div>
        <div class="q-text">${esc(code ? (coding.title || 'Coding question') : q.question)}</div>
        ${code ? `<p class="muted" style="margin-top:.6rem">${esc(coding.statement || q.question)}</p>
          ${(coding.examples || []).map((ex) => `<div class="example">Input: ${esc(ex.input)}<br>Output: ${esc(ex.output)}</div>`).join('')}
          ${(coding.constraints || []).length ? `<p class="faint" style="margin-top:.6rem">${coding.constraints.map(esc).join('<br>')}</p>` : ''}
          ${coding.complexity_hint ? `<p class="faint">${esc(coding.complexity_hint)}</p>` : ''}` : ''}
        <label class="field" style="margin-top:18px">${code ? `Your solution (${esc(q.editor_language || 'code')})` : 'Your answer'}
          <textarea class="input answer ${code ? 'code' : ''}" id="answer" spellcheck="${code ? 'false' : 'true'}" placeholder="${code ? '' : 'Type your answer, or use the microphone to speak it.'}">${esc(answers[q.id] || '')}</textarea></label>
        <div class="answer-tools">
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn ghost small" id="replay">Repeat question</button>
            ${!code && Recognition ? '<button class="btn ghost small mic" id="mic">Speak answer</button>' : ''}
          </div>
          <span class="faint" id="wc"></span>
        </div>
        <div class="q-nav">
          <button class="btn ghost" id="prev" ${index === 0 ? 'disabled' : ''}>Previous</button>
          ${index < qs.length - 1 ? '<button class="btn" id="next">Save and continue</button>' : '<button class="btn mint" id="finish">Finish interview</button>'}
        </div>`;
      const box = document.getElementById('answer');
      const count = () => { const words = (box.value.trim().match(/\S+/g) || []).length; document.getElementById('wc').textContent = code ? `${box.value.split('\n').length} lines` : `${words} words`; };
      count();
      box.addEventListener('input', () => { answers[q.id] = box.value; count(); });
      box.addEventListener('paste', () => { integrity.paste_events += 1; });
      box.addEventListener('keydown', (e) => {
        if (code && e.key === 'Tab') { e.preventDefault(); const s = box.selectionStart; box.setRangeText('    ', s, box.selectionEnd, 'end'); answers[q.id] = box.value; }
      });
      document.getElementById('replay').addEventListener('click', () => speak(code ? `${coding.title}. ${coding.statement}` : q.question));
      const mic = document.getElementById('mic');
      if (mic) mic.addEventListener('click', () => toggleMic(mic, box, q));
      document.getElementById('prev').addEventListener('click', () => { save(); index -= 1; draw(); });
      const next = document.getElementById('next');
      if (next) next.addEventListener('click', () => { save(); index += 1; draw(); });
      const fin = document.getElementById('finish');
      if (fin) fin.addEventListener('click', finish);
      speak(code ? `Coding question. ${coding.title}. ${coding.statement}` : q.question);
      if (!voiceOn) setOrb('', 'Your turn');
      box.focus();
    }

    function toggleMic(button, box, q) {
      if (listening) { stopListening(); button.classList.remove('on'); button.innerHTML = 'Speak answer'; setOrb('', 'Your turn'); return; }
      window.speechSynthesis && window.speechSynthesis.cancel();
      recognizer = new Recognition();
      recognizer.lang = 'en-IN';
      recognizer.continuous = true;
      recognizer.interimResults = false;
      const base = box.value ? `${box.value.trim()} ` : '';
      let spoken = '';
      recognizer.onresult = (event) => {
        for (let i = event.resultIndex; i < event.results.length; i += 1) if (event.results[i].isFinal) spoken += `${event.results[i][0].transcript.trim()} `;
        box.value = base + spoken; answers[q.id] = box.value; box.dispatchEvent(new Event('input'));
      };
      recognizer.onerror = (event) => { toast(event.error === 'not-allowed' ? 'Microphone access was blocked. You can type your answer instead.' : 'Voice input stopped.', 'error'); };
      recognizer.onend = () => { listening = false; button.classList.remove('on'); button.innerHTML = 'Speak answer'; setOrb('', 'Your turn'); };
      recognizer.start();
      listening = true;
      button.classList.add('on');
      button.innerHTML = '<span class="wave" aria-hidden="true"><i></i><i></i><i></i><i></i></span>Stop';
      setOrb('listening', 'Listening…');
    }

    async function finish() {
      if (finished) return;
      const empty = qs.filter((q) => !(answers[q.id] || '').trim()).length;
      const ok = await confirmDialog('Finish the interview?', empty ? `${empty} question(s) have no answer yet. You cannot change answers after finishing.` : 'Your answers will be scored and you cannot change them afterwards.', 'Finish interview');
      if (!ok) return;
      finished = true;
      stopListening();
      window.speechSynthesis && window.speechSynthesis.cancel();
      const button = document.getElementById('finish');
      busy(button, true, 'Scoring your answers…');
      const payload = {};
      qs.forEach((q) => { payload[q.id] = answers[q.id] || ''; });
      try {
        const data = await api(`/api/applications/${app.id}/interview/complete`, { json: { answers: payload, integrity } });
        document.removeEventListener('visibilitychange', onVisibility);
        exitFocus();
        await refresh(app.id);
        if (data.application.stage.key === 'interview_passed') { confetti(); toast('You cleared the interview. HR will share the next steps soon.', 'ok'); }
        else toast('Your interview has been scored. We have emailed you the result.');
      } catch (error) {
        finished = false; busy(button, false); toast(error.message, 'error');
      }
    }

    document.getElementById('voice-toggle').addEventListener('click', (e) => {
      voiceOn = !voiceOn;
      if (!voiceOn && window.speechSynthesis) window.speechSynthesis.cancel();
      e.currentTarget.textContent = voiceOn ? 'Mute interviewer' : 'Unmute interviewer';
      setOrb('', 'Your turn');
    });
    draw();
  }

  boot();
})();
