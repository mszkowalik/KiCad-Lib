"""Deployment-version identity: fingerprints, file sets, composition, diff.

A deployment version binds firmware images + a berryware release + an artwork
drawing + procedure + parameter wiring. The firmware fingerprint is DERIVED
from the image rows and cached on the version so the UI can say "firmware
unchanged since v5" without re-reading every row — cache, never authority;
always recompute through `stamp()` after touching the images.

The files need no cache. A version pins a `FileSet` (decision 0029): an
immutable manifest of (filename, blob) whose fingerprint IS its identity, so
"same berryware as v5" is one integer comparison and the same folder imported
twice is the same row. Blobs are content-addressed and platform wide; a set
is what the user sees and pins ("release-1.3.11"), and the per-file version
numbers that used to sit underneath are gone.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable

from sqlalchemy import or_

from ... import models as M

# Variables the engine produces on its own; the validator must not flag a
# placeholder that one of these (or a step's own `capture`) supplies.
RUNTIME_VARS = {
    "mac", "serial", "chip", "base_url", "operator",
    "mqtt_user", "mqtt_password", "sim_pin",
}

# The two kinds of set, and how a filename lands in one of them. A marking
# template is a LightBurn project and nothing else has ever been artwork, so
# the extension is the rule: a set of .lbrn/.lbrn2 files is artwork, a set of
# anything else is berryware, and a mix is refused (decision 0029).
SET_KINDS = ("berryware", "artwork")
ARTWORK_EXTENSIONS = (".lbrn", ".lbrn2")


def is_artwork_name(filename: str) -> bool:
    return filename.lower().endswith(ARTWORK_EXTENSIONS)


def kind_of_names(filenames: Iterable[str]) -> str:
    """`artwork`, `berryware`, or `mixed` — the caller refuses the last."""
    kinds = {"artwork" if is_artwork_name(n) else "berryware" for n in filenames}
    if not kinds:
        return "berryware"
    return kinds.pop() if len(kinds) == 1 else "mixed"


def firmware_fingerprint(images: Iterable[tuple[str, str]]) -> str:
    """sha256 over the ordered (address, asset sha256) pairs. Two versions
    flashing the same bytes to the same offsets share a fingerprint even if
    the rows were created separately."""
    body = "\n".join(f"{addr.lower()}={sha}" for addr, sha in sorted(images))
    return hashlib.sha256(body.encode()).hexdigest() if body else ""


def files_fingerprint(files: Iterable[tuple[str, str]]) -> str:
    """sha256 over the file SET (filename, content sha256), order-independent
    — reordering downloads is a procedure change, not a payload change. The
    same formula the bundles used, so every historical run stamp still
    matches the set it was made from."""
    body = "\n".join(f"{name}={sha}" for name, sha in sorted(files))
    return hashlib.sha256(body.encode()).hexdigest() if body else ""


def stamp(db, version: M.DeploymentVersion) -> None:
    """Recompute and store the firmware fingerprint for a version."""
    db.flush()
    version.firmware_fingerprint = firmware_fingerprint(
        (img.address, img.asset.sha256) for img in version.images
    )


def version_entries(version: M.DeploymentVersion) -> list[tuple[M.FileSetEntry, str]]:
    """Every file the version pins, berryware first, each with its kind."""
    out: list[tuple[M.FileSetEntry, str]] = []
    if version.file_set is not None:
        out += [(e, version.file_set.kind) for e in version.file_set.entries]
    if version.artwork_set is not None:
        out += [(e, version.artwork_set.kind) for e in version.artwork_set.entries]
    return out


def version_files_fingerprint(version: M.DeploymentVersion) -> str:
    """The fingerprint over EVERYTHING the version pins — what a programming
    run stamps. Equals the berryware set's own when there is no artwork."""
    return files_fingerprint((e.filename, e.blob.sha256) for e, _ in version_entries(version))


def image_json(img: M.DeploymentImage) -> dict:
    a = img.asset
    return {
        "firmware_asset_id": a.id, "address": img.address, "filename": a.filename,
        "kind": a.kind, "chip": a.chip, "size_bytes": a.size_bytes, "sha256": a.sha256,
        "build_label": a.build_label,
    }


def entry_json(e: M.FileSetEntry, kind: str | None = None) -> dict:
    b = e.blob
    return {
        "set_id": e.file_set_id, "filename": e.filename,
        "kind": kind or e.file_set.kind,
        "position": e.position, "size_bytes": b.size_bytes, "sha256": b.sha256,
        "binary": bool(b.is_binary), "blob_id": b.id,
    }


