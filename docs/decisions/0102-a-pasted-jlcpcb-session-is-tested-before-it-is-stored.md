---
status: accepted
date: 2026-11-07
decision-makers: Mateusz Kowalik
---

# Log in to JLCPCB in a new tab, paste the session back, and test it before it is stored

## Context and Problem Statement

Henry reads JLCPCB's web API with a copy of a browser session
([docs/jlcpcb-web-api.md](../jlcpcb-web-api.md)). When the session dies, a person
copies it from DevTools and pastes it into Henry. The user asked to automate this,
and then chose to keep it half automatic. What is the least work for a person, with
no install and no credential in Henry that is worth more than the session itself?

## Decision Drivers

* No install on the user's machine.
* Henry never holds a Google credential. It opens the whole Google account, not
  only JLCPCB.
* Nothing defeats a captcha or other bot detection.
* A bad paste must not overwrite a session that still works.

## Facts, measured on 2026-11-07

* The account logs in with Google, and Google asks which account to use.
* A page of Henry cannot read JLCPCB's cookies. They belong to another origin, and
  `JLCPCB_SESSION_ID` is httpOnly.
* JLCPCB answers a dead session with HTTP 200 and `code: 460` in the body, and the
  text "For security reasons, you were automatically logged out of your account". A
  made-up session gets the same answer, so this text does not show a security event.
  The order service adds `success: false`. The parts service does not, so Henry read
  its answer as an empty list and marked the session as working.
* How long a session lives is not known. The audit log shows three pastes: two on
  2026-07-28 and one on 2026-10-29. `last_ok_at` cannot say more, because of the
  answer above.
* The site's JS requires reCAPTCHA or the Aliyun slider on the password form
  (`resolveCaptchaParams`). `googleSign()` calls no captcha. This is read from the
  code, and no login was tried.

## Considered Options

* A new tab for the login, and a paste that Henry tests
* A Chrome extension that sends the session and asks for a login
* A small iframe in Henry
* A command on the Mac that opens a browser window and reads the cookies
* A browser on the server, shown in a Henry window
* A password or Google login in a headless browser on the server
* Renew on the server through the site's `/checkLogin` with the stored cookies

## Decision Outcome

Chosen option: "A new tab and a tested paste", because it needs no install, and how
often a session dies is not known yet. It may die so rarely that more is not worth it.

1. **A button opens the login.** "Log in at JLCPCB" on the JLC page opens an account
   page in a new tab, and the steps to copy the session back appear beside it.
2. **A paste can be what DevTools gives.** A "Copy as cURL" command, a `Cookie:`
   header alone or among other headers, a cookie-JSON array, or the bare value of
   `JLCPCB_SESSION_ID`. Henry keeps only the cookies.
3. **Henry tests every paste before it stores it.** It reads the order list with the
   new cookies. On a dead session the answer is 409, and the stored session stays.
4. **`code: 460` in a 200 body is a dead session**, the same as HTTP 460.
5. **A dead JLCPCB session answers 409, never 401.** The web client reads any 401 as a
   lost Henry session and shows the sign-in form. A test holds this rule.
6. **A new session clears the old one's `died_at`, `last_error` and
   `keepalive_count`.** Otherwise the status says that a new session is dead, and the
   lifetime is measured from the wrong start.

### Consequences

* Good, because nothing is installed and no new credential is stored anywhere.
* Good, because a failed paste says so at once and cannot damage a working session.
* Good, because `died_at` now measures a session's lifetime.
* Bad, because a person still logs in and opens DevTools each time.
* Bad, because a person learns of a dead session only from the JLC page or a failed
  import. Nothing notifies them.
* Neutral, because this API stays undocumented and plausibly against JLCPCB's terms,
  as it was before.

### Confirmation

* `api/tests/costs/test_jlc_web_session_death.py` holds items 2 to 6.
* The first live paste confirms the flow. It also shows whether the bare
  `JLCPCB_SESSION_ID` value is enough. The code says so, but no live test has shown it.

## Pros and Cons of the Options

### A Chrome extension

* Good, because nobody opens DevTools, and a dead session raises a notification.
* Bad, because it needs an install and keeps a Henry token unencrypted in Chrome.
* It was built and tested against a stub Henry, then set aside at the user's choice.
  It is on the local branch `jlc-session-extension`, which was not pushed. Revisit it
  if `died_at` shows that sessions die often.

### A small iframe in Henry

* Bad, because a page of Henry could not read the cookies in any case.
* Bad, because the Google button sets `top.location.href`, which takes the whole Henry
  page out of the frame.

### A command on the Mac

* Good, because a person only logs in, and the command reads the cookies. This is the
  method of [hatlabs/jlcpcb-cli](https://github.com/hatlabs/jlcpcb-cli).
* Bad, because it needs a local script and a person who has noticed the dead session.
* Bad, because Google may refuse a browser window that a program controls (unverified).

### A browser on the server, shown in a Henry window

* Good, because it needs no install and no DevTools.
* Bad, because the Google login passes through Henry's server, in a heavy new container.
* Bad, because Google may block a login from a server address (unverified).

### A password or Google login in a headless browser on the server

* Bad, because the password form requires a captcha, and this project does not defeat
  one.
* Bad, because a Google login would put the credentials of the whole Google account,
  with its second factor, in Henry.

### Renew on the server through `/checkLogin`

* Good, because it would need no person and no browser.
* Bad, because it is untested. The test needs the stored cookies on production and the
  request's parameters, which are not known.
* Not rejected: add it if a test shows that it works.

## More Information

On 2026-07-28 the user deferred both an extension and a headless login until the
session's lifetime was measured
([docs/production-costs/design.md](../production-costs/design.md)). This record does
not end that wait for the extension, and item 6 makes the measurement work.
