"""Fold the per-file version pool into content-addressed blobs and file sets.

Decision 0029. Before it, one berryware release was stored three times: as
`device_file_versions` (a version number per file), as a `berry_bundles` row
listing those versions, and as `deployment_files` pinning the same versions
again under each deployment version — with `files_fingerprint`, `files_label`
and `berry_bundle_id` cached on the version and re-derived after every edit.
After it, a version pins ONE `file_sets` row for berryware and one for
artwork, a set is a manifest of (filename, blob), and a blob is bytes keyed by
sha256, shared platform wide.

The fold is one transaction, guarded by the presence of `deployment_files`:

1. every distinct sha256 in `device_file_versions` becomes a `file_blobs` row;
2. every `berry_bundles` row becomes a berryware set, keeping its id, and
   twins with the same fingerprint (the same release imported into two
   projects) collapse into the lower id;
3. every deployment version's berryware pins become (or find) a set by
   fingerprint, and its artwork pins a one-file artwork set; artwork versions
   nothing pinned get a set too, so no drawing is lost;
4. the version columns move to `file_set_id` / `artwork_set_id`;
5. the fold is CHECKED — every version that pinned berryware must now point
   at a set whose fingerprint equals its old `files_fingerprint` when it
   pinned no artwork — and only then are the old tables and columns dropped.

A check failure rolls the whole transaction back and the API comes up on the
old shape, which the ORM can no longer read; that is deliberate, because a
half-migrated file store is worse than a loud failure. Idempotent: a second
start finds no `deployment_files` and skips.
"""
from __future__ import annotations

import hashlib
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger("uvicorn.error")

# name -> "ok: …" | "skipped" | "failed: …"; merged into GET /api/health/schema.
RESULT: dict[str, str] = {}


def _has_table(conn, name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:n) IS NOT NULL"),
                             {"n": f"public.{name}"}).scalar())


def _fingerprint(files) -> str:
    body = "\n".join(f"{name}={sha}" for name, sha in sorted(files))
    return hashlib.sha256(body.encode()).hexdigest() if body else ""


def _ensure_set(conn, kind: str, label: str, entries, created_by="", comment="",
                created_at=None, want_id=None) -> int:
    """entries: [(filename, sha256)]. Returns the set id, existing or new."""
    fp = _fingerprint(entries)
    found = conn.execute(text("SELECT id FROM file_sets WHERE fingerprint = :fp"),
                         {"fp": fp}).scalar()
    if found is not None:
        if label:
            conn.execute(text(
                "UPDATE file_sets SET label = :l WHERE id = :id "
                "AND (label = '' OR label LIKE '% files')"), {"l": label, "id": found})
        return int(found)
    params = {"kind": kind, "label": label or f"{len(entries)} files", "fp": fp,
              "by": created_by or "", "comment": comment or ""}
    if want_id is not None:
        params["id"] = want_id
        params["at"] = created_at
        sid = conn.execute(text(
            "INSERT INTO file_sets (id, kind, label, fingerprint, comment, created_by, created_at) "
            "VALUES (:id, :kind, :label, :fp, :comment, :by, COALESCE(:at, now())) RETURNING id"),
            params).scalar()
    else:
        params["at"] = created_at
        sid = conn.execute(text(
            "INSERT INTO file_sets (kind, label, fingerprint, comment, created_by, created_at) "
            "VALUES (:kind, :label, :fp, :comment, :by, COALESCE(:at, now())) RETURNING id"),
            params).scalar()
    ordered = sorted(entries, key=lambda e: (e[0] == "autoexec.be", e[0]))
    for pos, (name, sha) in enumerate(ordered):
        conn.execute(text(
            "INSERT INTO file_set_entries (file_set_id, blob_id, filename, position) "
            "SELECT :sid, id, :name, :pos FROM file_blobs WHERE sha256 = :sha"),
            {"sid": sid, "name": name, "pos": pos, "sha": sha})
    return int(sid)