def set_ref(s: M.FileSet | None) -> dict | None:
    """The short form a version carries: enough to label a pill and link."""
    if s is None:
        return None
    return {"id": s.id, "kind": s.kind, "label": s.label, "fingerprint": s.fingerprint,
            "file_count": len(s.entries)}


def files_kind(version: M.DeploymentVersion) -> str:
    """What a version's pinned files ARE, as one word the UI can label a card
    with: "berryware", "artwork", "mixed", or "" when nothing is pinned."""
    kinds = {k for _, k in version_entries(version)}
    if not kinds:
        return ""
    return kinds.pop() if len(kinds) == 1 else "mixed"


def version_json(db, v: M.DeploymentVersion, deep: bool = True) -> dict:
    entries = version_entries(v)
    out = {
        "id": v.id, "deployment_id": v.deployment_id, "version_no": v.version_no,
        "status": v.status, "comment": v.comment, "created_by": v.created_by,
        "approved_by": v.approved_by, "transport_profile": v.transport_profile,
        "monitor_baud": v.monitor_baud, "flash_config": v.flash_config,
        "param_set_id": v.param_set_id, "param_defaults": v.param_defaults,
        "firmware_fingerprint": v.firmware_fingerprint,
        "file_set": set_ref(v.file_set),
        "artwork_set": set_ref(v.artwork_set),
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "image_count": len(v.images), "file_count": len(entries),
        "files_kind": files_kind(v),
        "step_count": len(v.steps or []),
        # Whether this PROCEDURE asks for a SIM PIN. The bench hides the box
        # otherwise: a Dongle_V2 or an Aqua has no modem, and a field nobody
        # can use is a field somebody fills in by mistake.
        "needs_sim_pin": any(
            isinstance(step, dict) and step.get("op") == "lte_sim_pin"
            for step in (v.steps or [])
        ),
    }
    if deep:
        out["images"] = [image_json(i) for i in v.images]
        out["files"] = [entry_json(e, k) for e, k in entries]
        out["steps"] = v.steps or []
        if v.param_set_id:
            ps = db.get(M.ParamSet, v.param_set_id)
            out["param_set_name"] = ps.name if ps else None
    return out


def _file_map(v: M.DeploymentVersion) -> dict[str, dict]:
    return {e.filename: entry_json(e, k) for e, k in version_entries(v)}


def changes_since(prev: M.DeploymentVersion | None, cur: M.DeploymentVersion) -> dict:
    """What moved between two versions — the one-line summary each row in the
    version timeline shows, and the basis of the publish confirmation."""
    if prev is None:
        return {"firmware": "initial", "files": "initial", "procedure": "initial",
                "params": "initial", "summary": "first version"}
    parts = []
    fw = "unchanged" if prev.firmware_fingerprint == cur.firmware_fingerprint else "changed"
    if fw == "changed":
        parts.append("firmware")
    a, b = _file_map(prev), _file_map(cur)
    prev_names, cur_names = set(a), set(b)
    changed = {n for n in prev_names & cur_names if a[n]["sha256"] != b[n]["sha256"]}
    added, removed = cur_names - prev_names, prev_names - cur_names
    files = "unchanged"
    if changed or added or removed:
        bits = []
        if changed:
            bits.append(f"{len(changed)} changed")
        if added:
            bits.append(f"{len(added)} added")
        if removed:
            bits.append(f"{len(removed)} removed")
        files = ", ".join(bits)
        # Name the files by what they are: a mark version's summary must not
        # say "berryware" when the only thing that moved is the artwork.
        moved = {(b.get(n) or a[n])["kind"] for n in changed | added | removed}
        noun = moved.pop() if len(moved) == 1 else "files"
        parts.append(f"{noun} ({files})")
    proc = "unchanged" if (prev.steps or []) == (cur.steps or []) else "changed"
    if proc == "changed":
        n_prev, n_cur = len(prev.steps or []), len(cur.steps or [])
        proc = f"changed ({n_prev} → {n_cur} steps)" if n_prev != n_cur else "changed"
        parts.append("procedure")
    params = "unchanged"
    if (prev.param_set_id, prev.param_defaults) != (cur.param_set_id, cur.param_defaults):
        params = "changed"
        parts.append("parameters")
    if prev.transport_profile != cur.transport_profile or prev.monitor_baud != cur.monitor_baud:
        parts.append("transport")
    return {
        "firmware": fw, "files": files, "procedure": proc, "params": params,
        "changed_files": sorted(changed), "added_files": sorted(added),
        "removed_files": sorted(removed),
        "summary": ", ".join(parts) if parts else "no payload change",
    }


