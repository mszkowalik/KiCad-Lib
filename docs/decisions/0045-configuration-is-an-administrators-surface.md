---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# Put the deployment's own configuration behind the administrator role, and state the admin-only set in a test

## Context and Problem Statement

The platform has had two roles, `admin` and `user`, since sign-in was built
(2026-07-31), and a default-deny authentication gate since
`app/authgate.py::AuthGate` landed. The gate answers "is this a known caller".
It has never answered "may this caller do this", which is a per-route question.

An audit on 2026-09-19 counted the per-route answers: 16 of about 440 routes
carried `require_admin`. `/api/users` and `/api/mqtt` were fully gated, two of
26 field-solver routes were, and `/api/settings` was not gated at all. So any
signed-in user could write the deployment's own configuration. That is not a
theoretical reach: `appconfig.set_override` does `setattr(settings, key, value)`
on the live singleton, so a write lands on the next request, not at the next
restart. An ordinary account could rotate `httplib_token` and invalidate every
installed `.kicad_httplib`, move `public_base_url` out from under every
generated datasheet link and PCM URL, repoint `render_url` at a host of its
choosing, or replace the Anthropic and JLCPCB keys.

Nothing had gone wrong. Three people hold accounts and all three are trusted.
The exposure was that the gap was invisible: no test asserted the role model,
so the difference between `/api/settings` and `/api/users` beside it was not
a decision anybody had made, it was an omission nobody could see.

## Decision Drivers

* A configuration knob that takes effect on the next request is a deployment
  control, not a preference.
* The role model should be legible. "Which routes are admin-only" had no
  answer short of grepping 36 routers.
* A dropped `require_admin` is silent — the route keeps working, for everybody.
* The platform is on the internet, and an account is one password.
* Do not invent a permission system for a three-person deployment.

## Considered Options

* Gate the configuration surface on `require_admin`, and write the admin-only
  set down in a test
* Gate it, and rely on review to keep it gated
* Introduce per-capability permissions instead of the two roles
* Leave it, and document that every signed-in user is trusted with the
  deployment

## Decision Outcome

Chosen option: "Gate the configuration surface on `require_admin`, and write
the admin-only set down in a test", because it closes the one surface whose
blast radius reaches other people's KiCad installations, and because the test
is what stops the set drifting back.

Gated by this record:

* `GET`, `PUT` and `DELETE` on `/api/settings` — the whole router. The GET goes
  with the writes: the non-secret half names the render service and the
  deployment's address, and a read only an admin can act on serves nobody else.
  Secrets were never returned; `appconfig.describe` reports `is_set` only, and
  that is unchanged.
* `POST /api/fieldsolver/rules` and `DELETE /api/fieldsolver/rules/{rid}`. A
  rule set is the fab's own limits — the same class of shared fact as a
  stackup, which decision 0002 already made admin-only, and it is edited from
  the control beside it.
* `PUT /api/fx` and `POST /api/fx/refresh`. Every document in the register
  converts to USD through these, so one hand-typed rate moves every batch
  cost and every order margin at once (user decision 2026-09-19).
* The ARCHIVE-WIDE datasheet jobs: `POST /api/datasheets/fetch-all`,
  `/classify`, `/index`, `/index/stop`, `/restamps/collapse`,
  `/storage/reclaim` and `DELETE /api/datasheets/broken` (user decision
  2026-09-19). Each walks every document, several write new PDF versions that
  bump the components pinning them, and two delete.

Three READS stay open although their writes do not, and that is deliberate:
`GET /api/fx`, `GET /api/fx/at` and `GET /api/datasheets/fetch-status`.
`/api/fx/at` backs the invoice pages' preview of stored figures, so gating it
would break a page that has nothing to do with administration. The other two
are the answer to a question a non-admin genuinely has — "is HUF missing", "is
this datasheet archived yet" — and the honest response to a missing rate is to
let the person see it and ask, not to hide the table as well as the button.
The per-datasheet `POST /{id}/fetch` and `POST /{id}/upload` stay open for the
same reason: attaching one part's document is ordinary library work, and
gating it would put an admin in the middle of normal verification.

