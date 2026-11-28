/*
 * Interface translation (English, Arabic) — same approach as Job-Hunting-Agent.
 *
 * Pages are written in English. For another language the server sets <html lang dir>
 * and loads /static/js/i18n/<lang>.js (window.HRM_I18N) before this script. Interface
 * text, placeholders, tooltips and labels are then swapped in place, including text the
 * page scripts add later (a MutationObserver watches for it). Names, job descriptions,
 * resumes, questions, code and anything people type are never translated: they are not
 * in the dictionary, and inputs, textareas, code and [data-no-i18n] are skipped.
 *
 * Every language picker (select[data-lang-picker]) is wired here: the choice is saved in
 * the hrm_lang cookie (and on the signed-in person, for emails) and the page reloads in
 * that language from the first paint.
 */
(function () {
  'use strict';
  const root = document.documentElement;
  const LANGS = ['en', 'ar'];
  const NAMES = { en: 'English', ar: 'العربية' };
  // Arabic month and day names with Latin digits (matches numbers typed in forms and IDs).
  const LOCALES = { en: 'en-IN', ar: 'ar-u-nu-latn' };
  const lang = LANGS.includes(root.lang) ? root.lang : 'en';

  function setLanguage(next) {
    if (!LANGS.includes(next) || next === lang) return;
    document.cookie = `hrm_lang=${next}; path=/; max-age=31536000; samesite=lax`;
    // Save it on the signed-in person too (emails, other devices). Best effort.
    fetch('/api/auth/language', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lang: next }),
    }).catch(() => null).finally(() => location.reload());
  }

  function pickerHtml(extraClass) {
    const options = LANGS.map((code) => `<option value="${code}" lang="${code}"${code === lang ? ' selected' : ''}>${NAMES[code]}</option>`).join('');
    return `<label class="lang-picker ${extraClass || ''}" data-no-i18n title="Language"><span class="sr-only">Language</span><select data-lang-picker aria-label="Language">${options}</select></label>`;
  }

  function syncPickers() {
    document.querySelectorAll('select[data-lang-picker]').forEach((select) => { if (select.value !== lang) select.value = lang; });
  }
  document.addEventListener('change', (event) => {
    if (event.target && event.target.matches && event.target.matches('select[data-lang-picker]')) setLanguage(event.target.value);
  });

  window.HRM_LANG = { lang, rtl: root.dir === 'rtl', locale: LOCALES[lang], set: setLanguage, picker: pickerHtml, t: (text) => text };

  const pack = lang === 'en' ? null : window.HRM_I18N;
  if (!pack) {
    document.addEventListener('DOMContentLoaded', syncPickers);
    return;
  }

  const exact = pack.strings || {};
  const lower = {};
  Object.keys(exact).forEach((key) => { lower[key.toLowerCase()] = exact[key]; });
  const patterns = (pack.patterns || []).map(([source, template]) => [new RegExp(`^${source}$`, 'i'), template]);
  const htmlBlocks = pack.html || {};
  const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'CODE', 'PRE', 'KBD', 'SAMP', 'NOSCRIPT', 'TEMPLATE']);
  const ATTRIBUTES = ['placeholder', 'title', 'aria-label', 'alt', 'data-label'];
  const cache = new Map();

  function lookup(key) {
    if (Object.prototype.hasOwnProperty.call(exact, key)) return exact[key];
    const folded = key.toLowerCase();
    if (Object.prototype.hasOwnProperty.call(lower, folded)) return lower[folded];
    return undefined;
  }

  function translate(text) {
    const key = String(text).replace(/\s+/g, ' ').trim();
    if (!key || !/[A-Za-z]/.test(key)) return null;
    if (cache.has(key)) return cache.get(key);
    let result = lookup(key);
    if (result === undefined) {
      result = null;
      for (const [pattern, template] of patterns) {
        const match = key.match(pattern);
        if (match) {
          // $1 = a captured value, translated if it is itself interface text;
          // $L1 = a comma-separated list, $S1 = a semicolon-separated list, each item translated.
          const part = (value) => { const r = value ? translate(value) : null; return r === null ? (value || '') : r; };
          result = template.replace(/\$([LS])(\d)|\$(\d)/g, (_, kind, listIndex, index) => {
            if (kind === 'L') return (match[Number(listIndex)] || '').split(/,\s*/).map(part).join(pack.listSeparator || '، ');
            if (kind === 'S') return (match[Number(listIndex)] || '').split(/;\s*/).map(part).join('؛ ');
            return part(match[Number(index)]);
          });
          break;
        }
      }
      // A sentence ending in ":" or "." that is only missing its punctuation in the pack.
      if (result === null) {
        const bare = key.replace(/[:.!?]$/, '');
        if (bare !== key) {
          const hit = lookup(bare);
          if (hit !== undefined) result = hit + ({ ':': ':', '.': '.', '!': '!', '?': '؟' }[key.slice(-1)] || '');
        }
      }
    }
    if (cache.size > 5000) cache.clear();
    cache.set(key, result);
    return result;
  }
  window.HRM_LANG.t = (text) => translate(text) || text;

  function skipped(element) {
    for (let node = element; node && node !== document; node = node.parentElement) {
      if (SKIP.has(node.tagName) || node.isContentEditable || (node.hasAttribute && node.hasAttribute('data-no-i18n'))) return true;
    }
    return false;
  }

  function translateTextNode(node) {
    const value = node.nodeValue;
    const result = translate(value);
    if (result === null || result === value.trim()) return;
    const lead = value.match(/^\s*/)[0];
    const tail = value.match(/\s*$/)[0];
    node.nodeValue = lead + result + tail;
  }

  function translateAttributes(element) {
    for (const name of ATTRIBUTES) {
      const value = element.getAttribute && element.getAttribute(name);
      if (!value) continue;
      const result = translate(value);
      if (result !== null && result !== value) element.setAttribute(name, result);
    }
  }

  function translateTree(start) {
    if (!start) return;
    if (start.nodeType === Node.TEXT_NODE) {
      if (start.parentElement && !skipped(start.parentElement)) translateTextNode(start);
      return;
    }
    if (start.nodeType !== Node.ELEMENT_NODE || skipped(start)) return;
    if (start.dataset && start.dataset.i18n && htmlBlocks[start.dataset.i18n]) {
      if (start.dataset.i18nDone !== lang) {
        start.innerHTML = htmlBlocks[start.dataset.i18n];
        start.dataset.i18nDone = lang;
      }
      return;
    }
    translateAttributes(start);
    const walker = document.createTreeWalker(start, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          if (node.hasAttribute('data-no-i18n') || node.isContentEditable) return NodeFilter.FILTER_REJECT;
          if (SKIP.has(node.tagName)) {
            // A text box keeps what the person typed, but its placeholder and label are interface.
            if (node.tagName !== 'SCRIPT' && node.tagName !== 'STYLE') translateAttributes(node);
            return NodeFilter.FILTER_REJECT;
          }
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    let node = walker.nextNode();
    while (node) {
      if (node.nodeType === Node.TEXT_NODE) translateTextNode(node);
      else if (node.dataset && node.dataset.i18n && htmlBlocks[node.dataset.i18n]) translateTree(node);
      else translateAttributes(node);
      node = walker.nextNode();
    }
  }

  function translateTitle() {
    const parts = document.title.split(/\s+[·|–-]\s+/);
    const translated = parts.map((part) => translate(part) || part).join(' · ');
    if (translated !== document.title) document.title = translated;
  }

  let queued = new Set();
  let scheduled = false;
  function flush() {
    scheduled = false;
    const nodes = queued;
    queued = new Set();
    nodes.forEach((node) => { if (node.isConnected) translateTree(node); });
    translateTitle();
    syncPickers();
  }
  function queue(node) {
    queued.add(node);
    if (!scheduled) { scheduled = true; requestAnimationFrame(flush); }
  }

  function start() {
    translateTree(document.body);
    translateTitle();
    syncPickers();
    new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === 'characterData') queue(mutation.target);
        else if (mutation.type === 'attributes') queue(mutation.target);
        else mutation.addedNodes.forEach(queue);
      }
    }).observe(root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRIBUTES });
    new MutationObserver(() => queue(document.body)).observe(document.querySelector('title') || document.head, { subtree: true, childList: true, characterData: true });
  }

  // Dialogs raised by page scripts (confirm/alert/prompt) are translated too.
  const nativeConfirm = window.confirm.bind(window);
  const nativeAlert = window.alert.bind(window);
  const nativePrompt = window.prompt.bind(window);
  window.confirm = (message) => nativeConfirm(translate(String(message)) || message);
  window.alert = (message) => nativeAlert(translate(String(message)) || message);
  window.prompt = (message, value) => nativePrompt(translate(String(message)) || message, value);

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();