/* Shared helpers: API calls, toasts, escaping, small DOM utilities. */
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
    if (response.status === 401) { window.location.href = '/login'; throw new Error('Please sign in.'); }
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
    setTimeout(() => item.remove(), 4200);
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

  function confetti() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const host = document.createElement('div');
    host.className = 'confetti';
    const colours = ['#5b4bff', '#12b886', '#f5a524', '#8f84ff', '#22d3ee'];
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

  function confirmDialog(title, body, okLabel) {
    return new Promise((resolve) => {
      const dialog = document.createElement('dialog');
      dialog.innerHTML = `<h3>${esc(title)}</h3><p class="muted" style="margin-top:.6rem">${esc(body)}</p>
        <div class="actions"><button class="btn ghost" value="no">Not yet</button><button class="btn" value="yes">${esc(okLabel)}</button></div>`;
      document.body.appendChild(dialog);
      dialog.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { dialog.close(b.value); }));
      dialog.addEventListener('close', () => { resolve(dialog.returnValue === 'yes'); dialog.remove(); });
      dialog.showModal();
    });
  }

  async function logout() {
    try { await api('/api/auth/logout', { method: 'POST' }); } finally { window.location.href = '/login'; }
  }

  function fmt(value, digits = 0) {
    if (value === null || value === undefined || value === '') return '–';
    const n = Number(value);
    return Number.isInteger(n) ? String(n) : n.toFixed(digits || 1);
  }

  function dial(score, threshold, colour) {
    const r = 92; const c = 2 * Math.PI * r;
    const pct = Math.max(0, Math.min(100, Number(score) || 0));
    const angle = (threshold / 100) * 2 * Math.PI;
    const tx1 = 110 + (r - 14) * Math.cos(angle); const ty1 = 110 + (r - 14) * Math.sin(angle);
    const tx2 = 110 + (r + 14) * Math.cos(angle); const ty2 = 110 + (r + 14) * Math.sin(angle);
    const html = `<div class="dial" role="img" aria-label="Score ${fmt(score)} out of 100, pass mark ${threshold}">
      <svg width="220" height="220" viewBox="0 0 220 220"><circle class="ring-bg" cx="110" cy="110" r="${r}"/>
      <circle class="ring" cx="110" cy="110" r="${r}" stroke="${colour}" stroke-dasharray="${c}" stroke-dashoffset="${c}" data-target="${c * (1 - pct / 100)}"/>
      <line class="tick" x1="${tx1}" y1="${ty1}" x2="${tx2}" y2="${ty2}"/></svg>
      <div class="value"><b data-count="${pct}">0</b><span>pass mark ${fmt(threshold)}</span></div></div>`;
    return html;
  }

  /* Animate dials, bars and counters that were just inserted (one reveal per render). */
  function animateIn(root) {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      root.querySelectorAll('.ring[data-target]').forEach((ring) => { ring.style.strokeDashoffset = ring.dataset.target; });
      root.querySelectorAll('.bar i[data-w]').forEach((bar) => { bar.style.width = bar.dataset.w; });
      root.querySelectorAll('.journey .fill[data-w]').forEach((bar) => { bar.style.width = bar.dataset.w; });
      root.querySelectorAll('[data-count]').forEach((node) => {
        const target = Number(node.dataset.count) || 0;
        const start = performance.now();
        const step = (now) => {
          const t = Math.min(1, (now - start) / 1200);
          node.textContent = Math.round(target * (1 - Math.pow(1 - t, 3)));
          if (t < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      });
    }));
  }

  window.HRM = { esc, api, toast, busy, confetti, confirmDialog, logout, fmt, dial, animateIn };
})();