def diff(prev: M.DeploymentVersion, cur: M.DeploymentVersion) -> dict:
    """Full side-by-side for the diff view."""
    def img_map(v):
        return {i.address.lower(): image_json(i) for i in v.images}

    a_img, b_img = img_map(prev), img_map(cur)
    a_file, b_file = _file_map(prev), _file_map(cur)
    images = []
    for addr in sorted(set(a_img) | set(b_img)):
        before, after = a_img.get(addr), b_img.get(addr)
        state = ("unchanged" if before and after and before["sha256"] == after["sha256"]
                 else "added" if not before else "removed" if not after else "changed")
        images.append({"address": addr, "before": before, "after": after, "state": state})
    files = []
    for name in sorted(set(a_file) | set(b_file)):
        before, after = a_file.get(name), b_file.get(name)
        state = ("unchanged" if before and after and before["sha256"] == after["sha256"]
                 else "added" if not before else "removed" if not after else "changed")
        files.append({"filename": name, "before": before, "after": after, "state": state})
    return {
        "from": {"id": prev.id, "version_no": prev.version_no},
        "to": {"id": cur.id, "version_no": cur.version_no},
        "images": images,
        "files": files,
        "file_set_before": set_ref(prev.file_set), "file_set_after": set_ref(cur.file_set),
        "artwork_set_before": set_ref(prev.artwork_set),
        "artwork_set_after": set_ref(cur.artwork_set),
        "steps_changed": (prev.steps or []) != (cur.steps or []),
        "steps_before": prev.steps or [],
        "steps_after": cur.steps or [],
        "params_before": {"param_set_id": prev.param_set_id, "defaults": prev.param_defaults},
        "params_after": {"param_set_id": cur.param_set_id, "defaults": cur.param_defaults},
        "transport_before": {"profile": prev.transport_profile, "baud": prev.monitor_baud},
        "transport_after": {"profile": cur.transport_profile, "baud": cur.monitor_baud},
        "changes": changes_since(prev, cur),
    }


# ------------------------------------------------------------------ file sets

def set_users(db, s: M.FileSet) -> list[dict]:
    """Every deployment version that pins this set, for the usage pill and the
    delete guard — one query, reused by both so they cannot disagree."""
    rows = (
        db.query(M.DeploymentVersion, M.Deployment, M.Project)
        .join(M.Deployment, M.Deployment.id == M.DeploymentVersion.deployment_id)
        .join(M.Project, M.Project.id == M.Deployment.project_id)
        .filter(or_(M.DeploymentVersion.file_set_id == s.id,
                    M.DeploymentVersion.artwork_set_id == s.id))
        .order_by(M.Deployment.name, M.DeploymentVersion.version_no).all()
    )
    return [{"version_id": v.id, "version_no": v.version_no, "status": v.status,
             "deployment": d.name, "deployment_id": d.id,
             "project": p.name, "project_id": p.id}
            for v, d, p in rows]


def previous_for_name(db, s: M.FileSet, filename: str) -> M.FileSetEntry | None:
    """The newest OLDER set of the same kind that carries this filename — the
    reference for "same as release X" / "changed since release X" on the
    Files page. Lineages of different projects interleave, so this is a
    reading aid; the exact answer between two versions is the diff view."""
    return (
        db.query(M.FileSetEntry)
        .join(M.FileSet, M.FileSet.id == M.FileSetEntry.file_set_id)
        .filter(M.FileSet.kind == s.kind, M.FileSet.id < s.id,
                M.FileSetEntry.filename == filename)
        .order_by(M.FileSet.id.desc())
        .first()
    )


