/* Shared helpers for every page: API calls, toasts, escaping, dialogs, tables, router, formatters. */
(function () {
  'use strict';

  function esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
  }

  async function api(path, options = {}) {
    const init = { credentials: 'same-origin', ...options };
    if (init.json !== undefined) {
      init.method = init.method || 'POST';
      init.headers = { 'Content-Type': 'application/json', ...(init.headers || {}) };
      init.body = JSON.stringify(init.json);
      delete init.json;
    }
    const response = await fetch(path, init);
    let data = {};
    try { data = await response.json(); } catch (_) { /* empty body */ }
    // 401 from a portal API = the session ended -> back to sign-in. Sign-in APIs themselves
    // (/api/auth/*) answer 401 for a wrong password or "nobody signed in"; those must reach
    // the page as a normal error, or the sign-in form would just reload with no message.
    if (response.status === 401 && !path.startsWith('/api/auth/')) { window.location.href = window.HRM_LOGIN || '/login'; throw new Error('Please sign in.'); }
    if (response.status === 403 && /new password/i.test(data.detail || '')) { window.location.href = '/password'; throw new Error(data.detail); }
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join(', ') : data.detail;
      throw new Error(detail || `Request failed (${response.status}).`);
    }
    return data;
  }

  function toast(message, kind = '') {
    let host = document.getElementById('toasts');
    if (!host) { host = document.createElement('div'); host.id = 'toasts'; host.setAttribute('aria-live', 'polite'); document.body.appendChild(host); }
    const item = document.createElement('div');
    item.className = `toast ${kind}`;
    item.textContent = message;
    host.appendChild(item);
    setTimeout(() => item.remove(), 4500);
  }

  function busy(button, on, label) {
    if (!button) return;
    if (on) {
      button.dataset.label = button.innerHTML;
      button.disabled = true;
      button.innerHTML = `<span class="spinner" aria-hidden="true"></span>${esc(label || 'Working…')}`;
    } else {
      button.disabled = false;
      if (button.dataset.label) button.innerHTML = button.dataset.label;
    }
  }

  /* Run an async action with a busy button and an error toast. */
  async function act(button, label, fn, okMessage) {
    busy(button, true, label);
    try {
      const result = await fn();
      if (okMessage) toast(okMessage, 'ok');
      return result;
    } catch (error) {
      toast(error.message, 'error');
      return undefined;
    } finally {
      busy(button, false);
    }
  }

  function confetti() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const host = document.createElement('div');
    host.className = 'confetti';
    const colours = ['#008081', '#1a9e6f', '#d99a2b', '#6fd0cf', '#0a4f50'];
    for (let i = 0; i < 90; i += 1) {
      const piece = document.createElement('i');
      piece.style.left = `${Math.random() * 100}%`;
      piece.style.background = colours[i % colours.length];
      piece.style.animationDuration = `${1.8 + Math.random() * 1.6}s`;
      piece.style.animationDelay = `${Math.random() * 0.5}s`;
      host.appendChild(piece);
    }
    document.body.appendChild(host);
    setTimeout(() => host.remove(), 4000);
  }

  function confirmDialog(title, body, okLabel, cancelLabel = 'Cancel') {
    return new Promise((resolve) => {
      const dialog = document.createElement('dialog');
      dialog.innerHTML = `<h3>${esc(title)}</h3><p class="muted">${esc(body)}</p>
        <div class="actions"><button class="btn ghost" value="no">${esc(cancelLabel)}</button><button class="btn" value="yes">${esc(okLabel)}</button></div>`;
      document.body.appendChild(dialog);
      dialog.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => dialog.close(b.value)));
      dialog.addEventListener('close', () => { resolve(dialog.returnValue === 'yes'); dialog.remove(); });
      dialog.showModal();
    });
  }

  /* A form dialog. ``onSubmit(data, form)`` returns truthy to close; throw to show an error. */
  function formDialog(title, bodyHTML, submitLabel, onSubmit, { wide = false } = {}) {
    const dialog = document.createElement('dialog');
    if (wide) dialog.classList.add('wide');
    dialog.innerHTML = `<form class="stack" novalidate><h3>${esc(title)}</h3>${bodyHTML}
      <div class="actions"><button type="button" class="btn ghost" data-close>Cancel</button><button type="submit" class="btn">${esc(submitLabel)}</button></div></form>`;
    document.body.appendChild(dialog);
    const form = dialog.querySelector('form');
    dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => dialog.remove());
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type=submit]');
      busy(button, true, 'Saving…');
      try {
        const ok = await onSubmit(formObject(form), form);
        if (ok !== false) dialog.close();
      } catch (error) { toast(error.message, 'error'); } finally { busy(button, false); }
    });
    dialog.showModal();
    const first = form.querySelector('input:not([type=hidden]), select, textarea');
    if (first) first.focus();
    return dialog;
  }

  function formObject(form) {
    const data = {};
    new FormData(form).forEach((value, key) => { if (!(value instanceof File)) data[key] = typeof value === 'string' ? value.trim() : value; });
    form.querySelectorAll('input[type=checkbox][name]').forEach((box) => { data[box.name] = box.checked; });
    return data;
  }

  async function logout() {
    try { await api('/api/auth/logout', { method: 'POST' }); } finally { window.location.href = '/'; }
  }

  function fmt(value, digits = 0) {
    if (value === null || value === undefined || value === '') return '–';
    const n = Number(value);
    return Number.isInteger(n) ? String(n) : n.toFixed(digits || 1);
  }

  // Dates and times follow the interface language (Arabic month names with Latin digits);
  // money keeps Indian digit grouping (₹12,34,567) in every language.
  const LOCALE = (window.HRM_LANG && window.HRM_LANG.locale) || 'en-IN';

  function money(value) {
    if (value === null || value === undefined || value === '') return '–';
    return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: Number(value) % 1 ? 2 : 0 })}`;
  }

  function date(value, withTime = false) {
    if (!value) return '–';
    const d = new Date(value.length === 10 ? `${value}T00:00:00` : value);
    if (Number.isNaN(d.getTime())) return esc(value);
    const opts = { day: 'numeric', month: 'short', year: 'numeric' };
    if (withTime) Object.assign(opts, { hour: '2-digit', minute: '2-digit' });
    return d.toLocaleString(LOCALE, opts);
  }

  function time(value) {
    if (!value) return '–';
    return new Date(value).toLocaleTimeString(LOCALE, { hour: '2-digit', minute: '2-digit' });
  }

  function label(value) { return String(value || '').replace(/_/g, ' '); }

  function pill(status, text) { return `<span class="pill ${esc(status)}">${esc(text || label(status))}</span>`; }

  /* columns: [{label, render(row) -> html, cls}] */
  function table(columns, rows, { empty = 'Nothing here yet.', onClick = null, id = '' } = {}) {
    if (!rows || !rows.length) return `<div class="empty">${esc(empty)}</div>`;
    const tid = id || `t${Math.random().toString(36).slice(2, 8)}`;
    setTimeout(() => {
      if (!onClick) return;
      document.querySelectorAll(`#${tid} tr[data-i]`).forEach((tr) => tr.addEventListener('click', (e) => {
        if (e.target.closest('button, a, input, select')) return;
        onClick(rows[Number(tr.dataset.i)]);
      }));
    });
    return `<div class="table-wrap"><table class="data" id="${tid}"><thead><tr>${columns.map((c) => `<th class="${c.cls || ''}">${esc(c.label)}</th>`).join('')}</tr></thead>
      <tbody>${rows.map((row, i) => `<tr data-i="${i}" class="${onClick ? 'click' : ''}">${columns.map((c) => `<td class="${c.cls || ''}">${c.render(row)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }

  function bars(items, { max = 100, colour } = {}) {
    return `<div class="bars">${items.map((it) => {
      const value = Number(it.value) || 0;
      const pct = Math.max(0, Math.min(100, (value / (it.max || max)) * 100));
      const c = colour ? colour(value, it) : 'var(--brand)';
      return `<div class="bar-row"><header><span>${esc(it.label)}</span><span class="num">${esc(it.text !== undefined ? it.text : fmt(value))}</span></header>
        <div class="bar"><i data-w="${pct}%" style="background:${c}"></i></div></div>`;
    }).join('')}</div>`;
  }

  function dial(score, threshold, colour) {
    const r = 92; const c = 2 * Math.PI * r;
    const pct = Math.max(0, Math.min(100, Number(score) || 0));
    const angle = (threshold / 100) * 2 * Math.PI;
    const tx1 = 110 + (r - 14) * Math.cos(angle); const ty1 = 110 + (r - 14) * Math.sin(angle);
    const tx2 = 110 + (r + 14) * Math.cos(angle); const ty2 = 110 + (r + 14) * Math.sin(angle);
    return `<div class="dial" role="img" aria-label="Score ${fmt(score)} out of 100, pass mark ${threshold}">
      <svg viewBox="0 0 220 220"><circle class="ring-bg" cx="110" cy="110" r="${r}"/>
      <circle class="ring" cx="110" cy="110" r="${r}" stroke="${colour}" stroke-dasharray="${c}" stroke-dashoffset="${c}" data-target="${c * (1 - pct / 100)}"/>
      <line class="tick" x1="${tx1}" y1="${ty1}" x2="${tx2}" y2="${ty2}"/></svg>
      <div class="value"><b data-count="${pct}">0</b><span>pass mark ${fmt(threshold)}</span></div></div>`;
  }

  function animateIn(root) {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      root.querySelectorAll('.ring[data-target]').forEach((ring) => { ring.style.strokeDashoffset = ring.dataset.target; });
      root.querySelectorAll('.bar i[data-w]').forEach((bar) => { bar.style.width = bar.dataset.w; });
      root.querySelectorAll('.journey .fill[data-w]').forEach((bar) => { bar.style.width = bar.dataset.w; });
      root.querySelectorAll('[data-count]').forEach((node) => {
        const target = Number(node.dataset.count) || 0;
        const start = performance.now();
        const step = (now) => {
          const t = Math.min(1, (now - start) / 1100);
          node.textContent = Math.round(target * (1 - Math.pow(1 - t, 3)));
          if (t < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      });
    }));
  }

  /* Tiny hash router: routes = [{path: '/employees/:id', view: fn(params)}] */
  function router(routes, fallback) {
    async function go() {
      const hash = (window.location.hash || '#/').slice(1) || '/';
      for (const route of routes) {
        const names = [];
        const pattern = new RegExp(`^${route.path.replace(/:[a-z]+/g, (m) => { names.push(m.slice(1)); return '([^/]+)'; })}$`);
        const match = hash.match(pattern);
        if (match) {
          const params = {};
          names.forEach((n, i) => { params[n] = decodeURIComponent(match[i + 1]); });
          await route.view(params, route);
          return;
        }
      }
      if (fallback) window.location.hash = fallback;
    }
    window.addEventListener('hashchange', go);
    go();
    return go;
  }

  const ICONS = {
    home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.8c2 .7 3.2 2.4 3.6 5.2"/>',
    funnel: '<path d="M3 4h18l-7 8v6l-4 2v-8z"/>',
    briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    wallet: '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M16 13h2M3 10h18"/>',
    inbox: '<path d="M3 13l3-8h12l3 8v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M3 13h5l1 3h6l1-3h5"/>',
    book: '<path d="M4 4h6a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4zM20 4h-6a3 3 0 0 0-3 3"/><path d="M20 4v14h-7"/>',
    spark: '<path d="M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z"/>',
    star: '<path d="M12 3l2.7 5.6 6.1.8-4.5 4.3 1.1 6.1L12 17l-5.4 2.8 1.1-6.1L3.2 9.4l6.1-.8z"/>',
    shield: '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4.5 4.2-7 8-7s7 2.5 8 7"/>',
    doc: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 13h6M9 17h6"/>',
    team: '<circle cx="7" cy="9" r="3"/><circle cx="17" cy="9" r="3"/><path d="M1.5 19c.7-3 2.8-4.5 5.5-4.5s4.8 1.5 5.5 4.5M11.5 19c.7-3 2.8-4.5 5.5-4.5s4.8 1.5 5.5 4.5"/>',
    bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    growth: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    onboard: '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3"/>',
    audit: '<path d="M9 5H5v16h14V5h-4"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 12l2 2 4-4"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  };
  function icon(name) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  }

  /* Portal shell: sidebar navigation + top bar; returns the content element. */
  function shell({ nav, me, subtitle, onNotifications }) {
    document.body.innerHTML = `<div class="shell">
      <aside class="sidebar" id="sidebar"><a class="brand" href="#/"><img src="/static/img/kairoz-logo-white.png" alt="Kairoz"></a>
        ${nav.map((g) => `<nav class="nav-group" aria-label="${esc(g.group)}"><span>${esc(g.group)}</span>${g.items.map((it) => `
          <a class="nav-link" href="#${it.path}" data-path="${it.path}">${icon(it.icon)}${esc(it.label)}${it.count ? `<span class="count">${it.count}</span>` : ''}</a>`).join('')}</nav>`).join('')}
        <div class="me"><span class="avatar">${esc((me.full_name || me.email || '?').slice(0, 1).toUpperCase())}</span>
          <div><b>${esc(me.full_name)}</b><span>${esc(subtitle)}</span></div>
          <button class="btn link" id="logout" title="Sign out" aria-label="Sign out" style="margin-inline-start:auto;color:#9fc2c1">${icon('logout')}</button></div>
      </aside>
      <div class="portal-main"><header class="portal-top">
        <div class="row"><button class="icon-btn menu-toggle" id="menu" aria-label="Menu">${icon('menu')}</button><h1 id="page-title"></h1></div>
        <div class="row" id="top-actions">${window.HRM_LANG ? window.HRM_LANG.picker('portal-lang') : ''}<button class="icon-btn" id="bell" aria-label="Notifications">${icon('bell')}</button></div></header>
        <main class="portal-content" id="content" tabindex="-1"></main></div></div>
      <div class="scrim hidden" id="scrim"></div><aside class="drawer" id="drawer" aria-hidden="true"></aside>`;
    document.getElementById('logout').addEventListener('click', logout);
    document.getElementById('menu').addEventListener('click', () => document.getElementById('sidebar').classList.toggle('open'));
    document.getElementById('bell').addEventListener('click', onNotifications);
    document.getElementById('scrim').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
    return document.getElementById('content');
  }

  function setPage(title, path) {
    document.getElementById('page-title').textContent = title;
    document.title = `${title} | Kairoz`;
    document.querySelectorAll('.nav-link').forEach((a) => {
      const p = a.dataset.path;
      a.setAttribute('aria-current', (p === '/' ? path === '/' : path === p || path.startsWith(`${p}/`)) ? 'page' : 'false');
    });
    document.getElementById('sidebar').classList.remove('open');
    window.scrollTo(0, 0);
  }

  function openDrawer(html) {
    const drawer = document.getElementById('drawer');
    drawer.innerHTML = html;
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    document.getElementById('scrim').classList.remove('hidden');
    const close = drawer.querySelector('[data-close]');
    if (close) { close.addEventListener('click', closeDrawer); close.focus(); }
    animateIn(drawer);
    return drawer;
  }

  function closeDrawer() {
    const drawer = document.getElementById('drawer');
    if (!drawer) return;
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    const scrim = document.getElementById('scrim');
    if (scrim) scrim.classList.add('hidden');
  }

  function options(list, selected, { valueKey = 'value', labelKey = 'label', blank = '' } = {}) {
    const items = list.map((it) => (typeof it === 'object' ? it : { [valueKey]: it, [labelKey]: it }));
    return `${blank ? `<option value="">${esc(blank)}</option>` : ''}${items.map((it) => `<option value="${esc(it[valueKey])}" ${String(it[valueKey]) === String(selected) ? 'selected' : ''}>${esc(it[labelKey])}</option>`).join('')}`;
  }

  window.HRM = {
    esc, api, toast, busy, act, confetti, confirmDialog, formDialog, formObject, logout, fmt, money, date, time, label, pill,
    table, bars, dial, animateIn, router, icon, shell, setPage, openDrawer, closeDrawer, options,
    locale: LOCALE, t: (text) => (window.HRM_LANG ? window.HRM_LANG.t(text) : text),
  };
})();