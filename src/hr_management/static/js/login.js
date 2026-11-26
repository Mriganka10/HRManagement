/* Email → one-time code → signed in. */
(function () {
  'use strict';
  const { api, toast, busy } = window.HRM;
  const $ = (id) => document.getElementById(id);
  const digits = Array.from(document.querySelectorAll('.otp-row input'));
  let email = '';

  $('email').focus();

  $('email-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    email = $('email').value.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { toast('Enter a valid email address.', 'error'); return; }
    busy($('send-btn'), true, 'Sending code…');
    try {
      const data = await api('/api/auth/request-otp', { json: { email } });
      $('sent-to').textContent = data.email;
      $('ttl').textContent = data.ttl_minutes;
      if (data.dev_otp) {
        $('dev-hint').textContent = `Development mode: your code is ${data.dev_otp} (also printed in the server terminal).`;
        $('dev-hint').classList.remove('hidden');
      }
      $('step-email').classList.add('hidden');
      $('step-code').classList.remove('hidden');
      digits[0].focus();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      busy($('send-btn'), false);
    }
  });

  digits.forEach((input, index) => {
    input.addEventListener('input', () => {
      input.value = input.value.replace(/\D/g, '').slice(-1);
      if (input.value && index < digits.length - 1) digits[index + 1].focus();
      if (digits.every((d) => d.value)) $('code-form').requestSubmit();
    });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Backspace' && !input.value && index > 0) digits[index - 1].focus();
    });
    input.addEventListener('paste', (event) => {
      const text = (event.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, 6);
      if (text.length) {
        event.preventDefault();
        text.split('').forEach((ch, i) => { if (digits[i]) digits[i].value = ch; });
        digits[Math.min(text.length, 5)].focus();
        if (text.length === 6) $('code-form').requestSubmit();
      }
    });
  });

  $('code-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const otp = digits.map((d) => d.value).join('');
    if (otp.length !== 6) { toast('Enter all 6 digits.', 'error'); return; }
    busy($('verify-btn'), true, 'Signing in…');
    try {
      const data = await api('/api/auth/verify', { json: { email, otp } });
      window.location.href = data.redirect || '/app';
    } catch (error) {
      toast(error.message, 'error');
      digits.forEach((d) => { d.value = ''; });
      digits[0].focus();
      busy($('verify-btn'), false);
    }
  });

  $('back-btn').addEventListener('click', () => {
    $('step-code').classList.add('hidden');
    $('step-email').classList.remove('hidden');
    $('dev-hint').classList.add('hidden');
    $('email').focus();
  });
})();
