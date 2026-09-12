# Projects module — git-tracked designs

Backend rules for projects, their git mirrors, snapshots and exports. Decision
[0009](../decisions/0009-the-git-mirror-is-the-source-archive.md) makes the mirror
the source archive and
[0010](../decisions/0010-a-git-token-belongs-to-an-account.md) makes a token an
account object.

Two neighbours: the money a project costs is in
[production-economics.md](production-economics.md), and simulating its schematic
is in [spice-runs.md](spice-runs.md).

Services: `gitrepo` (bare mirrors at `DATA_DIR/git/<id>.git`, plain git CLI,
token injected per-invocation via `http.extraheader` — never written to disk),
`storage` (MinIO), `crypto` (Fernet from `SECRET_KEY`), `project_ingest`,
`project_render`, `project_bom`, `fx`, `ladder`. Routers: `projects.py`,
`production_runs.py`.

- **Snapshots are immutable, keyed by commit sha** — MinIO render caches
  (`projects/<id>/renders/<sha>/…`) never invalidate. Checkouts under
  `DATA_DIR/checkouts/<id>/<sha>/` are disposable (`gitrepo.materialize`
  recreates them); the render container sees them read-only at `/data/...`.
- **`routers/account.py` is the self-service twin of `routers/users.py`.** It
  takes NO user id — the subject is always `request.state.user` — so no endpoint
  on it can be aimed at somebody else by changing a number in a URL, and it
  deliberately cannot touch role, active or delete (the self-lockout guards).
  Two traps it documents:
  - **Re-load the user into THIS request's session.** `AuthGate` resolves it
    with a session of its own and closes it, so `request.state.user` is
    DETACHED: reading a loaded column works and the first lazy load raises
    `DetachedInstanceError`. `require_admin` gets away without this only because
    it reads `.role` and nothing else.
  - **Password change is NOT here.** `POST /api/auth/password` already does it
    and does it better — it re-issues the session cookie after ending every
    session, so the caller is not signed out of the tab they are in.
- **A git token belongs to an ACCOUNT, and `_token(p)` resolves it**
  ([decision 0010](../decisions/0010-a-git-token-belongs-to-an-account.md)).
  `GitCredential` is one hosting account's token; `projects.git_credential_id`
  points at one; `projects.git_token_enc` survives as a per-project alternative
  for a one-off repo. **The credential WINS when both are set** — the reverse
  would let a stale project copy shadow a live account token with nothing on
  screen saying so, which is the exact failure this replaced (four projects, one
  account, one revoked copy, diagnosed only by fingerprinting the four secrets).
  `_project_json` therefore reports `token_source` (`credential`|`project`|`none`)
  and every surface must say which is in force, never just "a token is stored".
  - **`services/git_credential_migrate.py` groups by the DECRYPTED value.**
    Fernet is randomised, so one token encrypted twice gives two ciphertexts and
    `GROUP BY git_token_enc` would mint one credential per project — preserving
    the duplication it exists to remove. That is why the fold is Python.
  - **`POST /api/git-credentials/{id}/check` uses `git ls-remote` through
    `gitrepo._auth_args`**, per assigned project — never a provider API probe,
    which would exercise a different code path from the one that fails. It
    translates `could not read Username`, which means the credential was
    REFUSED and reads like a prompt bug. A credential no project uses reports
    that it cannot be tested rather than passing.
  - **Replacing a token clears the stored verdict.** The old answer described
    the old secret; saying nothing is right until somebody checks the new one.
  - Gating is any signed-in user, matching `routers/projects.py`, which has
    never been admin-gated. Tighten the two together or not at all.
- **The mirror IS the source archive — nothing else stores project source**
  ([decision 0009](../decisions/0009-the-git-mirror-is-the-source-archive.md)).
  Ingest used to write a `source.tar.gz` per snapshot into MinIO and never read
  it back: 16 of them cost 950 MB, while the mirrors holding every commit of
  every project cost 214 MB. `gitrepo.archive_tgz(project_id, sha)` rebuilds a
  byte-exact tree from the mirror on demand, with no network call. Two
  consequences: **`DATA_DIR/git` must be in the backup set**, and a project that
  is ever ingested from something other than a git remote would need its own
  stored copy, because there would be no mirror to rebuild from.
- **BOM extraction goes through kicad-cli** (`sch export bom`), never a manual
  schematic parse — KiCad resolves hierarchy, DNP, and variants. Matching:
  `${SYMBOL_NAME}` == `Component.name` first, then `LCSC Part`. Variant list
  comes from `.kicad_pro` → `schematic.variants` (KiCad 10; absent on 9).
- **NUL is illegal in argv**: git `--format` separators use `\x1f`, never `\x00`.
- **Click-maps** (`services/project_map.py`): hotspot geometry is parsed from
  the sch/pcb sources with `util/sexpr.py` (never kiutils — it chokes on new
  KiCad tokens), enriched with `SnapshotBomLine` matches, cached in MinIO as
  `map-v{MAP_VERSION}.json`. Bump `MAP_VERSION` on any format change. Bboxes
  are deliberately approximate (conservative corners, mirror-safe).
- **Notes/runs/history are never revision-filtered** — they are project-scoped;
  `ProjectNote.sha`/`ref_name` and `ProductionRun.snapshot_id` only record
  the commit context they were created against.