def set_json(db, s: M.FileSet, deep: bool = True) -> dict:
    users = set_users(db, s)
    out = {
        "id": s.id, "kind": s.kind, "label": s.label, "fingerprint": s.fingerprint,
        "comment": s.comment, "created_by": s.created_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "file_count": len(s.entries), "used_by": len(users),
        "size_bytes": sum(e.blob.size_bytes for e in s.entries),
        # Always present, so a picker can name an artwork set's one drawing
        # without a second request.
        "filenames": [e.filename for e in s.entries],
    }
    if deep:
        out["users"] = users
        files = []
        for e in s.entries:
            row = entry_json(e, s.kind)
            prev = previous_for_name(db, s, e.filename)
            row["previous"] = None if prev is None else {
                "set_id": prev.file_set_id, "label": prev.file_set.label,
                "same": prev.blob.sha256 == e.blob.sha256,
            }
            files.append(row)
        out["files"] = files
    return out


def normalise_text(raw: str) -> str:
    """Store text with LF endings, always.

    Content addressing is only useful if the same source yields the same
    hash whoever uploads it. A CRLF file read as bytes hashes differently
    from the same file read as text (Python translates newlines), which made
    5 of the V3 files report "changed" on every import when nothing had.
    The device does not care: Berry and JSON both accept LF.
    """
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def decode_upload(raw: bytes) -> tuple[str, bytes | None]:
    """Text, LF-normalised, or the bytes untouched when the upload is not
    UTF-8 text. A NUL byte is the tell for a binary that happens to decode."""
    if b"\x00" not in raw:
        try:
            return normalise_text(raw.decode("utf-8")), None
        except UnicodeDecodeError:
            pass
    return "", raw


def ensure_blob(db, raw: bytes) -> tuple[M.FileBlob, bool]:
    """Get-or-create the blob for these bytes. Returns (blob, created)."""
    content, binary = decode_upload(raw)
    stored = binary if binary is not None else content.encode("utf-8")
    sha = hashlib.sha256(stored).hexdigest()
    b = db.query(M.FileBlob).filter(M.FileBlob.sha256 == sha).one_or_none()
    if b is not None:
        return b, False
    b = M.FileBlob(sha256=sha, content=content, is_binary=binary is not None,
                   content_bytes=binary, size_bytes=len(stored))
    db.add(b)
    db.flush()
    return b, True


def blob_bytes(b: M.FileBlob) -> bytes:
    return (b.content_bytes or b"") if b.is_binary else b.content.encode("utf-8")


def order_entries(entries: Iterable[tuple[str, M.FileBlob]]) -> list[tuple[str, M.FileBlob]]:
    """Alphabetical, autoexec.be last — a partial download must never leave a
    bootable device with half its application."""
    return sorted(entries, key=lambda e: (e[0] == "autoexec.be", e[0]))


def ensure_set(db, entries: list[tuple[str, M.FileBlob]], label: str = "",
               created_by: str = "", comment: str = "") -> tuple[M.FileSet, bool]:
    """Get-or-create the set for this exact manifest. Returns (set, created).

    Identity is the fingerprint, so the same folder imported twice — under any
    label, by any project — is ONE row. A fresh label on an existing set is
    kept only if the set had a generic one ("N files"), because the first
    real name (release-1.3.11) is the one the fleet knows. Filenames must be
    unique, and a set is one kind: a drawing does not travel with scripts.
    """
    names = [n for n, _ in entries]
    if len(set(names)) != len(names):
        dup = next(n for n in names if names.count(n) > 1)
        raise ValueError(f"{dup} appears twice in one set")
    kind = kind_of_names(names)
    if kind == "mixed":
        raise ValueError("a set is berryware OR artwork — an .lbrn2 does not travel with scripts")
    fp = files_fingerprint((n, b.sha256) for n, b in entries)
    existing = db.query(M.FileSet).filter(M.FileSet.fingerprint == fp).one_or_none()
    if existing is not None:
        if label and (not existing.label or existing.label.endswith(" files")):
            existing.label = label
        return existing, False
    s = M.FileSet(kind=kind, label=label or f"{len(entries)} files", fingerprint=fp,
                  created_by=created_by, comment=comment)
    db.add(s)
    db.flush()
    for pos, (name, blob) in enumerate(order_entries(entries)):
        db.add(M.FileSetEntry(file_set_id=s.id, blob_id=blob.id, filename=name, position=pos))
    db.flush()
    return s, True


def prune_blobs(db) -> int:
    """Delete blobs no entry references any more — after a set is deleted.
    Content nothing names is not history, it is space."""
    used = db.query(M.FileSetEntry.blob_id).distinct()
    orphans = db.query(M.FileBlob).filter(~M.FileBlob.id.in_(used)).all()
    for b in orphans:
        db.delete(b)
    return len(orphans)
