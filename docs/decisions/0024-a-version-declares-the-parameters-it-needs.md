---
status: "accepted"
date: 2026-09-17
decision-makers: Mateusz Kowalik
---

# A version declares the parameters it needs; the values keep a revision log

## Context and Problem Statement

A deployment version pins firmware, berryware and a procedure. It does NOT pin
the parameter VALUES the procedure interpolates — `{SSId1}`, `{MqttHost}`,
`creds_salt`. Those live in a project-scoped `ParamSet`, Fernet-encrypted and
mutable, and that split was chosen deliberately on 2026-07-27: rotating a WiFi
password must not mint a new version of every deployment that uses it.

What the split left out is any record of the DEPENDENCY. The only statement
that a version needed `MqttHost` was the text `{MqttHost}` inside one of its
steps. Measured on the live database (2026-09-17):

* `Dongle_V2 config` **v10 needs seven keys**, **v18 needs four**, and all seven
  published versions point at the same set. Removing the three v18 stopped using
  breaks v10.
* `Aqua_V2 config` v1 is the same shape against its own set.

The user asked the question directly: "what happens if we change parameters'
names across different deployments or their meaning — if I would run the older
deployments it wouldn't work."

Measuring what actually happened found four distinct holes, not one:

1. **A rename or a removal** was caught, but only at RUN START, by
   `validate.check` — with a device already in the socket. Nothing warned at
   edit time and nothing named the versions at risk.
2. **A meaning change was invisible.** Same key, new value — a broker repointed,
   a salt rotated — passes every check the platform has. An old version runs
   against the new meaning and reports `pass`.
3. **A draft skipped validation entirely** (`if not draft_run:`). That is the
   worst place to skip it: `protocol.subst` leaves an unresolved placeholder as
   literal text, and `set_and_check` compares what it SENT against what it read
   back — both `"{MqttHost}"` — so the step **passes** and the device ships
   pointed at a broker called `{MqttHost}`.
4. **`param_set_id` was a plain integer, not a foreign key**, and
   `DELETE /param-sets/{id}` had no guard, so deleting a set left every version
   pointing at a dead id.

And one the work itself uncovered: `derive_credentials` reads `creds_salt`
straight out of the run's variables rather than interpolating `{creds_salt}`,
so a walk of the step strings reported the one key whose loss cannot be
recovered from at the bench as used by nobody.

## Decision Drivers

* Rotating a secret must stay a one-field edit, not a fleet-wide re-publish.
* A breaking edit must be refused where it is made, naming what it breaks.
* "Which values did THIS unit get?" must be answerable after a rotation,
  without storing the secret a second time.
* No backfill: 22 published versions exist and none of them can be re-published.

## Considered Options

* **Pin the values on the version.** Correct by construction, and it reverses
  the 2026-07-27 decision: every password rotation would mint a version of every
  deployment.
* **Version the ParamSet itself**, with versions pointing at a set version.
  Same problem from the other end — a rotation makes a new set version, and
  either every version follows it (no safety gained) or none does (the fleet
  splits).
* **Guards only**: validate drafts, refuse a delete in use, warn in the editor.
  Cheap, no migration, closes hole 3 and 4 — and leaves 1 late and 2 invisible.
* **Version the CONTRACT, log the values.** Chosen.

## Decision Outcome

Chosen option: **the contract sticks to the version, the values stick to the
project with a revision id, and the run points at both.**

* `DeploymentVersion.param_schema` — frozen on publish by
  `services/flasher/params.py::build_schema`: one entry per key the version
  needs, each recording whether it is a secret and whether it came from the
  version's own `param_defaults` or from the shared set. A key the version
  carries itself cannot be broken by editing the project's parameters, and
  saying so is what stops the editor warning about keys it does not own.
* `ParamSetRevision` — append-only, one row per write: `keys_added`,
  `keys_removed`, `changed`, the non-secret values for DISPLAY, and the full
  values in `values_enc`. **`changed` names the keys whose value moved and never
  prints the old one**, because the history page is read on a bench with other
  people in the room.
* **A revision can be REVERTED to**, and that is why the full values are kept
  (user request, same day). `POST /param-sets/{id}/revert` writes the revision's
  values as a NEW revision: reverting r5 to r2 produces r6, so the record still
  says r3-r5 happened and that somebody undid them. The breaking guard applies
  exactly as it does to a save, because an old revision can be missing a key a
  version published since then needs.
* **The trade that revert forces, stated plainly.** Keeping the values means an
  old secret is recoverable from history by anyone holding `SECRET_KEY` — the
  same condition under which the CURRENT secret is readable, and the same Fernet
  key, so it is not a new class of exposure. It was taken over the alternative
  because a revert that silently skipped `Password1` and `creds_salt` would
  restore a configuration that has never existed on any device, which is worse
  than the retention it avoids. A revision written before `values_enc` existed
  reports `restorable: false` and the page offers no button for it, rather than
  restoring an empty set over every parameter in the project.
