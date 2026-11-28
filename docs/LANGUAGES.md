# Languages: English and Arabic

Every page has a language menu (🌐 **English / العربية**). Candidates, employees and HR can switch at any time; the
whole interface changes, Arabic pages turn right-to-left, and the choice is remembered. This works the same way
as in Job-Hunting-Agent.

| What | English | Arabic |
| --- | --- | --- |
| Interface text, buttons, menus, messages, errors | ✓ | ✓ |
| Layout | left-to-right | right-to-left (sidebar, side panels, calendar, tables, chat bubbles mirror) |
| Dates | 28 Nov 2026 | 28 نوفمبر 2026 (Latin digits, so IDs and amounts stay readable) |
| Emails (sign-in code, every hiring stage, credentials, leave, requests) | ✓ | ✓ in the recipient's language, right-to-left |
| HR assistant | ✓ | understands Arabic requests and answers in Arabic, with or without an LLM |
| People's data (names, job descriptions, resumes, test/interview questions, policy text, code) | as entered | as entered — never machine-translated |

## How the language is chosen

First match wins:

1. the `hrm_lang` cookie set by the language menu on this browser;
2. the language saved on the person — staff account (`accounts.lang`) or candidate (`users.lang`) — so a choice follows them to a new device;
3. the browser's `Accept-Language` (an Arabic browser opens in Arabic);
4. `HRM_DEFAULT_LANGUAGE` (`en` unless you change it).

Choosing a language while signed in saves it on the person (`POST /api/auth/language`). A candidate's language
carries over to their employee account at onboarding. Emails always use the recipient's saved language.

## How it works

| Piece | File |
| --- | --- |
| Language detection, saved preference, `<html lang dir>`, the menu | `src/hr_management/i18n.py`, `api/pages.py`, `api/auth.py` |
| Translator (swaps interface text in place, including text added later by the page scripts) | `static/js/i18n.js` |
| Arabic dictionary and patterns | `static/js/i18n/ar.js` |
| Right-to-left styles, Arabic fonts | end of `static/css/app.css` |
| Arabic emails | `notifications.py` → `_TEMPLATES_AR` |
| Arabic assistant (understanding + replies) | `services/assistant.py` → `from_arabic`, `_REPLIES` |

Pages stay written in English. For Arabic, the server sets `<html lang="ar" dir="rtl">` and loads
`i18n/ar.js` + `i18n.js`. The translator looks up each piece of interface text in `strings` (exact text) and
then in `patterns` (text containing names, numbers or dates, e.g. `Not enough (.+) balance: …`). Inputs,
textareas, code, the language menu and anything inside `data-no-i18n` are never touched.

## Adding or fixing a translation

Open `static/js/i18n/ar.js`, add or edit a line in `strings` — the key is the exact English text on the page —
and reload. No build step. For text with a value in it, add a pattern:

```js
["You already have leave from (.+) to (.+)\\.", "لديك إجازة بالفعل من $1 إلى $2."]
```

`$1` is the captured value (translated too if it is itself interface text); `$L1` translates a comma list, `$S1` a
semicolon list. When you add new English text to a page, add its Arabic line in the same change.

## Adding another language

Add it to `LANGUAGES` in `i18n.py` and `LANGS` / `NAMES` / `LOCALES` in `i18n.js`, create `static/js/i18n/<code>.js`
with the same shape as `ar.js`, and add email templates and assistant replies for it. Right-to-left languages also
use the `[dir="rtl"]` styles already in `app.css`.

## Things to know

- **Policies** are company content: write an Arabic version of a policy in **HR → Policies** if staff need one.
  The assistant quotes policies as written.
- **Mock tests and the AI interview** are scored on English answers, so their questions stay in English. The
  surrounding screens, instructions and results are translated.
- **Payslips, certificates and letters** (printable documents) stay in English as official records.