The Admin page hides the Configuration tab from a non-admin, who now lands on
Datasheets. The Exchange rates and Datasheets tabs stay VISIBLE and lose their
buttons — the table and the status readout are worth reading, the actions are
not offered. The field solver hides the rules Edit button, as it already hid
the stackup one. **All of these are courtesies.** The gate is the API's, and a
hidden control is not a control.

Deliberately NOT gated, and this is the boundary the record draws: the review
axis, production, orders, invoices, projects, the flasher, the agent and the
library itself stay open to any signed-in user. Those are the work. A role is
for the deployment, for other people's credentials, and for the shared
reference data every project reads — the fab's stackups and rules, the
exchange rates, the archive as a whole. It is not for deciding who may do
their job on one part, one batch or one board.

### Consequences

* Good, because the one surface that can reach into other people's KiCad
  installations now needs the role that manages accounts.
* Good, because `api/tests/auth/test_role_gates.py` states the admin-only set
  as data, so adding a gate is a line and removing one is a failure.
* Good, because the two field-solver surfaces that are the same kind of fact
  are now gated the same way.
* Bad, because a non-admin who needs a knob changed has to ask an admin.
  Accepted: there are three accounts and one admin, and none of these knobs
  is touched in a normal week.
* Bad, because the role model is now genuinely two-tier, and the next person
  adding an admin route has to notice the test. That is the intent.
* Neutral: `cors_origins` was in reach before this change but not exploitable
  live — `CORSMiddleware` captured the list at startup, so a write needed a
  restart to matter. Its `restart` flag says `false` and is wrong. Left as
  found; it is a display bug, not an access one.

### Confirmation

`python -m pytest tests/auth -q` from `api/`, which needs no database. It walks
the mounted app and asserts the gated set equals `EXPECTED`, in both
directions — a listed route that lost its gate fails, and a gated route nobody
listed fails too. Both spellings count: `Depends(require_admin)` and a bare
`require_admin(request)` in the body.

Verified on 2026-09-19: 32 passed. Removing the dependency from
`PUT /api/settings/{key}` made exactly that case fail, and restoring it passed
again. Against the running dev API, `/api/settings` and `/api/fieldsolver/rules`
answer 401 anonymously and 200 to an admin. In the browser, a non-admin sees
three Admin tabs and lands on Datasheets, `?tab=config` falls back to
Datasheets, the rates table renders all 29 rows with no Override and no
Refresh, the datasheet status line renders with no job buttons, and no
field-solver Edit button appears. An admin sees six tabs, 29 Override buttons,
Refresh, both datasheet job buttons and both field-solver Edit buttons.

## Pros and Cons of the Options

### Gate it, and rely on review to keep it gated

* Good, because it is the smaller change.
* Bad, because this is precisely what did not work. `/api/users` was gated on
  every route from the day it was written and `/api/settings` never was, and
  the difference survived every review in between.

### Per-capability permissions

* Good, because "may edit FX rates" is a more honest unit than "is an admin".
* Bad, because it is a permission system for three people, and every route
  would need a capability assigned before the first one meant anything.
* Bad, because a half-populated permission table reads as a policy while
  behaving as a default.

### Leave it, and document that every signed-in user is trusted

* Good, because it is truthful about a three-person deployment.
* Bad, because the account set will grow, and the day it does the exposure is
  already there rather than being added deliberately.
* Bad, because it makes `require_admin` on `/api/users` arbitrary: if every
  user is trusted with the deployment, they may as well manage accounts.

## More Information

* The audit that prompted this: 16 of about 440 routes gated, three gaps named
  — the settings router, the field-solver rule sets, and no test at all. The
  exchange rates and the datasheet jobs were reported in the same pass as
  open questions rather than as gaps, and answered the same day: both admin.
* [0002](0002-field-solver-in-the-platform.md) made stackup writes admin-only
  for the reason this record extends to rule sets.
* [0033](0033-the-broker-observes-devices-it-never-commands.md) made every MQTT
  route admin-only, for a credential rather than for configuration.
* [0010](0010-a-git-token-belongs-to-an-account.md) is the counter-example that
  stays as it is: git credentials are open to any signed-in user on purpose,
  because setting a raw token on a project always was, and gating one half
  would forbid the safe path while leaving the unsafe one open.
* Revisit if the account list grows past a handful of people who all administer
  the platform, or if a non-admin needs a configuration knob often enough that
  asking becomes the friction.
