/* Staff sign-in (user ID + password) and first-sign-in password change. */
(function () {
  'use strict';
  const { api, toast, busy } = window.HRM;
  const $ = (id) => document.getElementById(id);

  const loginForm = $('login-form');
  if (loginForm) {
    const as = new URLSearchParams(window.location.search).get('as');
    if (as === 'hr') { $('art-title').textContent = 'HR portal'; $('form-title').textContent = 'HR sign-in'; $('user_id').placeholder = 'KZH1001'; }
    if (as === 'employee') { $('art-title').textContent = 'Employee portal'; $('form-title').textContent = 'Employee sign-in'; }
    $('user_id').focus();
    loginForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const userId = $('user_id').value.trim().toUpperCase();
      const password = $('password').value;
      if (!userId || !password) { toast('Enter your user ID and password.', 'error'); return; }
      busy($('login-btn'), true, 'Signing in…');
      try {
        const data = await api('/api/auth/login', { json: { user_id: userId, password } });
        window.location.href = data.redirect;
      } catch (error) {
        toast(error.message, 'error');
        $('password').value = '';
        $('password').focus();
        busy($('login-btn'), false);
      }
    });
  }

  const pwForm = $('pw-form');
  if (pwForm) {
    api('/api/auth/me').then((me) => { $('who').textContent = `${me.full_name} (${me.user_id})`; }).catch(() => {});
    const check = () => {
      const value = $('new').value;
      const rules = { len: value.length >= 10, mix: /[a-z]/i.test(value) && /\d/.test(value), match: value && value === $('repeat').value };
      document.querySelectorAll('#rules li').forEach((li) => li.classList.toggle('ok', Boolean(rules[li.dataset.r])));
      return Object.values(rules).every(Boolean);
    };
    ['new', 'repeat'].forEach((id) => $(id).addEventListener('input', check));
    $('pw-logout').addEventListener('click', window.HRM.logout);
    pwForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!check()) { toast('Your new password does not meet the rules yet.', 'error'); return; }
      busy($('pw-btn'), true, 'Saving…');
      try {
        const data = await api('/api/auth/change-password', { json: { current_password: $('current').value, new_password: $('new').value } });
        toast('Password saved.', 'ok');
        window.location.href = data.redirect;
      } catch (error) { toast(error.message, 'error'); busy($('pw-btn'), false); }
    });
  }
})();
