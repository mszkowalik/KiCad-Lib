"""Production flasher: deployments, firmware, berryware, runs and devices.

ONE revision binds everything (user decision 2026-07-29, design.md §14): a
DEPLOYMENT VERSION pins firmware images at their offsets, the exact berryware
file versions, the procedure and the parameter wiring. A programming run pins
one deployment version, so "what did this device get" has a single answer.
Channels ("production", "bench") are named pointers at a version — going live
and rolling back are channel moves, never edits to history.

`GET /files/{version_id}/{filename}` is deliberately unauthenticated: the
DEVICE fetches it over plain HTTP with UrlFetch (no auth headers), same
reachability rule as the KiCad HTTP catalog.
"""
from __future__ import annotations

import hashlib
import io
import json
import struct
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile,
    WebSocket, WebSocketDisconnect,
)
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import String, cast, func, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import utcnow
from ..db import get_db
from .. import models as M
from ..services import storage
from ..services import crypto
from ..services import mqtt_monitor
from ..services.flasher import (bundle, checks as checks_svc, credentials,
                                params as params_svc, transports, validate)
from ..services.flasher import engine as engine_mod
from ..services.flasher.engine import (SERIAL_MAX, SERIAL_MIN, RunEngine)
from .util import acting_name, actor_of, audit

router = APIRouter(prefix="/api/flasher", tags=["flasher"])

# The NAMES a version may pin. The profiles themselves — baud, reset style,
# whether the monitor may touch DTR/RTS — live in `services/flasher/transports.py`,
# which is also what `/meta` serves and what the engine puts in a run's spec.
# They were TypeScript constants until 2026-09-17; see that module for why.
TRANSPORT_PROFILES = list(transports.NAMES)
FIRMWARE_KINDS = ["factory", "app", "filesystem", "safeboot"]
# The only two parts in production (user decision 2026-07-30).
CHIPS = ["esp32", "esp32c6"]
# Recommended flash offset per (chip, kind) — from the projects' own partition
# maps, so the composer pre-fills a correct address instead of "0x0" always:
#   esp32c6: esp32c6_partition_8MB_app3904k_fs3392k.csv (CE_Dongle_v3)
#   esp32:   Tasmota's standard ESP32 layout (bootloader 0x1000, app0 0x10000)
# A blank means "no safe default" — the layout decides, so the field stays free.
DEFAULT_OFFSETS = {
    "esp32": {"factory": "0x0", "app": "0x10000", "safeboot": "0x0", "filesystem": ""},
    "esp32c6": {"factory": "0x0", "app": "0xE0000", "safeboot": "0x0",
                "filesystem": "0x4B0000"},
}
# esp_chip_id_t from esp-idf. The bytes are the authority on what an image is
# built for — a dropdown is a guess.
ESP_CHIP_IDS = {0: "esp32", 2: "esp32s2", 5: "esp32c3", 9: "esp32s3",
                12: "esp32c2", 13: "esp32c6", 16: "esp32h2"}
STEP_OPS = [
    "esp_connect", "erase", "flash", "esp_reset", "await_reenumerate",
    "serial_open", "serial_close", "reset", "sleep", "wait_boot", "command",
    "set_and_check", "backlog", "berry", "expect", "assert_equals",
    "assert_range", "poll_until", "download_files", "derive_credentials",
    "lte_sim_pin", "mark_laser", "print_label",
]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ------------------------------------------------------------------ firmware

@router.get("/projects/{project_id}/firmware")
def list_firmware(project_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(M.FirmwareAsset)
        .filter(M.FirmwareAsset.project_id == project_id)
        .order_by(M.FirmwareAsset.uploaded_at.desc())
        .all()
    )
    # One grouped count instead of a query per row — the panel shows "used by"
    # on every asset, and that is also what the delete guard reports.
    counts = dict(
        db.query(M.DeploymentImage.firmware_asset_id, func.count(M.DeploymentImage.id))
        .group_by(M.DeploymentImage.firmware_asset_id)
        .all()
    )
    return [_firmware_json(a, used_by=counts.get(a.id, 0)) for a in rows]


ESP_MAGIC = 0xE9
# An ESP image starts with 0xE9. A padded whole-flash image starts with 0xFF
# and carries the bootloader at 0x1000 (ESP32) — both are legitimate.
ESP_MAGIC_OFFSETS = (0x0, 0x1000)


def _detect_chip(data: bytes) -> str:
    """Read the chip out of the ESP image header (offset 12, LE uint16).

    Handles both layouts: a bare app image starts with 0xE9, a padded
    whole-flash image starts at 0x1000 (ESP32 keeps its bootloader there).
    Returns "" when the bytes carry no header — e.g. a LittleFS image.
    """
    for off in ESP_MAGIC_OFFSETS:
        if len(data) > off + 14 and data[off] == ESP_MAGIC:
            return ESP_CHIP_IDS.get(struct.unpack_from("<H", data, off + 12)[0], "")
    return ""


def default_offset(chip: str, kind: str) -> str:
    return DEFAULT_OFFSETS.get(chip, {}).get(kind, "")


def _looks_flashable(data: bytes, kind: str) -> bool:
    if len(data) < 64 * 1024:
        return False  # no real app or filesystem image is this small
    if kind == "filesystem":
        return True  # LittleFS has its own layout, no ESP header
    return any(len(data) > off and data[off] == ESP_MAGIC for off in ESP_MAGIC_OFFSETS)


def _firmware_json(a: M.FirmwareAsset, used_by: int | None = None) -> dict:
    return {
        "id": a.id, "filename": a.filename, "sha256": a.sha256,
        "size_bytes": a.size_bytes, "chip": a.chip, "kind": a.kind,
        "flashable": a.flashable,
        "default_address": default_offset(a.chip, a.kind),
        "used_by": used_by,
        "build_label": a.build_label, "notes": a.notes,
        "uploaded_by": a.uploaded_by, "uploaded_at": _iso(a.uploaded_at),
    }