* `ProgrammingRun.param_set_revision_id` — `params_snapshot` masks every
  secret, so it cannot answer "which salt did this unit get?". The revision id
  can, without storing the secret twice.
* **`PUT /param-sets/{name}` refuses a write that removes a key any PUBLISHED
  version declares**, and the 409 names them. `force` overrides and is recorded
  on the revision as `[forced]`. Drafts are deliberately not counted: their
  author is usually the person editing the parameters, and a guard people learn
  to force is worse than no guard.
* **`DELETE /param-sets/{id}` refuses while any version points at the set**, and
  `param_set_id` is now a real foreign key.
* **Drafts are validated like published versions** at run start.
* **A DEPLOYMENT names a set too** (`Deployment.param_set_id`), and that is the
  answer to "how is a deployment linked to parameters". Before it the link
  existed only on each version, chosen inside the composer's Parameters section
  — so a brand-new deployment was linked to nothing, and the first anyone knew
  of it was a publish refused for an unresolved `{MqttHost}`. Now: a new
  deployment in a project with exactly one set takes it (`_sole_param_set`;
  it refuses to guess when there are two), a first version inherits the
  deployment's, and a later version inherits from the version it was composed
  from. The version's pin is still what a run uses and is still immutable, so
  moving the deployment's set never rewrites a published version — the version
  card says `deployment now defaults elsewhere` when the two differ.
* `params.OP_PARAM_FIELDS` is a new DECLARATION SITE: an op that consumes a
  parameter by name rather than interpolating it must be listed there, or the
  guard silently under-reports. `derive_credentials` is its first entry, and
  `validate.check` now errors when such a parameter is missing — that case used
  to publish cleanly and fail mid-run, after the erase.

The parameters also left the Files page for `/production/parameters`. They are
not an artefact a version pins, like a firmware image or a berryware bundle;
they are what a version depends on and does not contain. The page shows the two
things that had nowhere to live: whether a key is used at all, and the history
of what moved. It edits in place — the page IS the editor, Save and Cancel
appear when something differs from what is stored.

Two things were built and then cut back the same day, on use:

* **The full "needed by" list was a column and is now the × tooltip.** A
  parameter set is scoped to ONE project, so the list only ever named sibling
  deployments of the project already picked at the top, and it was taking 42% of
  the table to say so. What stayed is the single fact that was useful: a key no
  published version reads is marked `unused`, so removing it is free. The guard
  never depended on the column — the server refuses the save and names the
  versions itself.
* **Secret values are shown in the clear.** Masking them with a show toggle was
  one more click on every visit, on a page behind the sign-in gate, for values
  somebody came here to read. Storage is untouched: the set is Fernet-encrypted
  at rest whatever is on screen.

### Consequences

* Good, because a breaking edit is refused where it is made, naming every
  version it would break, instead of surfacing at the bench.
* Good, because a meaning change is finally a recorded event, with a note, and
  a unit can be traced to the revision it was programmed from.
* Good, because a draft can no longer ship a device configured against the
  literal string `{MqttHost}` and report `pass`.
* Good, because `params.py` is now the ONE implementation of "which keys does
  this version use", shared by the publish gate, the editor and the freeze.
  `validate.py` lost its private copy of the walk.
* Bad, because a version published before this has no `param_schema`.
  `declared_keys` falls back to walking its steps rather than treating it as
  needing nothing — correct, and slower, on every parameter page load.
* Bad, because the revision log starts empty. A set edited before today has no
  history, and the page says so rather than implying the values never moved.
* Bad, because a rotated secret stays readable in the revision log. Accepted
  above, and the reason is written there rather than left for somebody to
  discover.
* Neutral: a ParamSet is still not versioned, on purpose. This decision does not
  reverse 2026-07-27 — it supplies the half that was missing.

### Confirmation

Measured against the live database on 2026-09-17, before and after:

* `dependents()` on the Dongle_V2 set names 7 published versions for each of
  `MqttHost`, `MqttPort`, `Password1`, `SSId1` and `creds_salt`, and none for
  `Topic`, `FriendlyName` or `MqttGroupTopic` — correct, because v10 carries
  those three as its own `param_defaults`.
* `PUT` removing `MqttHost` from the real set is refused with a 409 naming all
  seven versions; the set was verified unchanged afterwards.
* `DELETE` of that set is refused, naming 8 versions.
* A create + a value change wrote revisions 1 and 2, the second recording
  `changed: ["MqttHost"]` with its note and no old value.
* `validate.check` over all 22 versions reports the same two failures as before
  the refactor (both pre-existing placeholder-firmware errors), and a synthetic
  version with no set now errors with
  `step 27 (derive_credentials) needs the 'creds_salt' parameter`.
