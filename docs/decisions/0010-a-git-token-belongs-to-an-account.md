---
status: "accepted"
date: 2026-09-12
decision-makers: Mateusz Kowalik
---

# A git token belongs to an account, and projects point at it by name

## Context and Problem Statement

Every project stored its own encrypted token in `projects.git_token_enc`. Four
projects on the production server pointed at four repositories of one GitHub
account, so one secret existed as four independent copies, and nothing compared
them.

On 2026-09-12 three of those copies were the same live token and the fourth had
been revoked. The symptom was a single project failing to fetch with:

    fatal: could not read Username for 'https://github.com': terminal prompts disabled

which reads as a prompt or terminal bug and is nothing of the kind — git asks
for a username precisely when a credential was REFUSED. Diagnosing it took
comparing the four stored tokens by fingerprint and probing each against
GitHub's API; nothing in the platform surfaced that the four projects disagreed,
or that one of them had stopped working. The project had been broken long enough
to also lose its git mirror ([decision 0009](0009-the-git-mirror-is-the-source-archive.md)),
and the mirror could not be re-cloned precisely because the token was dead.

Rotating a token had the same shape: edit every project that uses the account,
and any one missed is a silent failure at some later date.

## Decision Drivers

* A secret stored N times is a secret that can differ in N places, and the
  platform had no way to notice that it did.
* Rotation cost is linear in projects, and a miss is silent until the next fetch.
* Nothing recorded whether a stored credential still worked.
* A one-off repository should not require creating a named account first.

## Considered Options

* Keep one token per project
* Named credentials, with the per-project token kept as an alternative
* Named credentials only, removing the per-project token
* Keep per-project tokens and add a "copy from another project" action

## Decision Outcome

Chosen option: **named credentials, with the per-project token kept as an
alternative**.

`git_credentials` holds one row per hosting ACCOUNT — a name, the encrypted
token, an optional host and login, and the verdict of the last check.
`projects.git_credential_id` points at one. The per-project token stays for a
one-off repository that does not warrant a named account.

**A credential WINS over a project's own token when both are set**, and
`GET /api/projects/{id}` reports `token_source` (`credential` | `project` |
`none`) so a project can never be ambiguous about which secret it uses. The
losing rule was deliberate: letting the project copy win would recreate exactly
the failure above, a stale secret shadowing a live one with nothing on screen
saying so.

Management lives on a new **Account page**, reached by clicking the signed-in
name in the top bar — not on Setup, which is administration of other people's
accounts and the deployment's knobs.

A **Check** action runs the same `git ls-remote`, through the same
`_auth_args`, that a real fetch uses, once per project assigned to the
credential, and stores the verdict with its date. It is deliberately not a
GitHub API probe: that would test a different code path from the one that fails.
A credential no project uses reports that it cannot be tested rather than
claiming to be fine.

### Consequences

* Good, because one account's token exists once. Rotation is one edit, and two
  projects on one account cannot disagree.
* Good, because a dead credential is visible before somebody needs it —
  `check_ok` is shown on the list with the date it was taken, and a credential
  nobody has checked reads "not checked", never "ok".
* Good, because the refusal message a revoked token produces is translated
  where it is shown: "the remote refused this token (expired, revoked, or no
  access to this repository)".
* Bad, because a credential is global to the platform, so any signed-in user can
  assign any project to any account. That matches what the project router
  already allowed — setting a raw token on a project has never been admin-gated
  — but it means the two must be revisited together, never one alone.
* Neutral, because `projects.git_token_enc` stays. It is a live alternative, not
  a vestige, and the startup migration only clears the values it folded.

### Confirmation

1. `GET /api/git-credentials` lists one credential per distinct token that was
   stored, with the projects using it.
2. Every project reports `token_source: "credential"`.
3. Pressing Check on the credential reports `ok` for every project.
4. On the local box after the migration: two credentials from four projects
   (three sharing the live token, one holding the revoked one), consolidated by
   hand to one after the dead token was replaced.

## Pros and Cons of the Options

### Keep one token per project

* Good, because it is what exists and needs no migration.
* Bad, because it is the defect: N copies of one secret, no comparison, silent
  divergence, and rotation cost linear in projects.

### Named credentials, with the per-project token kept

* Good, because the normal case gets an account and the one-off case still
  works with no ceremony.
* Good, because the migration is mechanical and reversible per project.
* Bad, because two sources of a secret exist, so precedence must be stated and
  shown. Answered by the credential winning and `token_source` being reported.

### Named credentials only

* Good, because there is exactly one place a token can live.
* Bad, because a throwaway repository then requires creating a named account
  first, and the user asked for both paths.

### Copy from another project

* Good, because it is a small change.
* Bad, because it makes MORE copies of the secret — it automates the thing that
  caused the incident, and rotation still touches every project.

## More Information

* `services/git_credential_migrate.py` — the one-shot fold. It groups by the
  DECRYPTED value, which is why it is Python and not SQL: Fernet is randomised,
  so encrypting one token twice gives two different ciphertexts and
  `GROUP BY git_token_enc` would make one credential per project, preserving
  exactly the duplication being removed.
* Migration names are provisional (`github.com`, `github.com (2)`) because
  nothing offline can tell which login a token belongs to. The platform does not
  guess one; the operator renames the row.
* An undecryptable token (SECRET_KEY changed since it was stored) is counted and
  LEFT in place rather than folded or deleted — it is lost either way, and
  removing the row would hide that.
* The `check_detail` on a credential is a stored string, so it can be stale by
  construction. It is always shown with `checked_at`, and a token replaced
  through PATCH clears the verdict rather than carrying the old one forward.