@router.post("/projects/{project_id}/firmware")
async def upload_firmware(
    project_id: int,
    file: UploadFile = File(...),
    kind: str = Form("factory"),
    chip: str = Form(""),
    build_label: str = Form(""),
    notes: str = Form(""),
    uploaded_by: str = Form(""),
    db: Session = Depends(get_db),
):
    uploaded_by = acting_name(uploaded_by)
    if kind not in FIRMWARE_KINDS:
        raise HTTPException(400, f"kind must be one of {FIRMWARE_KINDS}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    # The image header outranks the form: a mislabelled chip is how a build
    # ends up flashed onto the wrong part.
    detected = _detect_chip(data)
    if detected:
        chip = detected
    elif chip and chip not in CHIPS:
        raise HTTPException(400, f"chip must be one of {CHIPS}")
    sha = hashlib.sha256(data).hexdigest()
    existing = (
        db.query(M.FirmwareAsset)
        .filter(M.FirmwareAsset.project_id == project_id, M.FirmwareAsset.sha256 == sha)
        .one_or_none()
    )
    if existing:
        return {"existing": True, "chip_detected": detected, **_firmware_json(existing)}
    key = f"firmware/{project_id}/{sha}/{file.filename}"
    storage.put_bytes(key, data)
    asset = M.FirmwareAsset(
        project_id=project_id, filename=file.filename or "firmware.bin", sha256=sha,
        size_bytes=len(data), chip=chip, kind=kind, minio_key=key,
        build_label=build_label, notes=notes, uploaded_by=uploaded_by,
        flashable=_looks_flashable(data, kind),
    )
    db.add(asset)
    db.commit()
    audit(db, "flasher.firmware_upload", "firmware_asset", asset.id,
          details=f"{asset.filename} ({len(data)} B, {kind}, chip {asset.chip or '?'})",
          actor=uploaded_by)
    return {"existing": False, "chip_detected": detected, **_firmware_json(asset)}


class FirmwarePatch(BaseModel):
    chip: str | None = None
    kind: str | None = None
    build_label: str | None = None
    notes: str | None = None


def _firmware_usage(db: Session, asset_id: int) -> list[dict]:
    """Which deployment versions pin this image. Deleting one would rewrite
    what a run says it flashed, so usage is a hard stop."""
    rows = (
        db.query(M.DeploymentImage, M.DeploymentVersion, M.Deployment)
        .join(M.DeploymentVersion, M.DeploymentVersion.id == M.DeploymentImage.deployment_version_id)
        .join(M.Deployment, M.Deployment.id == M.DeploymentVersion.deployment_id)
        .filter(M.DeploymentImage.firmware_asset_id == asset_id)
        .all()
    )
    return [{"deployment": d.name, "version_no": v.version_no, "version_id": v.id}
            for _, v, d in rows]


@router.patch("/firmware/{asset_id}")
def patch_firmware(asset_id: int, body: FirmwarePatch, db: Session = Depends(get_db)):
    """Metadata only — the bytes are the identity and never change."""
    a = db.get(M.FirmwareAsset, asset_id)
    if a is None:
        raise HTTPException(404, "no such firmware asset")
    data = body.model_dump(exclude_unset=True)
    if "kind" in data and data["kind"] not in FIRMWARE_KINDS:
        raise HTTPException(400, f"kind must be one of {FIRMWARE_KINDS}")
    if data.get("chip") and data["chip"] not in CHIPS:
        raise HTTPException(400, f"chip must be one of {CHIPS}")
    for field in ("chip", "kind", "build_label", "notes"):
        if field in data and data[field] is not None:
            setattr(a, field, data[field])
    db.commit()
    return _firmware_json(a)


@router.delete("/firmware/{asset_id}")
def delete_firmware(asset_id: int, db: Session = Depends(get_db)):
    a = db.get(M.FirmwareAsset, asset_id)
    if a is None:
        raise HTTPException(404, "no such firmware asset")
    used = _firmware_usage(db, asset_id)
    if used:
        where = ", ".join(f"{u['deployment']} v{u['version_no']}" for u in used[:4])
        raise HTTPException(
            409, f"{a.filename} is pinned by {len(used)} deployment version(s) ({where}) — "
                 "programming runs record what they flashed, so it stays")
    key, name = a.minio_key, a.filename
    db.delete(a)
    db.commit()
    try:
        storage.delete_prefix(key)
    except Exception:  # noqa: BLE001 — the row is gone; a stray object is harmless
        pass
    audit(db, "flasher.firmware_delete", "firmware_asset", asset_id, details=name)
    return {"ok": True}


@router.get("/firmware/{asset_id}/usage")
def firmware_usage(asset_id: int, db: Session = Depends(get_db)):
    return {"versions": _firmware_usage(db, asset_id)}


@router.get("/firmware/{asset_id}/bin")
def firmware_bin(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(M.FirmwareAsset, asset_id)
    if asset is None:
        raise HTTPException(404, "no such firmware asset")
    data = storage.get_bytes(asset.minio_key)
    if data is None:
        raise HTTPException(410, "firmware bytes missing from storage")
    return Response(
        content=data, media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{asset.filename}"'},
    )


class PublishIn(BaseModel):
    approved_by: str = ""


# ------------------------------------------------------------------ file sets
# A RELEASE is a file set (decision 0029): an immutable manifest of
# (filename, blob), platform wide, identified by its fingerprint. Blobs are
# bytes keyed by sha256 and shared by every set. A deployment version pins one
# berryware set and one artwork set; nothing pins a file on its own any more,
# and no file carries a version number of its own.

def _set_or_404(db: Session, set_id: int) -> M.FileSet:
    s = db.get(M.FileSet, set_id)
    if s is None:
        raise HTTPException(404, "no such file set")
    return s


def _kind_arg(kind: str) -> str:
    if kind and kind not in bundle.SET_KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(bundle.SET_KINDS)}")
    return kind


@router.get("/file-sets")
def list_file_sets(kind: str = "", db: Session = Depends(get_db)):
    """Every set on the platform, newest first, with how many deployment
    versions pin each. Sets are not project-scoped: the same driver JSON in
    three projects is one blob, and the same release imported into two
    projects is one set (user decision 2026-09-18)."""
    q = db.query(M.FileSet)
    if _kind_arg(kind):
        q = q.filter(M.FileSet.kind == kind)
    return [bundle.set_json(db, s, deep=False) for s in q.order_by(M.FileSet.id.desc()).all()]


@router.get("/file-sets/{set_id}")
def get_file_set(set_id: int, db: Session = Depends(get_db)):
    """The manifest, who pins it, and per file whether it is the same as the
    newest older set that carried that name."""
    return bundle.set_json(db, _set_or_404(db, set_id))


@router.get("/file-sets/{set_id}/entries/{filename}")
def get_file_set_entry(set_id: int, filename: str, db: Session = Depends(get_db)):
    """One file's text, for the preview and the artwork thumbnail. A binary
    has no text to show; its bytes are at /files/{set_id}/{filename}."""
    s = _set_or_404(db, set_id)
    e = next((x for x in s.entries if x.filename == filename), None)
    if e is None:
        raise HTTPException(404, "no such file in this set")
    out = bundle.entry_json(e, s.kind)
    out["content"] = "" if e.blob.is_binary else e.blob.content
    return out


class FileSetPatch(BaseModel):
    label: str | None = None
    comment: str | None = None


@router.patch("/file-sets/{set_id}")
def patch_file_set(set_id: int, body: FileSetPatch, db: Session = Depends(get_db)):
    """Rename or annotate. The manifest is the identity and never changes — a
    different set of files is a different set (derive one)."""
    s = _set_or_404(db, set_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("label"):
        s.label = data["label"].strip()
    if data.get("comment") is not None:
        s.comment = data["comment"]
    db.commit()
    return bundle.set_json(db, s)


@router.delete("/file-sets/{set_id}")
def delete_file_set(set_id: int, db: Session = Depends(get_db)):
    """Refused while any deployment version pins it — that version is the
    record of what units were given, draft or published, current or not.
    Blobs nothing names afterwards are pruned with it."""
    s = _set_or_404(db, set_id)
    users = bundle.set_users(db, s)
    if users:
        where = ", ".join(f"{u['deployment']} v{u['version_no']}" for u in users[:4])
        raise HTTPException(409, {
            "error": f'"{s.label}" is pinned by {len(users)} deployment version(s) ({where}'
                     f"{', …' if len(users) > 4 else ''}) — it stays as their record",
            "users": users,
        })
    label = s.label
    db.delete(s)
    db.flush()
    pruned = bundle.prune_blobs(db)
    db.commit()
    audit(db, "flasher.file_set_delete", "file_set", set_id,
          details={"label": label, "blobs_pruned": pruned})
    return {"ok": True, "blobs_pruned": pruned}


async def _read_uploads(db: Session, files: list[UploadFile]) -> list[dict]:
    """Every upload as (bare filename, blob, whether the blob is new)."""
    out = []
    for upload in files:
        name = (upload.filename or "").split("/")[-1]
        if not name:
            continue
        blob, created = bundle.ensure_blob(db, await upload.read())
        out.append({"filename": name, "blob": blob, "created": created})
    return out


def _import_result(db: Session, s: M.FileSet, created: bool, uploads: list[dict],
                   changes: dict | None = None) -> dict:
    return {
        "set": bundle.set_json(db, s), "created": created,
        "files": sorted(({"filename": u["filename"], "size_bytes": u["blob"].size_bytes,
                          "sha256": u["blob"].sha256,
                          "state": "new" if u["created"] else "existing"} for u in uploads),
                        key=lambda r: r["filename"]),
        "changes": changes or {},
    }


@router.post("/file-sets/import")
async def import_file_set(
    files: list[UploadFile] = File(...),
    label: str = Form(""),
    comment: str = Form(""),
    created_by: str = Form(""),
    # "" = decide by the extensions; "artwork" = the marking step's upload,
    # refused unless every file is a LightBurn project.
    kind: str = Form(""),
    db: Session = Depends(get_db),
):
    """A whole folder or one file, the same path: the bytes become blobs
    (unchanged bytes are reused) and the manifest becomes a set — or finds the
    one that already exists, whatever the folder was called. This is the ONE
    way content enters the platform; there is no paste editor and no draft.
    """
    created_by = acting_name(created_by)
    uploads = await _read_uploads(db, files)
    if not uploads:
        raise HTTPException(400, "no files in the upload")
    names = [u["filename"] for u in uploads]
    found = bundle.kind_of_names(names)
    asked = _kind_arg(kind)
    if found == "mixed":
        raise HTTPException(400, "a set is berryware OR artwork — an .lbrn2 does not travel with scripts")
    if asked and asked != found:
        raise HTTPException(400, f"{', '.join(names)} is not {asked}: a marking template must be "
                                 "an .lbrn2 (or .lbrn), and a script must not be")
    if found == "artwork" and not label:
        label = names[0]
    try:
        s, created = bundle.ensure_set(db, [(u["filename"], u["blob"]) for u in uploads],
                                       label=label.strip(), created_by=created_by,
                                       comment=comment or (f"import ({len(uploads)} files)"
                                                           if len(uploads) > 1 else "upload"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    audit(db, "flasher.file_set_import", "file_set", s.id,
          details={"label": s.label, "files": len(uploads), "created": created},
          actor=created_by or "user")
    return _import_result(db, s, created, uploads)


@router.post("/file-sets/{set_id}/derive")
async def derive_file_set(
    set_id: int,
    files: list[UploadFile] = File([]),
    # JSON: filenames to leave out of the new set
    remove: str = Form("[]"),
    # JSON: [{"set_id": …, "filename": …}] — files borrowed from any other
    # set on the platform, by name; a borrowed file replaces one of the same
    # name in the base
    take: str = Form("[]"),
    label: str = Form(""),
    comment: str = Form(""),
    created_by: str = Form(""),
    db: Session = Depends(get_db),
):
    """A new set from an existing one: swap or add files by upload, borrow
    files from any other set, leave some out. This replaces both the per-file
    version and the hand-picked bundle: "release-1.3.11 with one driver fixed"
    is one call and one new row, and the base stays exactly as it was.
    """
    created_by = acting_name(created_by)
    base = _set_or_404(db, set_id)
    try:
        drop = set(json.loads(remove or "[]"))
        borrow = json.loads(take or "[]")
    except json.JSONDecodeError:
        raise HTTPException(400, "remove and take must be JSON")
    manifest: dict[str, M.FileBlob] = {e.filename: e.blob for e in base.entries}
    changes = {"replaced": [], "added": [], "removed": [], "borrowed": []}
    for name in list(manifest):
        if name in drop:
            del manifest[name]
            changes["removed"].append(name)
    for item in borrow:
        src = db.get(M.FileSet, int(item.get("set_id", 0)))
        e = next((x for x in (src.entries if src else []) if x.filename == item.get("filename")), None)
        if e is None:
            raise HTTPException(400, f"no file {item.get('filename')!r} in set {item.get('set_id')}")
        changes["replaced" if e.filename in manifest else "added"].append(e.filename)
        changes["borrowed"].append(f"{e.filename} from {src.label}")
        manifest[e.filename] = e.blob
    uploads = await _read_uploads(db, files)
    for u in uploads:
        changes["replaced" if u["filename"] in manifest else "added"].append(u["filename"])
        manifest[u["filename"]] = u["blob"]
    if not manifest:
        raise HTTPException(400, "the derived set would be empty")
    try:
        s, created = bundle.ensure_set(db, list(manifest.items()),
                                       label=(label or f"{base.label} (derived)").strip(),
                                       created_by=created_by,
                                       comment=comment or f"derived from {base.label}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    audit(db, "flasher.file_set_derive", "file_set", s.id,
          details={"from": base.id, "label": s.label, "created": created, **changes},
          actor=created_by or "user")
    return _import_result(db, s, created, uploads, changes)


@router.get("/files/{set_id}/{filename}")
def serve_set_file(set_id: int, filename: str, db: Session = Depends(get_db)):
    """What the DEVICE downloads with UrlFetch and what the bench fetches to
    mark. Unauthenticated (`authgate._OPEN_PREFIXES`); the URL ends with the
    filename because Tasmota saves by the last path segment."""
    s = db.get(M.FileSet, set_id)
    e = next((x for x in (s.entries if s else []) if x.filename == filename), None)
    if e is None:
        raise HTTPException(404, "no such file in this set")
    return Response(content=bundle.blob_bytes(e.blob), media_type="application/octet-stream")


# --------------------------------------------------------------- deployments
# ONE revision binds firmware + berryware + procedure + parameters (user
# decision 2026-07-29). Composing a new version is a single call: say what
# CHANGES, everything else is inherited from the version you start at.

# What a deployment IS, so the bench can offer the right button rather than
# guessing from the name. Backfilled once from `name ILIKE '% test'`; new
# deployments say it outright.
DEPLOYMENT_KINDS = ("flash", "test", "mark")


class DeploymentIn(BaseModel):
    name: str
    description: str = ""
    chip: str = ""
    # None = leave it alone. A PATCH that omitted it would otherwise reset a
    # test or mark deployment to "flash" and quietly take its button away.
    kind: str | None = None
    # Same rule: None leaves the flag as it is. On a TEST deployment, true
    # means every device of this project must pass it to read as verified.
    active: bool | None = None
    # The parameter set the deployment works against — the default its next
    # version inherits. `-1` means "clear it"; None means "leave it alone", the
    # same convention `kind` and `active` use, because a PATCH that omitted it
    # would otherwise unlink every deployment it touched.
    param_set_id: int | None = None


class ImageIn(BaseModel):
    firmware_asset_id: int
    address: str = "0x0"


class ComposeIn(BaseModel):
    """Compose a new draft version.

    `from_version_id` is the starting point; any section left as None is
    INHERITED from it, so "bump the firmware" is a two-field request. Starting
    from nothing (a first version) requires the sections you care about.
    """
    from_version_id: int | None = None
    comment: str = ""
    created_by: str = ""
    # sections — None means "inherit"
    images: list[ImageIn] | None = None
    # the berryware release and the artwork drawing, by set id; -1 clears
    file_set_id: int | None = None
    artwork_set_id: int | None = None
    steps: list[dict] | None = None
    param_set_id: int | None = None
    param_defaults: dict | None = None
    transport_profile: str | None = None
    monitor_baud: int | None = None
    flash_config: dict | None = None


def _deployment_json(d: M.Deployment, db: Session, deep: bool = False) -> dict:
    channels = (
        db.query(M.DeploymentChannel).filter(M.DeploymentChannel.deployment_id == d.id).all()
    )
    versions = sorted(d.versions, key=lambda v: v.version_no)
    prev_by_id = {}
    for i, v in enumerate(versions):
        prev_by_id[v.id] = versions[i - 1] if i else None
    out = {
        "id": d.id, "name": d.name, "description": d.description, "chip": d.chip,
        "kind": d.kind or "flash",
        "active": bool(d.active),
        "param_set_id": d.param_set_id,
        "param_set_name": (ps.name if (ps := db.get(M.ParamSet, d.param_set_id)) else None)
                          if d.param_set_id else None,
        "project_id": d.project_id, "current_version_id": d.current_version_id,
        "created_at": _iso(d.created_at),
        "channels": [
            {"name": c.name, "deployment_version_id": c.deployment_version_id,
             "version_no": (c.version.version_no if c.version else None),
             "status": (c.version.status if c.version else None),
             "updated_by": c.updated_by, "updated_at": _iso(c.updated_at)}
            for c in sorted(channels, key=lambda c: c.name)
        ],
        "versions": [
            {**bundle.version_json(db, v, deep=False),
             "changes": bundle.changes_since(prev_by_id[v.id], v)}
            for v in reversed(versions)
        ],
    }
    if deep and d.current_version_id:
        cur = db.get(M.DeploymentVersion, d.current_version_id)
        if cur:
            out["current"] = bundle.version_json(db, cur)
    return out


@router.get("/projects/{project_id}/deployments")
def list_deployments(project_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(M.Deployment).filter(M.Deployment.project_id == project_id)
        .order_by(M.Deployment.name).all()
    )
    return [_deployment_json(d, db) for d in rows]


def _deployment_kind(value: str) -> str:
    kind = (value or "flash").strip().lower()
    if kind not in DEPLOYMENT_KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(DEPLOYMENT_KINDS)}")
    return kind


def _sole_param_set(db: Session, project_id: int) -> int | None:
    """The project's parameter set when it has exactly one.

    Every project on this platform has one, named `production`. Guessing is
    still wrong when there are two — the author has to say which — so this
    answers None rather than picking the first.
    """
    rows = db.query(M.ParamSet).filter(M.ParamSet.project_id == project_id).all()
    return rows[0].id if len(rows) == 1 else None


@router.post("/projects/{project_id}/deployments")
def create_deployment(project_id: int, body: DeploymentIn, db: Session = Depends(get_db)):
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "no such project")
    kind = _deployment_kind(body.kind or "flash")
    d = M.Deployment(project_id=project_id, name=body.name.strip(),
                     description=body.description, chip=body.chip.strip(), kind=kind,
                     # A new deployment in a project that already has ONE set
                     # takes it. Every project here has exactly one, so the
                     # alternative is an empty field the author has to fill in
                     # with the only possible answer.
                     param_set_id=body.param_set_id if body.param_set_id not in (None, -1)
                     else _sole_param_set(db, project_id),
                     # A test starts OFF: it gates every device in the project,
                     # so somebody turns it on deliberately. Anything else is on.
                     active=(body.active if body.active is not None else kind != "test"))
    db.add(d)
    db.commit()
    return {"id": d.id}


@router.patch("/deployments/{deployment_id}")
def patch_deployment(deployment_id: int, body: DeploymentIn, request: Request,
                     db: Session = Depends(get_db)):
    d = db.get(M.Deployment, deployment_id)
    if d is None:
        raise HTTPException(404, "no such deployment")
    d.name = body.name.strip() or d.name
    d.description = body.description
    d.chip = body.chip.strip()
    if body.param_set_id is not None:
        d.param_set_id = None if body.param_set_id == -1 else body.param_set_id
    if body.kind is not None:
        d.kind = _deployment_kind(body.kind)
    if body.active is not None:
        d.active = body.active
        # Turning a test on or off re-judges every device in the project, so it
        # is a decision worth being able to look up later.
        audit(db, "flasher.deployment_active", "deployment", d.id,
              details=f"{d.name} ({d.kind}) active={d.active}", actor=actor_of(request))
    db.commit()
    return _deployment_json(d, db)


@router.get("/deployments/{deployment_id}")
def get_deployment(deployment_id: int, db: Session = Depends(get_db)):
    d = db.get(M.Deployment, deployment_id)
    if d is None:
        raise HTTPException(404, "no such deployment")
    return _deployment_json(d, db, deep=True)


@router.delete("/deployments/{deployment_id}")
def delete_deployment(deployment_id: int, db: Session = Depends(get_db)):
    """Delete a deployment that was never used.

    HARD REFUSAL when any programming run references one of its versions: a run
    is the record of what a physical device received, and deleting the version
    it points at would leave that history unreadable. Only genuinely unused
    deployments can go. Firmware assets and berryware files are NOT touched —
    they live in the project's pool and other deployments may pin them.
    """
    d = db.get(M.Deployment, deployment_id)
    if d is None:
        raise HTTPException(404, "no such deployment")
    version_ids = [v.id for v in d.versions]
    runs = (
        db.query(M.ProgrammingRun)
        .filter(M.ProgrammingRun.deployment_version_id.in_(version_ids or [-1]))
        .count()
    )
    if runs:
        raise HTTPException(
            409,
            f'"{d.name}" is the recorded deployment of {runs} programming run(s) — deleting it '
            "would orphan that history. Rename it or leave it as an archive instead.")
    batches = (
        db.query(M.ProductionRun)
        .filter(M.ProductionRun.deployment_version_id.in_(version_ids or [-1]))
        .all()
    )
    for b in batches:  # soft pointer: clear it rather than dangle
        b.deployment_version_id = None
    db.query(M.DeploymentChannel).filter(
        M.DeploymentChannel.deployment_id == d.id).delete(synchronize_session=False)
    name, count = d.name, len(version_ids)
    db.delete(d)  # cascades versions -> images + pinned-file links
    db.commit()
    audit(db, "flasher.deployment_delete", "deployment", deployment_id,
          details=f"{name} ({count} version(s), never used"
                  + (f", {len(batches)} batch pin(s) cleared" if batches else "") + ")")
    return {"ok": True, "deleted_versions": count, "batches_cleared": len(batches)}


@router.post("/deployments/{deployment_id}/versions")
def compose_version(deployment_id: int, body: ComposeIn, db: Session = Depends(get_db)):
    """Create a DRAFT version. Sections left None inherit from `from_version_id`."""
    d = db.get(M.Deployment, deployment_id)
    if d is None:
        raise HTTPException(404, "no such deployment")
    base = None
    if body.from_version_id:
        base = db.get(M.DeploymentVersion, body.from_version_id)
        if base is None or base.deployment_id != d.id:
            raise HTTPException(400, "from_version_id is not a version of this deployment")

    def inherit(field, base_value, given):
        return base_value if given is None else given

    transport = inherit("transport_profile", base.transport_profile if base else "uart_bridge",
                        body.transport_profile)
    if transport not in TRANSPORT_PROFILES:
        raise HTTPException(400, f"transport_profile must be one of {TRANSPORT_PROFILES}")
    steps = inherit("steps", (base.steps if base else []) or [], body.steps)
    for step in steps:
        if step.get("op") not in STEP_OPS:
            raise HTTPException(400, f"unknown op {step.get('op')!r}")

    version = M.DeploymentVersion(
        deployment_id=d.id,
        version_no=max((v.version_no for v in d.versions), default=0) + 1,
        status="draft", created_by=acting_name(body.created_by), comment=body.comment,
        transport_profile=transport,
        monitor_baud=inherit("monitor_baud", base.monitor_baud if base else 115200,
                             body.monitor_baud),
        flash_config=inherit("flash_config", base.flash_config if base else None,
                             body.flash_config),
        steps=steps,
        # A version inherits from the one it was composed FROM, and a first
        # version from the deployment's own set — which is what makes a new
        # deployment usable without opening the composer's Parameters section
        # at all.
        param_set_id=inherit("param_set_id",
                             base.param_set_id if base else d.param_set_id,
                             body.param_set_id),
        param_defaults=inherit("param_defaults", base.param_defaults if base else None,
                               body.param_defaults),
        file_set_id=_pick_set(db, "berryware", base.file_set_id if base else None,
                              body.file_set_id),
        artwork_set_id=_pick_set(db, "artwork", base.artwork_set_id if base else None,
                                 body.artwork_set_id),
    )
    db.add(version)
    db.flush()

    # --- firmware images
    images = body.images
    if images is None and base is not None:
        images = [ImageIn(firmware_asset_id=i.firmware_asset_id, address=i.address)
                  for i in base.images]
    seen = set()
    for pos, img in enumerate(images or []):
        asset = db.get(M.FirmwareAsset, img.firmware_asset_id)
        if asset is None or asset.project_id != d.project_id:
            raise HTTPException(400, f"firmware asset {img.firmware_asset_id} not in this project")
        if img.address in seen:
            raise HTTPException(400, f"two images at address {img.address}")
        seen.add(img.address)
        db.add(M.DeploymentImage(deployment_version_id=version.id,
                                 firmware_asset_id=asset.id, address=img.address, position=pos))

    db.flush()
    db.refresh(version)
    bundle.stamp(db, version)
    db.commit()
    audit(db, "flasher.version_compose", "deployment_version", version.id,
          details=f"{d.name} v{version.version_no} (draft)", actor=acting_name(body.created_by))
    return {**bundle.version_json(db, version),
            "validation": validate.check(db, version)}


def _pick_set(db: Session, kind: str, inherited: int | None, given: int | None) -> int | None:
    """Resolve a set pointer for a version: None inherits, a negative id
    clears, and an id must name a set of the right KIND — a drawing pinned as
    berryware would reach the device as a download."""
    if given is None:
        return inherited
    if given < 0:
        return None
    s = db.get(M.FileSet, given)
    if s is None:
        raise HTTPException(400, f"no such file set {given}")
    if s.kind != kind:
        raise HTTPException(400, f'"{s.label}" is {s.kind}, not {kind}')
    return s.id


@router.get("/deployment-versions/{version_id}")
def get_deployment_version(version_id: int, db: Session = Depends(get_db)):
    v = db.get(M.DeploymentVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such deployment version")
    d = db.get(M.Deployment, v.deployment_id)
    versions = sorted(d.versions, key=lambda x: x.version_no)
    idx = [x.id for x in versions].index(v.id)
    prev = versions[idx - 1] if idx else None
    runs = (
        db.query(M.ProgrammingRun)
        .filter(M.ProgrammingRun.deployment_version_id == v.id).count()
    )
    devices = (
        db.query(M.ProgrammingRun.device_unit_id)
        .filter(M.ProgrammingRun.deployment_version_id == v.id,
                M.ProgrammingRun.device_unit_id.isnot(None))
        .distinct().count()
    )
    batches = (
        db.query(M.ProductionRun)
        .filter(M.ProductionRun.deployment_version_id == v.id).all()
    )
    return {
        **bundle.version_json(db, v),
        "deployment": {"id": d.id, "name": d.name, "chip": d.chip, "project_id": d.project_id,
                       "kind": d.kind or "flash",
                       # The deployment's CURRENT default, so the card can say
                       # when this version is pinned to a different set. The
                       # version's own `param_set_id` is what a run uses.
                       "param_set_id": d.param_set_id},
        "changes": bundle.changes_since(prev, v),
        "validation": validate.check(db, v),
        "where_used": {
            "runs": runs, "devices": devices,
            "batches": [{"id": b.id, "label": b.label} for b in batches],
            "channels": [
                c.name for c in db.query(M.DeploymentChannel)
                .filter(M.DeploymentChannel.deployment_version_id == v.id)
            ],
        },
    }


@router.get("/deployment-versions/{version_id}/diff")
def diff_deployment_version(version_id: int, against: int | None = None,
                            db: Session = Depends(get_db)):
    cur = db.get(M.DeploymentVersion, version_id)
    if cur is None:
        raise HTTPException(404, "no such deployment version")
    if against:
        prev = db.get(M.DeploymentVersion, against)
        if prev is None or prev.deployment_id != cur.deployment_id:
            raise HTTPException(400, "the other version belongs to a different deployment")
    else:
        d = db.get(M.Deployment, cur.deployment_id)
        earlier = [v for v in sorted(d.versions, key=lambda x: x.version_no)
                   if v.version_no < cur.version_no]
        prev = earlier[-1] if earlier else None
    if prev is None:
        return {"from": None, "to": {"id": cur.id, "version_no": cur.version_no},
                "images": [], "files": [], "steps_changed": True,
                "changes": bundle.changes_since(None, cur)}
    return bundle.diff(prev, cur)


@router.get("/deployment-versions/{version_id}/validate")
def validate_deployment_version(version_id: int, db: Session = Depends(get_db)):
    v = db.get(M.DeploymentVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such deployment version")
    return validate.check(db, v)


class VersionPatch(BaseModel):
    """Edits allowed only while a version is still a DRAFT."""
    comment: str | None = None
    steps: list[dict] | None = None
    images: list[ImageIn] | None = None
    # explicit null (or -1) clears the pin; omitted leaves it alone
    file_set_id: int | None = None
    artwork_set_id: int | None = None
    param_set_id: int | None = None
    param_defaults: dict | None = None
    transport_profile: str | None = None
    monitor_baud: int | None = None
    flash_config: dict | None = None


@router.patch("/deployment-versions/{version_id}")
def patch_deployment_version(version_id: int, body: VersionPatch, db: Session = Depends(get_db)):
    v = db.get(M.DeploymentVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such deployment version")
    if v.status != "draft":
        raise HTTPException(409, f"version is {v.status} — published versions are immutable")
    d = db.get(M.Deployment, v.deployment_id)
    data = body.model_dump(exclude_unset=True)
    for field in ("comment", "param_set_id", "param_defaults", "monitor_baud", "flash_config"):
        if field in data:
            setattr(v, field, data[field])
    if "transport_profile" in data and data["transport_profile"]:
        if data["transport_profile"] not in TRANSPORT_PROFILES:
            raise HTTPException(400, f"transport_profile must be one of {TRANSPORT_PROFILES}")
        v.transport_profile = data["transport_profile"]
    if "steps" in data and data["steps"] is not None:
        for step in data["steps"]:
            if step.get("op") not in STEP_OPS:
                raise HTTPException(400, f"unknown op {step.get('op')!r}")
        v.steps = data["steps"]
    if "images" in data and data["images"] is not None:
        for old in list(v.images):
            db.delete(old)
        db.flush()
        seen = set()
        for pos, img in enumerate(body.images or []):
            asset = db.get(M.FirmwareAsset, img.firmware_asset_id)
            if asset is None or asset.project_id != d.project_id:
                raise HTTPException(400, f"firmware asset {img.firmware_asset_id} not in this project")
            if img.address in seen:
                raise HTTPException(400, f"two images at address {img.address}")
            seen.add(img.address)
            db.add(M.DeploymentImage(deployment_version_id=v.id, firmware_asset_id=asset.id,
                                     address=img.address, position=pos))
    if "file_set_id" in data:
        v.file_set_id = _pick_set(db, "berryware", v.file_set_id, data["file_set_id"] if data["file_set_id"] is not None else -1)
    if "artwork_set_id" in data:
        v.artwork_set_id = _pick_set(db, "artwork", v.artwork_set_id, data["artwork_set_id"] if data["artwork_set_id"] is not None else -1)
    db.flush()
    db.refresh(v)
    bundle.stamp(db, v)
    db.commit()
    return {**bundle.version_json(db, v), "validation": validate.check(db, v)}


@router.post("/deployment-versions/{version_id}/publish")
def publish_deployment_version(version_id: int, body: PublishIn, db: Session = Depends(get_db)):
    v = db.get(M.DeploymentVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such deployment version")
    if v.status == "rejected":
        raise HTTPException(409, "version was rejected")
    if v.status == "published":
        return bundle.version_json(db, v)
    if not v.comment.strip():
        raise HTTPException(409, "publishing needs a comment saying what changed and why")
    result = validate.check(db, v)
    if not result["ok"]:
        raise HTTPException(409, "validation failed: " + " | ".join(result["errors"]))
    # Freeze the CONTRACT at publish: which parameters this version needs and
    # where each came from. From here on, editing the project's values can be
    # refused by name instead of failing at the bench (decision 0024).
    v.param_schema = params_svc.build_schema(db, v)
    v.status = "published"
    v.approved_by = acting_name(body.approved_by)
    d = db.get(M.Deployment, v.deployment_id)
    d.current_version_id = v.id
    db.commit()
    audit(db, "flasher.version_publish", "deployment_version", v.id,
          details=f"{d.name} v{v.version_no}: {v.comment}", actor=v.approved_by)
    return bundle.version_json(db, v)


@router.post("/deployment-versions/{version_id}/reject")
def reject_deployment_version(version_id: int, body: PublishIn, db: Session = Depends(get_db)):
    v = db.get(M.DeploymentVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such deployment version")
    if v.status == "published":
        raise HTTPException(409, "already published — publish a newer version instead")
    v.status = "rejected"
    db.commit()
    return {"ok": True}


@router.delete("/deployment-versions/{version_id}")
def delete_deployment_version(version_id: int, db: Session = Depends(get_db)):
    """Delete a DRAFT that nothing has used, so discarding one leaves no trace.

    `reject` exists beside this and keeps the row as history; it is the right
    answer for a draft somebody worked on and decided against. This one is for
    the draft nobody wanted: since 2026-09-17 `New version` mints one on a
    single click, so looking at a procedure and changing your mind must not
    leave a rejected row behind forever.

    Published is refused outright — a published version is what a device was
    given. A draft is refused too once anything records it: a draft CAN be run
    as a bench trial, and those runs name it.
    """
    v = db.get(M.DeploymentVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such deployment version")
    if v.status == "published":
        raise HTTPException(409, "published versions are never deleted — they are what a "
                                 "device was given. Publish a newer one instead.")
    runs = (
        db.query(M.ProgrammingRun)
        .filter(M.ProgrammingRun.deployment_version_id == version_id).count()
    )
    if runs:
        raise HTTPException(409, {
            "error": f"{runs} programming run(s) record this version, so it cannot be "
                     "deleted. Reject it instead — the row stays as history.",
            "runs": runs,
        })
    chans = (
        db.query(M.DeploymentChannel)
        .filter(M.DeploymentChannel.deployment_version_id == version_id).all()
    )
    for c in chans:
        c.deployment_version_id = None
    d = db.get(M.Deployment, v.deployment_id)
    if d is not None and d.current_version_id == version_id:
        d.current_version_id = None
    db.delete(v)   # images and files cascade
    db.commit()
    audit(db, "flasher.version_delete", "deployment_version", version_id,
          {"deployment_id": v.deployment_id, "version_no": v.version_no})
    return {"ok": True}


class ChannelIn(BaseModel):
    deployment_version_id: int | None
    updated_by: str = ""


@router.put("/deployments/{deployment_id}/channels/{name}")
def set_channel(deployment_id: int, name: str, body: ChannelIn, db: Session = Depends(get_db)):
    """Point a channel at a version. This is how a release goes live and how a
    rollback happens — history is never edited."""
    d = db.get(M.Deployment, deployment_id)
    if d is None:
        raise HTTPException(404, "no such deployment")
    if body.deployment_version_id is not None:
        v = db.get(M.DeploymentVersion, body.deployment_version_id)
        if v is None or v.deployment_id != d.id:
            raise HTTPException(400, "that version belongs to another deployment")
        if v.status != "published":
            raise HTTPException(409, f"version is {v.status} — only published versions go on a channel")
    ch = (
        db.query(M.DeploymentChannel)
        .filter(M.DeploymentChannel.deployment_id == d.id, M.DeploymentChannel.name == name)
        .one_or_none()
    )
    if ch is None:
        ch = M.DeploymentChannel(deployment_id=d.id, name=name)
        db.add(ch)
    ch.deployment_version_id = body.deployment_version_id
    ch.updated_by = acting_name(body.updated_by)
    ch.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, "flasher.channel_set", "deployment", d.id,
          details=f"{d.name}: channel {name} -> version id {body.deployment_version_id}",
          actor=ch.updated_by)
    return {"ok": True}


# ---------------------------------------------------------------- param sets

class ParamSetIn(BaseModel):
    values: dict[str, str | int | float]
    updated_by: str = ""
    # Why the values changed. It ends up on the revision row, which is the only
    # record that a MEANING changed — a key whose name survives and whose value
    # moves passes every other check the platform has.
    note: str = ""
    # Remove a key a published version declares anyway. The refusal names the
    # versions; forcing it is a decision, so it is recorded on the revision.
    force: bool = False


@router.get("/projects/{project_id}/param-sets")
def list_param_sets(project_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(M.ParamSet).filter(M.ParamSet.project_id == project_id)
        .order_by(M.ParamSet.name).all()
    )
    out = []
    for ps in rows:
        keys = []
        if ps.values_enc:
            try:
                keys = sorted(json.loads(crypto.decrypt_token(ps.values_enc)).keys())
            except Exception:
                keys = ["<undecryptable>"]
        # Which published versions depend on each key. This is the fact the
        # editor never had: removing "Topic" breaks Dongle_V2 config v10, and
        # until decision 0024 the platform found that out at the bench.
        used = params_svc.dependents(db, ps.id)
        last = (
            db.query(M.ParamSetRevision)
            .filter(M.ParamSetRevision.param_set_id == ps.id)
            .order_by(M.ParamSetRevision.revision_no.desc())
            .first()
        )
        out.append({"id": ps.id, "name": ps.name, "keys": keys,
                    "used_by": {k: v for k, v in used.items()},
                    "revision_no": last.revision_no if last else 0,
                    "updated_by": ps.updated_by, "updated_at": _iso(ps.updated_at)})
    return out


@router.put("/projects/{project_id}/param-sets/{name}")
def put_param_set(project_id: int, name: str, body: ParamSetIn, db: Session = Depends(get_db)):
    ps = (
        db.query(M.ParamSet)
        .filter(M.ParamSet.project_id == project_id, M.ParamSet.name == name)
        .one_or_none()
    )
    if ps is None:
        ps = M.ParamSet(project_id=project_id, name=name)
        db.add(ps)
        db.flush()  # the revision row needs the id
    old: dict = {}
    if ps.values_enc:
        try:
            old = json.loads(crypto.decrypt_token(ps.values_enc))
        except Exception:  # noqa: BLE001 — an unreadable set is replaced wholesale
            old = {}
    new_values = dict(body.values)
    # The guard decision 0024 exists for: refuse an edit that would break a
    # PUBLISHED version, and say which. A draft is not counted — its author is
    # usually the person editing here, and a guard people learn to force is
    # worse than no guard.
    broken = params_svc.breaking(db, ps.id, new_values)
    if broken and not body.force:
        raise HTTPException(409, {
            "error": "this change would break a published version: " + "; ".join(broken),
            "breaking": broken,
        })
    rev = params_svc.record_revision(
        db, ps, old, new_values, acting_name(body.updated_by),
        note=(body.note + (" [forced]" if broken and body.force else "")).strip(),
    )
    ps.values_enc = crypto.encrypt_token(json.dumps(new_values))
    ps.updated_by = acting_name(body.updated_by)
    ps.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, "flasher.param_set_write", "param_set", ps.id,
          {"revision_no": rev.revision_no, "added": rev.keys_added,
           "removed": rev.keys_removed, "changed": rev.changed,
           "forced": bool(broken and body.force)})
    return {"id": ps.id, "revision_no": rev.revision_no}


class ParamRevertIn(BaseModel):
    revision_no: int
    updated_by: str = ""
    note: str = ""
    force: bool = False


@router.post("/param-sets/{param_set_id}/revert")
def revert_param_set(param_set_id: int, body: ParamRevertIn, db: Session = Depends(get_db)):
    """Put the values back to what a revision left, as a NEW revision.

    History is append-only and a revert does not remove any of it (user
    decision 2026-09-17): reverting r5 to r2 writes r6 holding r2's values, so
    the record still says that r3 to r5 happened and that somebody undid them.
    The breaking guard applies exactly as it does to a normal save — an old
    revision can be missing a key a version published since then needs.
    """
    ps = db.get(M.ParamSet, param_set_id)
    if ps is None:
        raise HTTPException(404, "no such param set")
    rev = (
        db.query(M.ParamSetRevision)
        .filter(M.ParamSetRevision.param_set_id == param_set_id,
                M.ParamSetRevision.revision_no == body.revision_no)
        .one_or_none()
    )
    if rev is None:
        raise HTTPException(404, f"this set has no revision {body.revision_no}")
    if not rev.values_enc:
        raise HTTPException(409, {
            "error": f"revision {body.revision_no} was recorded before the values were kept, "
                     "so there is nothing to restore. Its key list is still in the history.",
        })
    values = params_svc.revision_values(db, rev.id)
    broken = params_svc.breaking(db, ps.id, values)
    if broken and not body.force:
        raise HTTPException(409, {
            "error": "this change would break a published version: " + "; ".join(broken),
            "breaking": broken,
        })
    old: dict = {}
    if ps.values_enc:
        try:
            old = json.loads(crypto.decrypt_token(ps.values_enc))
        except Exception:  # noqa: BLE001
            old = {}
    note = body.note.strip() or f"reverted to r{rev.revision_no}"
    new_rev = params_svc.record_revision(
        db, ps, old, values, acting_name(body.updated_by),
        note=note + (" [forced]" if broken and body.force else ""),
    )
    ps.values_enc = crypto.encrypt_token(json.dumps(values))
    ps.updated_by = acting_name(body.updated_by)
    ps.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, "flasher.param_set_revert", "param_set", ps.id,
          {"to_revision": rev.revision_no, "new_revision": new_rev.revision_no,
           "forced": bool(broken and body.force)})
    return {"id": ps.id, "revision_no": new_rev.revision_no,
            "reverted_to": rev.revision_no}


@router.get("/param-sets/{param_set_id}/revisions")
def param_set_revisions(param_set_id: int, db: Session = Depends(get_db)):
    """What changed, when and by whom — never the value a secret used to hold."""
    ps = db.get(M.ParamSet, param_set_id)
    if ps is None:
        raise HTTPException(404, "no such param set")
    rows = (
        db.query(M.ParamSetRevision)
        .filter(M.ParamSetRevision.param_set_id == param_set_id)
        .order_by(M.ParamSetRevision.revision_no.desc())
        .all()
    )
    return [{"id": r.id, "revision_no": r.revision_no,
             "keys_added": r.keys_added or [], "keys_removed": r.keys_removed or [],
             "changed": r.changed or [], "values_public": r.values_public or {},
             # Whether this revision can be reverted TO. False for one recorded
             # before the values were kept — the page says so rather than
             # offering a button that restores an empty set.
             "restorable": bool(r.values_enc),
             "note": r.note, "updated_by": r.updated_by,
             "created_at": _iso(r.created_at)}
            for r in rows]


@router.get("/param-sets/{param_set_id}/values")
def param_set_values(param_set_id: int, db: Session = Depends(get_db)):
    """Decrypted values — detail view only, fetched explicitly for editing."""
    ps = db.get(M.ParamSet, param_set_id)
    if ps is None:
        raise HTTPException(404, "no such param set")
    values = json.loads(crypto.decrypt_token(ps.values_enc)) if ps.values_enc else {}
    return {"id": ps.id, "name": ps.name, "values": values}


@router.delete("/param-sets/{param_set_id}")
def delete_param_set(param_set_id: int, db: Session = Depends(get_db)):
    ps = db.get(M.ParamSet, param_set_id)
    if ps is None:
        raise HTTPException(404, "no such param set")
    # `param_set_id` used to be a soft pointer, so this left every version
    # pointing at a dead id and the failure surfaced as "no parameter defines
    # {MqttHost}" with a device already in the socket (decision 0024).
    users = (
        db.query(M.DeploymentVersion)
        .filter(M.DeploymentVersion.param_set_id == param_set_id).all()
    )
    if users:
        named = ", ".join(
            f"{db.get(M.Deployment, v.deployment_id).name} v{v.version_no}"
            for v in sorted(users, key=lambda v: (v.deployment_id, v.version_no))[:6]
        )
        more = f" and {len(users) - 6} more" if len(users) > 6 else ""
        raise HTTPException(409, {
            "error": f"{len(users)} deployment version(s) use this parameter set: "
                     f"{named}{more}. Point them at another set first.",
            "versions": [v.id for v in users],
        })
    db.query(M.ParamSetRevision).filter(
        M.ParamSetRevision.param_set_id == param_set_id
    ).delete()
    db.delete(ps)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------- meta

@router.get("/meta")
def flasher_meta():
    return {"ops": STEP_OPS, "transport_profiles": TRANSPORT_PROFILES,
            # The full table, not just the names: the bench needs the baud and
            # the reset style, and it must not keep its own copy of them.
            "transports": transports.PROFILES,
            "flash_bauds": list(transports.FLASH_BAUDS),
            # What a marking template says where the serial goes, when a step
            # does not name its own. The BENCH used to hold this list.
            "mark_placeholders": list(engine_mod.DEFAULT_MARK_PLACEHOLDERS),
            # The bounds `_identity_value` enforces. The bench checks them too,
            # so a bad capture is caught before a run is created — but it reads
            # them from here rather than keeping its own copy.
            "serial_len": {"min": SERIAL_MIN, "max": SERIAL_MAX},
            "firmware_kinds": FIRMWARE_KINDS, "chips": CHIPS,
            "default_offsets": DEFAULT_OFFSETS,
            # The check vocabulary, so a step can pick a name from a list and
            # the UI labels and orders without knowing any of it by heart.
            "checks": [{"name": n, "label": lbl, "category": cat, "position": pos}
                       for n, (lbl, cat, pos) in checks_svc.CATALOG.items()],
            "check_categories": checks_svc.CATEGORY_ORDER}


# -------------------------------------------------------------------- devices

def _parse_iso(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def _run_summary_json(r: M.ProgrammingRun, db: Session) -> dict:
    prod = db.get(M.ProductionRun, r.production_run_id) if r.production_run_id else None
    # NULL for a bench action that runs no procedure - an erase; `db.get`
    # on a null key warns and will raise in a later SQLAlchemy.
    v = db.get(M.DeploymentVersion, r.deployment_version_id) if r.deployment_version_id else None
    dep = db.get(M.Deployment, v.deployment_id) if v else None
    return {
        "id": r.id, "status": r.status, "operator": r.operator, "station": r.station,
        "attempt_no": r.attempt_no, "error": r.error, "draft_run": r.draft_run,
        "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
        "duration_ms": r.duration_ms,
        "production_run": {"id": prod.id, "label": prod.label} if prod else None,
        "deployment": {
            "version_id": v.id, "name": dep.name if dep else "?",
            "deployment_id": v.deployment_id, "version_no": v.version_no,
            "status": v.status,
        } if v else None,
    }


# Columns the device list may be sorted by. An allow-list, not a getattr:
# `sort` comes from a query string and must never be able to name an arbitrary
# column.
_DEVICE_SORTS = {
    # Project and batch sort by NAME through the outer joins `list_devices`
    # adds; `runs` by a correlated count. All three were unsortable until
    # 2026-09-07 because they lived on other tables.
    "project": M.Project.name,
    "batch": M.ProductionRun.label,
    "state": M.DeviceUnit.state,
    "runs": (select(func.count(M.ProgrammingRun.id))
             .where(M.ProgrammingRun.device_unit_id == M.DeviceUnit.id)
             .correlate(M.DeviceUnit).scalar_subquery()),
    "last_seen": M.DeviceUnit.last_seen,
    "first_seen": M.DeviceUnit.first_seen,
    "mac": M.DeviceUnit.mac,
    "serial": M.DeviceUnit.serial,
    "chip": M.DeviceUnit.chip,
    "tasmota_id": M.DeviceUnit.tasmota_id,
    "imei": M.DeviceUnit.imei,
    "iccid": M.DeviceUnit.iccid,
    "last_status": M.DeviceUnit.last_status,
}

# Per-column substring filters. The list is server-PAGED, so the table's filter
# row has to reach the server or it would search one page and then report "no
# rows match" about 5400 devices it never loaded. Same allow-list reasoning as
# the sort map: a column name arrives in a query string.
_DEVICE_FILTERS = {
    "runs": cast(_DEVICE_SORTS["runs"], String),
    "project": M.Project.name,
    "batch": M.ProductionRun.label,
    "state": M.DeviceUnit.state,
    "serial": M.DeviceUnit.serial,
    "mac": M.DeviceUnit.mac,
    "tasmota_id": M.DeviceUnit.tasmota_id,
    "chip": M.DeviceUnit.chip,
    "imei": M.DeviceUnit.imei,
    "iccid": M.DeviceUnit.iccid,
    "last_status": M.DeviceUnit.last_status,
}


@router.get("/devices")
def list_devices(
    project_id: int | None = None,
    production_run_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort: str = "last_seen",
    dir: str = "desc",
    f: list[str] = Query([]),
    db: Session = Depends(get_db),
):
    """One PAGE of devices, newest-seen first by default.

    This is the one list in the platform that pages in SQL rather than being
    rendered progressively in the browser: 5502 rows serialise to 1.98 MB and
    took 2.5 s on production (measured 2026-08-24), and no amount of clever
    rendering makes two megabytes arrive faster. Filtering and sorting are
    therefore SERVER-side here — a client that only holds one page cannot
    honestly filter the rest.
    """
    # Outer joins so project and batch can be sorted and filtered by name.
    # The batch is the device's own `production_run_id` (decision 0003), which
    # is what the orders side links; the latest programming run's batch is
    # only a fallback for devices no batch has claimed.
    query = (db.query(M.DeviceUnit)
             .outerjoin(M.Project, M.Project.id == M.DeviceUnit.project_id)
             .outerjoin(M.ProductionRun, M.ProductionRun.id == M.DeviceUnit.production_run_id))
    if project_id:
        query = query.filter(M.DeviceUnit.project_id == project_id)
    if status:
        query = query.filter(M.DeviceUnit.last_status == status)
    if production_run_id:
        # The device's own column, matching the comment above and the orders
        # side. Going through `ProgrammingRun.production_run_id` asked the
        # bench's copy of the choice instead of the corrected one.
        query = query.filter(M.DeviceUnit.production_run_id == production_run_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            M.DeviceUnit.mac.ilike(like)
            | M.DeviceUnit.serial.ilike(like)
            | M.DeviceUnit.tasmota_id.ilike(like)
            | M.DeviceUnit.imei.ilike(like)
            | M.DeviceUnit.iccid.ilike(like)
        )
    # `f` carries repeated `column:text` pairs — one per filled filter box.
    for pair in f:
        name, _, text = pair.partition(":")
        column = _DEVICE_FILTERS.get(name)
        if column is not None and text.strip():
            query = query.filter(column.ilike(f"%{text.strip()}%"))

    col = _DEVICE_SORTS.get(sort, M.DeviceUnit.last_seen)
    # NULLS LAST in both directions: a device that was never seen is the least
    # informative row on the page and must never head it.
    order = col.desc().nullslast() if dir == "desc" else col.asc().nullslast()
    total = query.order_by(None).count()
    devices = query.order_by(order, M.DeviceUnit.id.desc()).offset(offset).limit(limit).all()
    ids = [d.id for d in devices]
    latest: dict[int, M.ProgrammingRun] = {}
    counts: dict[int, int] = {}
    if ids:
        for r in (
            db.query(M.ProgrammingRun)
            .filter(M.ProgrammingRun.device_unit_id.in_(ids))
            .order_by(M.ProgrammingRun.started_at.desc())
        ):
            counts[r.device_unit_id] = counts.get(r.device_unit_id, 0) + 1
            latest.setdefault(r.device_unit_id, r)
    projects = {p.id: p.name for p in db.query(M.Project)}
    # One query for the batches this page references — `db.get` per device is
    # only free while the identity map still holds the object, and it holds
    # weak references.
    run_ids = {r.production_run_id for r in latest.values() if r.production_run_id}
    run_ids |= {d.production_run_id for d in devices if d.production_run_id}
    prod_runs = {r.id: r for r in db.query(M.ProductionRun)
                 .filter(M.ProductionRun.id.in_(run_ids))} if run_ids else {}
    tally = checks_svc.counts_for_devices(db, ids)
    out = []
    for d in devices:
        last = latest.get(d.id)
        prod = prod_runs.get(d.production_run_id) if d.production_run_id else None
        if prod is None and last is not None and last.production_run_id:
            prod = prod_runs.get(last.production_run_id)
        # NOT `counts` — that name holds the run count per device.
        checked = tally.get(d.id, {})
        out.append({
            "checks": {"pass": checked.get("pass", 0), "fail": checked.get("fail", 0),
                       "unknown": checked.get("unknown", 0)},
            "id": d.id, "mac": d.mac or "", "serial": d.serial, "chip": d.chip,
            "tasmota_id": d.tasmota_id, "imei": d.imei, "iccid": d.iccid,
            "imsi": d.imsi, "modem_model": d.modem_model,
            "project": {"id": d.project_id, "name": projects.get(d.project_id, "?")},
            "batch": {"id": prod.id, "label": prod.label} if prod else None,
            "state": d.state, "condition": d.condition or "ok",
            "last_status": d.last_status, "runs": counts.get(d.id, 0),
            "first_seen": _iso(d.first_seen), "last_seen": _iso(d.last_seen),
            "notes": d.notes,
        })
    return {"items": out, "total": total, "offset": offset, "limit": limit,
            "has_more": offset + len(out) < total}


# THE identity rows of a device, label included, in display order. The page
# renders what this returns and knows none of these names: a field that exists
# on the model has to be able to appear here without a frontend change.
#
# MAC and serial are on every unit and are always drawn. Each of the others is
# drawn when the device carries it, when a procedure of its project CAPTURES it
# (`capture` keys, the same names `engine.IDENTITY_VARS` writes to the device
# row), or when a sibling device in the project carries it. A Dongle_V2 has no
# modem, so it printed five empty modem rows on 4400 devices (user report
# 2026-09-16); the sibling rule is what keeps imported history readable once
# the procedure that produced it is gone.
_IDENTITY_ALWAYS = (("mac", "MAC"), ("serial", "Serial"))
_IDENTITY_OPTIONAL = (
    # column, label, the capture variable that fills it (None = never captured)
    ("chip", "Chip", None),
    ("tasmota_id", "Tasmota name", "topic"),
    ("imei", "IMEI", "imei"),
    ("iccid", "ICCID (SIM)", "iccid"),
    ("imsi", "IMSI", "imsi"),
    ("modem_model", "Modem", "modem_model"),
    ("modem_fw", "Modem firmware", "modem_fw"),
)


def _identity_rows(db: Session, dev: M.DeviceUnit) -> list[dict]:
    keys = [c for c, _, _ in _IDENTITY_OPTIONAL]
    show = {c for c in keys if (getattr(dev, c, "") or "").strip()}

    captured: set[str] = set()
    for (steps,) in db.execute(text("""
        SELECT v.steps FROM deployment_versions v
        JOIN deployments d ON d.id = v.deployment_id
        WHERE d.project_id = :p AND v.steps IS NOT NULL
    """), {"p": dev.project_id}):
        for step in steps or []:
            if isinstance(step, dict):
                captured.update((step.get("capture") or {}).keys())
    show |= {c for c, _, var in _IDENTITY_OPTIONAL if var and var in captured}

    rest = [c for c in keys if c not in show]
    if rest:
        sql = ", ".join(f"bool_or(coalesce({c}, '') <> '') AS {c}" for c in rest)
        row = db.execute(text(f"SELECT {sql} FROM device_units WHERE project_id = :p"),
                         {"p": dev.project_id}).mappings().one()
        show |= {c for c in rest if row[c]}

    rows = [{"key": c, "label": label, "value": getattr(dev, c, "") or ""}
            for c, label in _IDENTITY_ALWAYS]
    rows += [{"key": c, "label": label, "value": getattr(dev, c, "") or ""}
             for c, label, _ in _IDENTITY_OPTIONAL if c in show]
    return rows


def _presence_json(db: Session, dev: M.DeviceUnit) -> dict | None:
    """The broker's view of one device, or None if it was never heard.

    Matched by `device_unit_id` first and by topic second: a presence row
    discovered before the device was imported may not be linked yet, and the
    device page is exactly where somebody notices.
    """
    row = db.scalar(
        select(M.DevicePresence).where(M.DevicePresence.device_unit_id == dev.id)
    )
    if row is None and dev.tasmota_id:
        row = db.scalar(
            select(M.DevicePresence).where(M.DevicePresence.topic == dev.tasmota_id)
        )
    if row is None:
        return None
    return {
        "topic": row.topic,
        "online": row.online,
        "lwt": row.lwt,
        "last_seen_at": _iso(row.last_seen_at),
        "last_online_at": _iso(row.last_online_at),
        "last_offline_at": _iso(row.last_offline_at),
        "first_seen_at": _iso(row.first_seen_at),
        "temperature_c": row.temperature_c,
        "temperature_at": _iso(row.temperature_at),
        "wifi_ping_ms": row.wifi_ping_ms,
        "inverter": row.inverter,
        "inverter_sn": row.inverter_sn,
        "dongle_version": row.dongle_version,
        "persist": row.persist,
        "persist_at": _iso(row.persist_at),
        "updated_at": _iso(row.updated_at),
        # The MAC the topic encodes, when it encodes one. Shown so a mismatch
        # against the programmed MAC is visible rather than silent.
        "mac_from_topic": mqtt_monitor.mac_from_topic(row.topic),
        # The device's OWN answer, when anything has ever asked it.
        "reported_mac": row.reported_mac,
        "reported_mac_field": row.reported_mac_field,
        "reported_mac_at": _iso(row.reported_mac_at),
    }


@router.get("/devices/{device_id}")
def device_detail(device_id: int, reveal: bool = False, db: Session = Depends(get_db)):
    d = db.get(M.DeviceUnit, device_id)
    if d is None:
        raise HTTPException(404, "no such device")
    project = db.get(M.Project, d.project_id)
    # WHAT IS ON THE DEVICE NOW — the values the LAST run to configure it
    # wrote, not every value it ever carried. The full history made a 4-key
    # device print twelve rows of the same three keys, which reads like twelve
    # settings (user decision 2026-09-16). Every earlier value is still in
    # `device_config_values` and still reachable through its own run.
    # `set_at` is tz-aware; a NULL one sorts first rather than crashing the mix.
    _epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    newest_cfg = max(d.configs, key=lambda c: (c.set_at or _epoch, c.id), default=None)
    cfg_rows = ([c for c in d.configs if c.set_by_run_id == newest_cfg.set_by_run_id]
                if newest_cfg is not None else [])
    configs = [
        {
            "key": c.key,
            "value": (c.value if (reveal or not c.is_secret) else "•••"),
            "is_secret": c.is_secret, "current": c.current,
            "set_by_run_id": c.set_by_run_id, "set_at": _iso(c.set_at),
        }
        for c in sorted(cfg_rows, key=lambda c: c.key)
    ]
    newest = checks_svc.newest_run(db, d.id)
    verdict = checks_svc.verdict(db, d.id)
    return {
        "id": d.id, "mac": d.mac or "", "serial": d.serial, "chip": d.chip,
        "tasmota_id": d.tasmota_id, "imei": d.imei, "iccid": d.iccid, "imsi": d.imsi,
        "modem_model": d.modem_model, "modem_fw": d.modem_fw,
        "project": {"id": d.project_id, "name": project.name if project else "?"},
        "first_seen": _iso(d.first_seen), "last_seen": _iso(d.last_seen),
        "last_status": d.last_status, "condition": d.condition or "ok", "notes": d.notes,
        "configs": configs,
        # The identity rows to draw, label and value — see _identity_rows.
        "identity": _identity_rows(db, d),
        # Which run wrote them, and how many earlier values are not shown.
        "config_run_id": newest_cfg.set_by_run_id if newest_cfg is not None else None,
        "config_superseded": len(d.configs) - len(cfg_rows),
        # What this device is PROVEN to do: the newest run that MEASURED
        # something, so a green cell can never outlive the attempt that
        # replaced it, and a marking job never blanks the grid.
        "checks": checks_svc.for_device(db, d.id),
        "checks_run": ({"id": newest["id"], "status": newest["status"],
                        "act": checks_svc._act(newest),
                        "attempt_no": newest["attempt_no"],
                        "started_at": _iso(newest["started_at"])} if newest is not None else None),
        # Is it programmed — config, then an active test, then no erase since.
        "verdict": verdict,
        # What the BROKER says, which is a different axis from what the bench
        # proved: `checks` is history that cannot change, `presence` is now.
        # None when the monitor has never heard this topic.
        "presence": _presence_json(db, d),
        "runs": [_run_summary_json(r, db) for r in d.runs],
    }


class DevicePatch(BaseModel):
    notes: str


@router.patch("/devices/{device_id}")
def patch_device(device_id: int, body: DevicePatch, db: Session = Depends(get_db)):
    d = db.get(M.DeviceUnit, device_id)
    if d is None:
        raise HTTPException(404, "no such device")
    d.notes = body.notes
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------- programming runs

class RunCreate(BaseModel):
    """A run either belongs to a batch or is a bench trial (batch omitted).

    Version resolution, in order: an explicit `deployment_version_id`, else the
    batch's pinned version, else the batch's channel. A DRAFT version is
    allowed only for a bench trial and is recorded as such.

    There is NO `operator` field: who ran it is the signed-in account
    (`actor_of`), never a value the caller chooses. The bench used to ask for a
    name in a text box, which meant the record was as good as whatever somebody
    typed, and usually empty (user decision 2026-09-16).
    """
    production_run_id: int | None = None
    deployment_version_id: int | None = None
    station: str = ""
    override_reason: str = ""


@router.post("/runs")
def create_run(body: RunCreate, request: Request, db: Session = Depends(get_db)):
    prod = None
    if body.production_run_id:
        prod = db.get(M.ProductionRun, body.production_run_id)
        if prod is None:
            raise HTTPException(404, "no such production run")

    assigned = prod.deployment_version_id if prod else None
    if assigned is None and prod is not None and prod.deployment_channel:
        # Follow the batch's channel: resolve it now and record what it gave.
        ch = (
            db.query(M.DeploymentChannel)
            .join(M.Deployment, M.Deployment.id == M.DeploymentChannel.deployment_id)
            .filter(M.Deployment.project_id == prod.project_id,
                    M.DeploymentChannel.name == prod.deployment_channel)
            .one_or_none()
        )
        assigned = ch.deployment_version_id if ch else None
    version_id = body.deployment_version_id or assigned
    if not version_id:
        raise HTTPException(
            409, "no deployment version: the batch pins none and follows no channel, "
                 "and the request named none")
    v = db.get(M.DeploymentVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such deployment version")
    dep = db.get(M.Deployment, v.deployment_id)
    if prod is not None and dep.project_id != prod.project_id:
        raise HTTPException(409, "that deployment belongs to a different project than the batch")
    if v.status == "rejected":
        raise HTTPException(409, "that version was rejected")
    draft_run = v.status == "draft"
    if draft_run and prod is not None:
        raise HTTPException(
            409, f"version {dep.name} v{v.version_no} is a draft — publish it, or run it as a "
                 "bench trial (no batch) to try it out")
    # Drafts are validated too. They used to be exempt, and a draft is exactly
    # where an unresolved {placeholder} does the most damage: `subst` leaves the
    # literal text, `set_and_check` compares what it sent against what it read
    # back — both "{MqttHost}" — and the step PASSES. The device ships pointed
    # at a broker called {MqttHost} and the run says so too (decision 0024).
    # A draft's errors are reported as a draft's, not as "no longer validates".
    result = validate.check(db, v)
    if not result["ok"]:
        raise HTTPException(409, (
            "this draft does not validate yet: " if draft_run
            else "this version no longer validates: ") + " | ".join(result["errors"]))
    override = bool(assigned and version_id != assigned)
    if override and not body.override_reason.strip():
        raise HTTPException(409, "programming with a non-assigned version needs an override_reason")
    # Pin the RULE alongside the firmware: does a unit made by this run have to
    # pass a test? The batch answers; a bench trial takes the project's current
    # default (its active test deployment). Copied once, read forever — a
    # later change of mind cannot re-judge what this run produced.
    if prod is not None:
        test_required = bool(prod.requires_test)
    else:
        test_required = bool(db.query(M.Deployment).filter(
            M.Deployment.project_id == dep.project_id,
            M.Deployment.kind == "test", M.Deployment.active).first())
    run = M.ProgrammingRun(
        production_run_id=prod.id if prod else None, deployment_version_id=v.id,
        firmware_fingerprint=v.firmware_fingerprint,
        files_fingerprint=bundle.version_files_fingerprint(v),
        draft_run=draft_run, test_required=test_required,
        release_override_reason=body.override_reason.strip() if override else "",
        operator=actor_of(request), station=body.station, status="running",
    )
    db.add(run)
    db.commit()
    if override:
        audit(db, "flasher.run_override", "programming_run", run.id,
              details=f"batch {prod.id if prod else '-'} assigned version {assigned}, "
                      f"ran {version_id}: {body.override_reason}", actor=actor_of(request))
    return {"run_id": run.id, "deployment_version_id": v.id, "draft_run": draft_run}


class BenchRunIn(BaseModel):
    """A bench action that ran no procedure: an erase, or a mark typed by hand."""
    action: str = "erase"
    project_id: int
    mac: str = ""
    chip: str = ""
    status: str = "pass"          # pass | fail
    error: str = ""
    station: str = ""
    started_at: str = ""
    log: list[dict] = []          # [{"dir": "app", "text": "..."}]
    results: dict = {}            # what the action produced, e.g. {"marked": "..."}


@router.post("/bench-runs")
def create_bench_run(body: BenchRunIn, request: Request, db: Session = Depends(get_db)):
    """Record an erase or a manual mark in the SAME history as the programming runs.

    An erase was deliberately left unrecorded — it is a workshop action, and a
    row per erase would bury the production runs beside it. What changed the
    answer is that an erase IDENTIFIES the device: once the MAC is known, the
    attempt and its log are exactly what tells you a unit is giving trouble,
    and a failure that leaves no trace is the one you rediscover on the next
    batch (user decision 2026-09-16). An erase that never reached a MAC still
    records nothing: there is no device to attach it to — and a mark typed by
    hand is recorded on the same terms, because what the operator typed IS the
    unit's identity, which is what makes it a device event and not a note.
    """
    mac = body.mac.strip().lower()
    if not mac:
        raise HTTPException(400, "a bench run needs the MAC it read")
    dev = db.query(M.DeviceUnit).filter(M.DeviceUnit.mac == mac).one_or_none()
    if dev is None:
        dev = M.DeviceUnit(
            project_id=body.project_id, mac=mac, chip=body.chip,
            serial=mac.replace(":", "").upper(),
        )
        db.add(dev)
        db.flush()
    else:
        dev.chip = body.chip or dev.chip
        dev.last_seen = utcnow()
    run = M.ProgrammingRun(
        device_unit_id=dev.id, deployment_version_id=None, action=body.action,
        status=body.status, error=body.error[:2000], operator=actor_of(request),
        station=body.station, mac_read=mac, chip_read=body.chip,
        started_at=_parse_iso(body.started_at) or utcnow(), finished_at=utcnow(),
        results=body.results or None,
    )
    run.attempt_no = (
        db.query(M.ProgrammingRun).filter(M.ProgrammingRun.device_unit_id == dev.id).count() + 1
    )
    db.add(run)
    db.flush()
    if body.log:
        db.bulk_insert_mappings(M.ProgrammingLog, [
            {"run_id": run.id, "seq": i + 1, "ts": utcnow(), "device_ts": "",
             "dir": str(row.get("dir", "app"))[:10], "text": str(row.get("text", ""))[:4000]}
            for i, row in enumerate(body.log)
        ])
    # This is the newest thing that happened to this unit.
    dev.last_status = body.status
    dev.last_seen = utcnow()
    db.commit()
    return {"run_id": run.id, "device_unit_id": dev.id}


@router.post("/runs/{run_id}/mark-aborted")
def mark_aborted(run_id: int, db: Session = Depends(get_db)):
    """For a zombie row whose bench died without closing the socket."""
    r = db.get(M.ProgrammingRun, run_id)
    if r is None:
        raise HTTPException(404, "no such run")
    if r.status != "running":
        raise HTTPException(409, f"run is {r.status}")
    r.status = "aborted"
    r.error = "marked aborted manually"
    db.commit()
    return {"ok": True}


@router.post("/checks/recompute")
def recompute_checks(project_id: int | None = None, run_id: int | None = None,
                     db: Session = Depends(get_db)):
    """Rebuild the derived checks from the runs' own steps and results.

    Checks are a cached opinion about stored evidence, so improving an extractor
    has to be able to upgrade all history — that is this endpoint. It is safe to
    run at any time: each run's rows are deleted and rebuilt.
    """
    query = db.query(M.ProgrammingRun).filter(M.ProgrammingRun.status != "running")
    if run_id:
        query = query.filter(M.ProgrammingRun.id == run_id)
    if project_id:
        version_ids = [
            v.id for v in db.query(M.DeploymentVersion)
            .join(M.Deployment, M.Deployment.id == M.DeploymentVersion.deployment_id)
            .filter(M.Deployment.project_id == project_id)
        ]
        query = query.filter(M.ProgrammingRun.deployment_version_id.in_(version_ids or [-1]))
    # Ids first, then chunks: committing while a server-side cursor is open
    # invalidates the cursor.
    ids = [r.id for r in query.with_entities(M.ProgrammingRun.id).order_by(M.ProgrammingRun.id)]
    written = 0
    for start in range(0, len(ids), 200):
        for run_id_ in ids[start:start + 200]:
            run = db.get(M.ProgrammingRun, run_id_)
            written += len(checks_svc.recompute(db, run))
        db.commit()
    return {"runs": len(ids), "checks": written}


@router.get("/runs/{run_id}")
def run_detail(run_id: int, db: Session = Depends(get_db)):
    r = db.get(M.ProgrammingRun, run_id)
    if r is None:
        raise HTTPException(404, "no such run")
    device = db.get(M.DeviceUnit, r.device_unit_id) if r.device_unit_id else None
    return {
        **_run_summary_json(r, db),
        "device": {
            "id": device.id, "mac": device.mac or "", "serial": device.serial,
            "tasmota_id": device.tasmota_id,
        } if device else None,
        "mac_read": r.mac_read, "chip_read": r.chip_read,
        "firmware_fingerprint": r.firmware_fingerprint,
        "files_fingerprint": r.files_fingerprint,
        "release_override_reason": r.release_override_reason,
        "results": r.results, "params_snapshot": r.params_snapshot,
        "client_info": r.client_info,
        "checks": checks_svc.for_run(db, r.id),
        "steps": [
            {
                "idx": s.idx, "op": s.op, "label": s.label, "status": s.status,
                "started_at": _iso(s.started_at), "duration_ms": s.duration_ms,
                "error": s.error, "response": s.response, "check": s.check_name,
            }
            for s in r.steps
        ],
    }


@router.get("/runs/{run_id}/logs")
def run_logs(run_id: int, after: int = 0, limit: int = 2000,
             dir: str | None = None, db: Session = Depends(get_db)):
    query = (
        db.query(M.ProgrammingLog)
        .filter(M.ProgrammingLog.run_id == run_id, M.ProgrammingLog.seq > after)
    )
    if dir:
        query = query.filter(M.ProgrammingLog.dir == dir)
    rows = query.order_by(M.ProgrammingLog.seq).limit(min(limit, 5000)).all()
    return [
        {"seq": row.seq, "ts": _iso(row.ts), "device_ts": row.device_ts,
         "dir": row.dir, "text": row.text}
        for row in rows
    ]


@router.get("/production-runs/{production_run_id}/programming")
def batch_programming(production_run_id: int, db: Session = Depends(get_db)):
    """Coverage: the batch's planned serial list vs what was really programmed."""
    prod = db.get(M.ProductionRun, production_run_id)
    if prod is None:
        raise HTTPException(404, "no such production run")
    # A batch's attempts are the attempts on ITS DEVICES — `DeviceUnit`
    # carries the corrected batch ([0029](../../../docs/decisions/0029-the-batch-on-a-produced-event-is-correctable.md)),
    # a programming run carries a copy that `rebatch_devices` keeps in step but
    # that is NULL on every retro import. The run's own column is still read,
    # for the attempts that never reached a device and so have no other batch.
    runs = (
        db.query(M.ProgrammingRun)
        .outerjoin(M.DeviceUnit, M.DeviceUnit.id == M.ProgrammingRun.device_unit_id)
        .filter((M.DeviceUnit.production_run_id == production_run_id)
                | ((M.ProgrammingRun.device_unit_id.is_(None))
                   & (M.ProgrammingRun.production_run_id == production_run_id)))
        .order_by(M.ProgrammingRun.started_at.desc())
        .all()
    )
    norm = lambda s: s.replace(":", "").replace("-", "").upper()  # noqa: E731
    # The planned serial list, where a batch has one. Most do not — a batch's
    # real device list is `DeviceUnit.production_run_id`, and `missing` is only
    # meaningful against a list somebody typed in advance.
    planned = {norm(d.serial): d.serial for d in prod.devices}
    device_ids = {r.device_unit_id for r in runs if r.device_unit_id}
    devices = {
        d.id: d for d in db.query(M.DeviceUnit).filter(M.DeviceUnit.id.in_(device_ids or [-1]))
    }
    programmed_ok: set[str] = set()
    seen: set[str] = set()
    for r in runs:
        dev = devices.get(r.device_unit_id) if r.device_unit_id else None
        if dev is None or not dev.serial:
            continue
        serial = norm(dev.serial)
        seen.add(serial)
        if r.status == "pass":
            programmed_ok.add(serial)
    # `extra` and `missing` compare against the planned list and mean nothing
    # without one — a batch with no typed list would otherwise report every
    # device it really built as "extra".
    return {
        "planned": len(planned),
        "programmed_ok": len(programmed_ok & set(planned)) if planned else len(programmed_ok),
        "failed_only": sorted(seen - programmed_ok),
        "extra": sorted(programmed_ok - set(planned)) if planned else [],
        "missing": sorted(set(planned) - programmed_ok) if planned else [],
        "unidentified_attempts": sum(1 for r in runs if not r.device_unit_id),
        "runs": [_run_summary_json(r, db) for r in runs[:200]],
        "assigned_deployment_version_id": prod.deployment_version_id,
        "deployment_channel": prod.deployment_channel,
    }


class BatchDeploymentIn(BaseModel):
    """Pin a version outright, or follow a channel by name (mutually exclusive
    in practice: an explicit pin wins at run creation)."""
    deployment_version_id: int | None = None
    deployment_channel: str = ""


@router.put("/production-runs/{production_run_id}/deployment")
def assign_batch_deployment(production_run_id: int, body: BatchDeploymentIn,
                            db: Session = Depends(get_db)):
    prod = db.get(M.ProductionRun, production_run_id)
    if prod is None:
        raise HTTPException(404, "no such production run")
    if body.deployment_version_id is not None:
        v = db.get(M.DeploymentVersion, body.deployment_version_id)
        if v is None:
            raise HTTPException(404, "no such deployment version")
        dep = db.get(M.Deployment, v.deployment_id)
        if dep.project_id != prod.project_id:
            raise HTTPException(409, "that deployment belongs to a different project")
        if v.status != "published":
            raise HTTPException(409, f"version is {v.status} — a batch runs published versions only")
    prod.deployment_version_id = body.deployment_version_id
    prod.deployment_channel = body.deployment_channel.strip()
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------- mosquitto export

# USB serial bridges a bench opens. The profile grants ONLY these, so a device
# outside the list still costs the operator a pick — deliberately: this file is
# handed to people on machines nobody here administers, and "any serial port"
# is not a grant to hand out by download. Both entries are measured, not
# assumed: the CH340 from a V2 dongle on the bench (2026-09-16), the Espressif
# id from `USB_SERIAL_JTAG` in web/src/flasher/station.ts.
BENCH_USB_BRIDGES = [
    (0x1A86, 0x7523, 'CH340 "USB2.0-Serial" — Dongle V2 bridge'),
    (0x303A, 0x1001, "Espressif built-in USB-Serial/JTAG — V3"),
]


def _mobileconfig(origins: list[str]) -> str:
    """A macOS configuration profile granting these ORIGINS what a page cannot ask for.

    Why this file has to exist: a CH340 reports no USB serial number, so Chrome
    has no stable identifier to persist and discards the port permission when
    the device is unplugged. The operator is then back at the picker for every
    unit. No page can ask for this — serial permission is device-scoped by
    design, unlike camera or microphone — so the only grant that survives a
    replug comes from browser policy.

    The origins are baked in and EXACT: `localhost` and `127.0.0.1` are
    different origins, and so is a different port. The caller passes the origin
    the bench is really open at, which is why this is generated per request
    rather than shipped as a static file.
    """
    devices = "".join(
        f"""
              <!-- {note} -->
              <dict>
                <key>vendor_id</key><integer>{vid}</integer>
                <key>product_id</key><integer>{pid}</integer>
              </dict>"""
        for vid, pid, note in BENCH_USB_BRIDGES
    )
    urls = "".join(f"\n            <string>{o}</string>" for o in origins)
    # Stable identifier: installing a second time REPLACES the first profile
    # rather than stacking another copy.
    ident = "cc.disfunction.bench.serial"  # kept: renaming it stacks a second profile
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>PayloadType</key><string>Configuration</string>
  <key>PayloadVersion</key><integer>1</integer>
  <key>PayloadIdentifier</key><string>{ident}</string>
  <key>PayloadUUID</key><string>{uuid.uuid5(uuid.NAMESPACE_URL, ident + "|" + "|".join(origins))}</string>
  <key>PayloadDisplayName</key><string>7Sigma bench — serial ports and the marking agent</string>
  <key>PayloadDescription</key><string>Two grants the bench cannot ask for itself. Serial: the USB bridge reports no serial number, so Chrome forgets the port on every replug. Loopback: the marking bench reaches LightBurn through an agent on this machine, which Chrome blocks unless the site is allowed.</string>
  <key>PayloadOrganization</key><string>7Sigma</string>
  <key>PayloadScope</key><string>System</string>
  <key>PayloadRemovalDisallowed</key><false/>
  <key>PayloadContent</key>
  <array>
    <dict>
      <key>PayloadType</key><string>com.google.Chrome</string>
      <key>PayloadVersion</key><integer>1</integer>
      <key>PayloadIdentifier</key><string>{ident}.chrome</string>
      <key>PayloadUUID</key><string>{uuid.uuid5(uuid.NAMESPACE_URL, ident + ".chrome|" + "|".join(origins))}</string>
      <key>PayloadDisplayName</key><string>Chrome — bench serial devices</string>
      <key>SerialAllowUsbDevicesForUrls</key>
      <array>
        <dict>
          <key>devices</key>
          <array>{devices}
          </array>
          <key>urls</key>
          <array>{urls}
          </array>
        </dict>
      </array>
      <!-- The marking bench reaches the laser through an agent on 127.0.0.1,
           which Chrome 141+ blocks under Local Network Access with
           ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS. Without this the operator
           is prompted; the loopback key is the narrow one, and it outranks the
           broader LocalNetworkAccessAllowedForUrls. -->
      <key>LoopbackNetworkAccessAllowedForUrls</key>
      <array>{urls}
      </array>
    </dict>
  </array>
</dict>
</plist>
"""


def _calling_origin(request: Request) -> str:
    """Which address the bench is really open at.

    From the BROWSER (`Origin`, else `Referer`), because only it knows; a
    profile or a launcher written for the wrong origin silently does nothing.
    `public_base_url` is the fallback for a non-browser caller.
    """
    raw = request.headers.get("origin") or request.headers.get("referer") or ""
    parts = urlsplit(raw)
    origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
    if not origin:
        fallback = urlsplit(settings.public_base_url)
        if fallback.scheme and fallback.netloc:
            origin = f"{fallback.scheme}://{fallback.netloc}"
    if not origin:
        raise HTTPException(400, "cannot tell which origin this bench is served from")
    return origin


AGENT_SRC = Path(__file__).resolve().parent.parent / "services" / "bench_agent"

_AGENT_README = """7Sigma agent
============

WHAT IT IS
    The part of the bench that cannot live in a browser. Today it drives the
    laser through LightBurn and reads the real serial port names; it will
    grow as the bench does.

TO START IT (macOS)
    Double-click "{app}". A small window opens. Leave it open while
    you mark; closing it stops the agent.

    THE FIRST TIME on macOS, the app is unsigned and downloaded, so double-
    clicking may say it cannot be opened. RIGHT-CLICK IT AND CHOOSE OPEN
    instead, once, and confirm. After that it opens normally.

    "Start in a terminal.command" is the same program without the window, for
    when you would rather watch the log.

WHAT IT SETS UP FOR YOU (no administrator rights needed)
    On first start it grants this bench two things a web page cannot ask for
    itself, and then says so:

      * the USB serial adapters, so you are not asked to pick a port for
        every device;
      * permission to reach this agent on 127.0.0.1.

    QUIT CHROME COMPLETELY AND REOPEN IT ONCE afterwards. Nothing else is
    changed, other benches already listed keep working, and "--no-browser-setup"
    turns it off.

IF IT WILL NOT START
    It needs Python 3, which macOS provides. If the machine has none, install
    it from python.org and double-click again. Nothing else is required: no
    pip, no virtualenv, no administrator rights.

IF THE BENCH SAYS "LIGHTBURN IS NOT ANSWERING"
    * Is LightBurn running, with no dialog waiting for a click?
    * Does its title bar say Pro? LightBurn Core cannot drive a galvo laser,
      and the way it fails is silence, not an error.

THIS AGENT HOLDS NO PASSWORD AND NO TOKEN.
    It listens on this machine only, and answers only the bench page it was
    downloaded from ({origin}).
"""

# The app bundle. A .app is a directory with a plist and an executable, so it
# can be built here with no tooling — and it opens a WINDOW rather than a
# terminal, which is what a bench wants.
_APP = "7Sigma Agent.app"

_APP_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>7Sigma Agent</string>
  <key>CFBundleDisplayName</key><string>7Sigma Agent</string>
  <key>CFBundleIdentifier</key><string>cc.disfunction.bench.agent</string>
  <key>CFBundleVersion</key><string>2</string>
  <key>CFBundleShortVersionString</key><string>2.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>run</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
"""

# Finding a Python that can DRAW. `command -v python3` often lands on Homebrew's,
# which ships without tkinter (measured 2026-09-16: "No module named '_tkinter'"),
# while macOS's own /usr/bin/python3 has it. So: prefer one that can import it,
# and fall back to any python3 at all — the agent then runs without a window
# rather than not at all.
_PICK_PY = """PY=""
for C in /usr/bin/python3 "$(command -v python3)" /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  [ -x "$C" ] || continue
  [ -z "$PY" ] && PY="$C"
  if "$C" -c 'import tkinter' >/dev/null 2>&1; then PY="$C"; break; fi
done
[ -n "$PY" ] || PY=/usr/bin/python3
"""

_APP_RUN = """#!/bin/sh
# The app's executable: find a Python that can draw, and hand it the agent.
HERE=$(dirname "$0")
{pick}
exec "$PY" "$HERE/../Resources/agent.py" --origin '{origin}' "$@"
"""

_AGENT_COMMAND = """#!/bin/sh
# The terminal way in, for a bench that would rather watch the log.
# The app beside this file is the same program with a window.
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || echo /usr/bin/python3)
echo "Starting the 7Sigma agent. Leave this window open."
exec "$PY" "{app}/Contents/Resources/agent.py" --terminal --origin '{origin}' "$@"
"""



@router.get("/agent.zip")
def bench_agent(request: Request):
    """The bench agent, as something an operator can download and open.

    A bare .py is not clickable and a bare .command loses its execute bit in
    transit, so this is a ZIP: the archive carries the mode, and expanding it
    leaves a launcher that runs on a double-click. The bench's own origin is
    baked into that launcher, so nobody types a flag.
    """
    origin = _calling_origin(request)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        def add(name: str, text: str, mode: int) -> None:
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = mode << 16
            zf.writestr(info, text)

        # ONE copy of the agent, inside the bundle; both launchers point at it.
        add(f"{_APP}/Contents/Resources/agent.py", (AGENT_SRC / "agent.py").read_text(), 0o644)
        # esptool + pyserial, pure Python, extracted by the agent on first run
        # (decision 0023). Stored, not deflated: it is already a zip.
        vendor = zipfile.ZipInfo(f"{_APP}/Contents/Resources/vendor.zip", (2026, 1, 1, 0, 0, 0))
        vendor.compress_type = zipfile.ZIP_STORED
        vendor.external_attr = 0o644 << 16
        zf.writestr(vendor, (AGENT_SRC / "vendor.zip").read_bytes())
        add(f"{_APP}/Contents/Info.plist", _APP_PLIST, 0o644)
        # 0o755: the execute bit is the whole reason this is an archive. A .app
        # whose executable is not executable does not open at all.
        add(f"{_APP}/Contents/MacOS/run",
            _APP_RUN.format(origin=origin, pick=_PICK_PY), 0o755)
        add("Start in a terminal.command", _AGENT_COMMAND.format(origin=origin, app=_APP), 0o755)
        add("README.txt", _AGENT_README.format(origin=origin, app=_APP), 0o644)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="7sigma-agent.zip"'},
    )


@router.get("/bench-policy.mobileconfig")
def bench_policy(request: Request):
    """The macOS profile that stops the bench asking for a port on every unit.

    The origin comes from the BROWSER (its `Origin`, else `Referer`), because
    only the browser knows which address the bench is actually open at, and a
    profile written for the wrong one silently does nothing. `public_base_url`
    is the fallback for a non-browser caller.
    """
    origin = _calling_origin(request)
    return Response(
        content=_mobileconfig([origin]),
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": 'attachment; filename="7sigma-bench-serial.mobileconfig"'},
    )


def _mosquitto_file(db: Session, project_id: int | None) -> Response:
    """The broker password file in PLAINTEXT, one `user:password` line per
    device — the format the old tool appended to mosquitto_passwords.txt
    (CE_Production_flasher/config.py:52). The developer who deploys the broker
    hashes it with `mosquitto_passwd -U` (user decision 2026-09-23: plaintext,
    not the stored `$6$` lines).

    237 legacy CE_Dongle_V2 units carry the `mqtt_creds_line` but no stored
    `mqtt_password` (2026-09-23). Their password is re-derived from the username
    and the salt inside that line, and EVERY password — stored or derived — is
    checked against the line's hash before it is written, so a line in this
    file is one the device was really programmed with. A mismatch fails the
    export rather than hand the broker a password that locks a device out.

    EVERY name a device was ever programmed with is listed, not only the
    current one (user decision 2026-09-23). 78 units (77 CE_Aqua_V2, 1
    CE_Dongle_V2) were first programmed as `dongle_<6 hex>` and later as `dongle_<12 hex>`; both names
    stay on the broker, so the file carries 5534 lines for 5456 devices."""
    q = (
        db.query(M.DeviceConfigValue.device_unit_id, M.DeviceConfigValue.key,
                 M.DeviceConfigValue.value, M.DeviceConfigValue.set_by_run_id)
        .join(M.DeviceUnit, M.DeviceUnit.id == M.DeviceConfigValue.device_unit_id)
        .filter(M.DeviceConfigValue.key.in_(("mqtt_password", "mqtt_creds_line")))
    )
    if project_id is not None:
        q = q.filter(M.DeviceUnit.project_id == project_id)
    creds_lines, stored_pw = [], {}
    for unit_id, key, value, run_id in q.all():
        if key == "mqtt_creds_line":
            creds_lines.append((unit_id, run_id, value))
        else:
            stored_pw[(unit_id, run_id)] = value  # written by the same run as its line
    passwords: dict[str, str] = {}
    broken = set()
    for unit_id, run_id, line in creds_lines:
        username, _, rest = line.partition(":")
        _, _, salt, stored_hash = rest.split("$", 3)
        password = stored_pw.get((unit_id, run_id)) or credentials.derive(username, "", salt)[1]
        if credentials.derive(username, password, salt)[3] != stored_hash:
            broken.add(username)
        elif passwords.setdefault(username, password) != password:
            broken.add(username)  # one name, two passwords: the broker can hold only one
    if broken:
        raise HTTPException(
            500, f"{len(broken)} MQTT user(s) whose password does not match the stored hash: "
                 + ", ".join(sorted(broken)[:20]))
    body = "\n".join(f"{u}:{p}" for u, p in sorted(passwords.items()))
    return Response(
        content=body + ("\n" if body else ""),
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="mosquitto_passwords.txt"'},
    )


@router.get("/mosquitto")
def mosquitto_export_all(project_id: int | None = None, db: Session = Depends(get_db)):
    return _mosquitto_file(db, project_id)


@router.get("/projects/{project_id}/mosquitto")
def mosquitto_export(project_id: int, db: Session = Depends(get_db)):
    return _mosquitto_file(db, project_id)


# ------------------------------------------------------------------ WebSocket

@router.websocket("/ws/{run_id}")
async def ws_run(websocket: WebSocket, run_id: int):
    await websocket.accept()
    engine = RunEngine(websocket, run_id)
    try:
        await engine.run()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
