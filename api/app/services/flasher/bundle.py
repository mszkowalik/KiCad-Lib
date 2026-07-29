"""Deployment-version identity: fingerprints, labels, composition, diff.

A deployment version binds firmware images + berryware files + procedure +
parameter wiring. The two fingerprints are DERIVED from the child rows and
cached on the version so the UI can say "firmware unchanged since v5" or
"3 files changed" without re-reading every row — cache, never authority.
Always recompute through `stamp()` after touching the children.
"""
from __future__ import annotations

import hashlib
from typing import Iterable

from ... import models as M

# Variables the engine produces on its own; the validator must not flag a
# placeholder that one of these (or a step's own `capture`) supplies.
RUNTIME_VARS = {
    "mac", "serial", "chip", "base_url", "operator",
    "mqtt_user", "mqtt_password", "sim_pin",
}


def firmware_fingerprint(images: Iterable[tuple[str, str]]) -> str:
    """sha256 over the ordered (address, asset sha256) pairs. Two versions
    flashing the same bytes to the same offsets share a fingerprint even if
    the rows were created separately."""
    body = "\n".join(f"{addr.lower()}={sha}" for addr, sha in sorted(images))
    return hashlib.sha256(body.encode()).hexdigest() if body else ""


def files_fingerprint(files: Iterable[tuple[str, str]]) -> str:
    """sha256 over the file SET (filename, content sha256), order-independent
    — reordering downloads is a procedure change, not a payload change."""
    body = "\n".join(f"{name}={sha}" for name, sha in sorted(files))
    return hashlib.sha256(body.encode()).hexdigest() if body else ""


def stamp(db, version: M.DeploymentVersion) -> None:
    """Recompute and store both fingerprints for a version."""
    db.flush()
    version.firmware_fingerprint = firmware_fingerprint(
        (img.address, img.asset.sha256) for img in version.images
    )
    version.files_fingerprint = files_fingerprint(
        (link.file_version.file.filename, link.file_version.sha256) for link in version.files
    )


def image_json(img: M.DeploymentImage) -> dict:
    a = img.asset
    return {
        "firmware_asset_id": a.id, "address": img.address, "filename": a.filename,
        "kind": a.kind, "chip": a.chip, "size_bytes": a.size_bytes, "sha256": a.sha256,
        "build_label": a.build_label,
    }


def file_json(link: M.DeploymentFile) -> dict:
    v = link.file_version
    return {
        "device_file_version_id": v.id, "device_file_id": v.device_file_id,
        "filename": v.file.filename, "version_no": v.version_no, "status": v.status,
        "size_bytes": v.size_bytes, "sha256": v.sha256, "position": link.position,
        "comment": v.comment,
    }


def version_json(db, v: M.DeploymentVersion, deep: bool = True) -> dict:
    out = {
        "id": v.id, "deployment_id": v.deployment_id, "version_no": v.version_no,
        "status": v.status, "comment": v.comment, "created_by": v.created_by,
        "approved_by": v.approved_by, "transport_profile": v.transport_profile,
        "monitor_baud": v.monitor_baud, "flash_config": v.flash_config,
        "param_set_id": v.param_set_id, "param_defaults": v.param_defaults,
        "firmware_fingerprint": v.firmware_fingerprint,
        "files_fingerprint": v.files_fingerprint,
        "files_label": v.files_label,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "image_count": len(v.images), "file_count": len(v.files),
        "step_count": len(v.steps or []),
    }
    if deep:
        out["images"] = [image_json(i) for i in v.images]
        out["files"] = [file_json(f) for f in v.files]
        out["steps"] = v.steps or []
        if v.param_set_id:
            ps = db.get(M.ParamSet, v.param_set_id)
            out["param_set_name"] = ps.name if ps else None
    return out


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
    prev_files = {(f.file_version.file.filename, f.file_version.sha256) for f in prev.files}
    cur_files = {(f.file_version.file.filename, f.file_version.sha256) for f in cur.files}
    prev_names = {n for n, _ in prev_files}
    cur_names = {n for n, _ in cur_files}
    changed = {n for n, _ in cur_files - prev_files if n in prev_names}
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
        parts.append(f"berryware ({files})")
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

    def file_map(v):
        return {f.file_version.file.filename: file_json(f) for f in v.files}

    a_img, b_img = img_map(prev), img_map(cur)
    a_file, b_file = file_map(prev), file_map(cur)
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
        "steps_changed": (prev.steps or []) != (cur.steps or []),
        "steps_before": prev.steps or [],
        "steps_after": cur.steps or [],
        "params_before": {"param_set_id": prev.param_set_id, "defaults": prev.param_defaults},
        "params_after": {"param_set_id": cur.param_set_id, "defaults": cur.param_defaults},
        "transport_before": {"profile": prev.transport_profile, "baud": prev.monitor_baud},
        "transport_after": {"profile": cur.transport_profile, "baud": cur.monitor_baud},
        "changes": changes_since(prev, cur),
    }