def migrate(engine: Engine) -> None:
    try:
        with engine.begin() as conn:
            # `create_all` builds the three new tables but never alters an
            # existing one, so the version's two pointers are added here.
            for col in ("file_set_id", "artwork_set_id"):
                conn.execute(text(
                    f"ALTER TABLE deployment_versions ADD COLUMN IF NOT EXISTS {col} integer "
                    f"REFERENCES file_sets(id)"))
            if not _has_table(conn, "deployment_files"):
                RESULT["file_sets.fold"] = "skipped"
                return
            # A database from before decision 0026 lacks the kind and the
            # binary columns the copy below reads; add them empty.
            conn.execute(text("ALTER TABLE device_files ADD COLUMN IF NOT EXISTS "
                              "kind varchar(20) NOT NULL DEFAULT 'berryware'"))
            conn.execute(text("UPDATE device_files SET kind = 'artwork' WHERE kind = 'berryware' "
                              "AND (lower(filename) LIKE '%.lbrn' OR lower(filename) LIKE '%.lbrn2')"))
            conn.execute(text("ALTER TABLE device_file_versions ADD COLUMN IF NOT EXISTS "
                              "is_binary boolean NOT NULL DEFAULT false"))
            conn.execute(text("ALTER TABLE device_file_versions ADD COLUMN IF NOT EXISTS "
                              "content_bytes bytea"))
            # 1. blobs — one per distinct sha256, newest row wins on content
            #    (they are identical by definition of the key).
            conn.execute(text("""
                INSERT INTO file_blobs (sha256, content, is_binary, content_bytes, size_bytes, created_at)
                SELECT DISTINCT ON (sha256) sha256, content, is_binary, content_bytes, size_bytes, created_at
                FROM device_file_versions
                WHERE sha256 <> ''
                ORDER BY sha256, id
                ON CONFLICT (sha256) DO NOTHING
            """))
            n_blobs = conn.execute(text("SELECT count(*) FROM file_blobs")).scalar()

            # 2. bundles -> berryware sets, ids kept, twins collapsed.
            bundles = conn.execute(text(
                "SELECT id, label, comment, created_by, created_at FROM berry_bundles ORDER BY id"
            )).fetchall()
            bundle_to_set: dict[int, int] = {}
            for b in bundles:
                entries = conn.execute(text("""
                    SELECT f.filename, v.sha256
                    FROM berry_bundle_files bf
                    JOIN device_file_versions v ON v.id = bf.device_file_version_id
                    JOIN device_files f ON f.id = v.device_file_id
                    WHERE bf.berry_bundle_id = :b ORDER BY bf.position
                """), {"b": b.id}).fetchall()
                bundle_to_set[b.id] = _ensure_set(
                    conn, "berryware", b.label, [(e.filename, e.sha256) for e in entries],
                    b.created_by, b.comment, b.created_at, want_id=b.id)

            # The bundles kept their ids, so every later set must come after them.
            conn.execute(text(
                "SELECT setval('file_sets_id_seq', GREATEST((SELECT max(id) FROM file_sets), 1))"))

            # 3. every artwork version becomes a one-file artwork set, pinned or not.
            art = conn.execute(text("""
                SELECT v.id, f.filename, v.sha256, v.version_no, v.comment, v.created_by, v.created_at
                FROM device_file_versions v JOIN device_files f ON f.id = v.device_file_id
                WHERE f.kind = 'artwork' AND v.sha256 <> '' ORDER BY v.id
            """)).fetchall()
            art_version_to_set: dict[int, int] = {}
            for a in art:
                art_version_to_set[a.id] = _ensure_set(
                    conn, "artwork", f"{a.filename} v{a.version_no}", [(a.filename, a.sha256)],
                    a.created_by, a.comment, a.created_at)

            # 4. deployment versions: berryware pins -> a set (found by
            #    fingerprint, made if ad hoc), artwork pins -> the artwork set.
            versions = conn.execute(text(
                "SELECT id, files_label, files_fingerprint FROM deployment_versions ORDER BY id"
            )).fetchall()
            checked = 0
            for v in versions:
                pins = conn.execute(text("""
                    SELECT df.device_file_version_id AS vid, f.filename, f.kind, x.sha256
                    FROM deployment_files df
                    JOIN device_file_versions x ON x.id = df.device_file_version_id
                    JOIN device_files f ON f.id = x.device_file_id
                    WHERE df.deployment_version_id = :v ORDER BY df.position
                """), {"v": v.id}).fetchall()
                berry = [(p.filename, p.sha256) for p in pins if p.kind != "artwork"]
                artp = [p for p in pins if p.kind == "artwork"]
                set_id = None
                if berry:
                    set_id = _ensure_set(conn, "berryware", v.files_label or "", berry)
                art_id = None
                if artp:
                    if len(artp) > 1:
                        # Nothing on the platform pins two drawings; one set
                        # per version keeps the model honest if that changes.
                        art_id = _ensure_set(conn, "artwork", v.files_label or "",
                                             [(p.filename, p.sha256) for p in artp])
                    else:
                        art_id = art_version_to_set[artp[0].vid]
                conn.execute(text(
                    "UPDATE deployment_versions SET file_set_id = :s, artwork_set_id = :a "
                    "WHERE id = :v"), {"s": set_id, "a": art_id, "v": v.id})
                # 5. the check: the set's fingerprint must reproduce the old
                #    cached one whenever the old one covered exactly this set.
                if berry and not artp:
                    got = conn.execute(text("SELECT fingerprint FROM file_sets WHERE id = :s"),
                                       {"s": set_id}).scalar()
                    if got != v.files_fingerprint:
                        raise RuntimeError(
                            f"version {v.id}: set fingerprint {got} != cached "
                            f"{v.files_fingerprint} — rolling back")
                    checked += 1
            # Every version that pinned anything must now point somewhere.
            stranded = conn.execute(text("""
                SELECT count(DISTINCT df.deployment_version_id) FROM deployment_files df
                JOIN deployment_versions v ON v.id = df.deployment_version_id
                WHERE v.file_set_id IS NULL AND v.artwork_set_id IS NULL
            """)).scalar()
            if stranded:
                raise RuntimeError(f"{stranded} version(s) pinned files but got no set — rolling back")

            # 6. retire the old shape.
            for col in ("files_fingerprint", "files_label", "berry_bundle_id"):
                conn.execute(text(f"ALTER TABLE deployment_versions DROP COLUMN IF EXISTS {col}"))
            for table in ("deployment_files", "berry_bundle_files", "berry_bundles",
                          "device_file_versions", "device_files"):
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            conn.execute(text(
                "SELECT setval('file_sets_id_seq', GREATEST((SELECT max(id) FROM file_sets), 1))"))
            # A blob no set names was a file version nothing ever pinned or
            # bundled — not history, just bytes. Six of them on 2026-09-18.
            pruned = conn.execute(text(
                "DELETE FROM file_blobs b WHERE NOT EXISTS "
                "(SELECT 1 FROM file_set_entries e WHERE e.blob_id = b.id)")).rowcount
            n_sets = conn.execute(text("SELECT count(*) FROM file_sets")).scalar()
            RESULT["file_sets.fold"] = (
                f"ok: {n_blobs} blobs, {n_sets} sets from {len(bundles)} bundles + "
                f"{len(art)} artwork versions, {len(versions)} versions repointed, "
                f"{checked} fingerprints checked, {pruned} unreachable blobs pruned")
            log.info("flasher: " + RESULT["file_sets.fold"])
    except Exception as e:  # noqa: BLE001 — report, never block startup
        RESULT["file_sets.fold"] = f"failed: {type(e).__name__}: {e}"
        log.error("flasher: file-set fold did not apply: %s", RESULT["file_sets.fold"])
