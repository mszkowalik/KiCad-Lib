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
import json
import struct
from datetime import datetime, timezone

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models as M
from ..services import storage
from ..services import crypto
from ..services.flasher import bundle, validate
from ..services.flasher.engine import RunEngine
from .util import audit

router = APIRouter(prefix="/api/flasher", tags=["flasher"])

TRANSPORT_PROFILES = ["uart_bridge", "usb_serial_jtag"]
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
    "lte_sim_pin",
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


# -------------------------------------------------------------- device files

class DeviceFileIn(BaseModel):
    filename: str
    description: str = ""
    content: str
    comment: str = ""
    created_by: str = ""


def _file_version_json(v: M.DeviceFileVersion, with_content: bool = False) -> dict:
    out = {
        "id": v.id, "version_no": v.version_no, "status": v.status,
        "sha256": v.sha256, "size_bytes": v.size_bytes, "comment": v.comment,
        "created_by": v.created_by, "created_at": _iso(v.created_at),
    }
    if with_content:
        out["content"] = v.content
    return out


def _normalise_text(raw: str) -> str:
    """Store device files with LF endings, always.

    Content addressing is only useful if the same source yields the same
    hash whoever uploads it. A CRLF file read as bytes hashes differently
    from the same file read as text (Python translates newlines), which made
    5 of the V3 files report "changed" on every import when nothing had.
    The device does not care: Berry and JSON both accept LF.
    """
    return raw.replace("\r\n", "\n").replace("\r", "\n")


@router.get("/projects/{project_id}/device-files")
def list_device_files(project_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(M.DeviceFile).filter(M.DeviceFile.project_id == project_id)
        .order_by(M.DeviceFile.filename).all()
    )
    return [
        {
            "id": f.id, "filename": f.filename, "description": f.description,
            "current_version_id": f.current_version_id,
            "versions": [_file_version_json(v) for v in f.versions],
        }
        for f in rows
    ]


@router.post("/projects/{project_id}/device-files")
def create_device_file_version(project_id: int, body: DeviceFileIn, db: Session = Depends(get_db)):
    """Create (or extend) a device file with a new DRAFT version."""
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "no such project")
    name = body.filename.strip()
    if not name or "/" in name or "\\" in name:
        raise HTTPException(400, "filename must be a bare name (it becomes the name on the device)")
    file = (
        db.query(M.DeviceFile)
        .filter(M.DeviceFile.project_id == project_id, M.DeviceFile.filename == name)
        .one_or_none()
    )
    if file is None:
        file = M.DeviceFile(project_id=project_id, filename=name, description=body.description)
        db.add(file)
        db.flush()
    elif body.description:
        file.description = body.description
    content = _normalise_text(body.content)
    content_bytes = content.encode("utf-8")
    version = M.DeviceFileVersion(
        device_file_id=file.id,
        version_no=max((v.version_no for v in file.versions), default=0) + 1,
        status="draft", content=content,
        sha256=hashlib.sha256(content_bytes).hexdigest(),
        size_bytes=len(content_bytes),
        created_by=body.created_by, comment=body.comment,
    )
    db.add(version)
    db.commit()
    return {"file_id": file.id, **_file_version_json(version)}


@router.get("/device-file-versions/{version_id}")
def get_device_file_version(version_id: int, db: Session = Depends(get_db)):
    v = db.get(M.DeviceFileVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such file version")
    return {"file_id": v.device_file_id, "filename": v.file.filename,
            **_file_version_json(v, with_content=True)}


@router.post("/device-file-versions/{version_id}/publish")
def publish_device_file_version(version_id: int, body: PublishIn, db: Session = Depends(get_db)):
    v = db.get(M.DeviceFileVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such file version")
    if v.status == "rejected":
        raise HTTPException(409, "version was rejected")
    v.status = "published"
    v.file.current_version_id = v.id
    db.commit()
    audit(db, "flasher.device_file_publish", "device_file_version", v.id,
          details=f"{v.file.filename} v{v.version_no}", actor=body.approved_by)
    return _file_version_json(v)


def _file_version_usage(db: Session, version_id: int) -> dict:
    """Deployment versions and bundles pinning this file version."""
    deps = (
        db.query(M.DeploymentVersion, M.Deployment)
        .join(M.DeploymentFile, M.DeploymentFile.deployment_version_id == M.DeploymentVersion.id)
        .join(M.Deployment, M.Deployment.id == M.DeploymentVersion.deployment_id)
        .filter(M.DeploymentFile.device_file_version_id == version_id).all()
    )
    bundles = (
        db.query(M.BerryBundle)
        .join(M.BerryBundleFile, M.BerryBundleFile.berry_bundle_id == M.BerryBundle.id)
        .filter(M.BerryBundleFile.device_file_version_id == version_id).all()
    )
    return {
        "versions": [{"deployment": d.name, "version_no": v.version_no} for v, d in deps],
        "bundles": [{"id": b.id, "label": b.label} for b in bundles],
    }


@router.delete("/device-file-versions/{version_id}")
def delete_device_file_version(version_id: int, db: Session = Depends(get_db)):
    v = db.get(M.DeviceFileVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such file version")
    use = _file_version_usage(db, version_id)
    if use["versions"] or use["bundles"]:
        raise HTTPException(
            409, f"{v.file.filename} v{v.version_no} is pinned by "
                 f"{len(use['versions'])} deployment version(s) and "
                 f"{len(use['bundles'])} bundle(s) — it stays")
    file = v.file
    name = f"{file.filename} v{v.version_no}"
    if file.current_version_id == v.id:
        others = [x for x in file.versions if x.id != v.id and x.status == "published"]
        file.current_version_id = others[-1].id if others else None
    db.delete(v)
    db.flush()
    # A file with no versions left is an empty shell — remove it too.
    if not [x for x in file.versions if x.id != v.id]:
        db.delete(file)
    db.commit()
    audit(db, "flasher.file_version_delete", "device_file_version", version_id, details=name)
    return {"ok": True}


@router.get("/device-file-versions/{version_id}/usage")
def device_file_version_usage(version_id: int, db: Session = Depends(get_db)):
    if db.get(M.DeviceFileVersion, version_id) is None:
        raise HTTPException(404, "no such file version")
    return _file_version_usage(db, version_id)


@router.post("/device-file-versions/{version_id}/reject")
def reject_device_file_version(version_id: int, body: PublishIn, db: Session = Depends(get_db)):
    v = db.get(M.DeviceFileVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such file version")
    if v.status == "published":
        raise HTTPException(409, "already published")
    v.status = "rejected"
    db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/device-files/import")
async def import_device_files(
    project_id: int,
    files: list[UploadFile] = File(...),
    label: str = Form(""),
    created_by: str = Form(""),
    publish: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Import a whole berryware FOLDER at once — the composer's file drop.

    Content-addressed per file: a file whose bytes match its newest published
    version is REUSED (no version churn), anything else becomes a new version.
    Returns the resolved set, so the composer can pin it directly. This is the
    step that turns "19 files, 19 manual publishes" into one action.
    """
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "no such project")
    resolved: list[dict] = []
    for upload in files:
        name = (upload.filename or "").split("/")[-1]
        if not name:
            continue
        raw = await upload.read()
        try:
            content = _normalise_text(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise HTTPException(
                400, f"{name} is not UTF-8 text — berryware files are sources, not binaries")
        sha = hashlib.sha256(content.encode()).hexdigest()
        df = (
            db.query(M.DeviceFile)
            .filter(M.DeviceFile.project_id == project_id, M.DeviceFile.filename == name)
            .one_or_none()
        )
        if df is None:
            df = M.DeviceFile(project_id=project_id, filename=name)
            db.add(df)
            db.flush()
        same = next((v for v in df.versions if v.sha256 == sha and v.status == "published"), None)
        if same is not None:
            resolved.append({"filename": name, "device_file_version_id": same.id,
                             "version_no": same.version_no, "state": "unchanged",
                             "size_bytes": same.size_bytes})
            continue
        v = M.DeviceFileVersion(
            device_file_id=df.id,
            version_no=max((x.version_no for x in df.versions), default=0) + 1,
            status="published" if publish else "draft",
            content=content, sha256=sha, size_bytes=len(content.encode()),
            created_by=created_by,
            comment=f"imported from {label}" if label else "folder import",
        )
        db.add(v)
        db.flush()
        if publish:
            df.current_version_id = v.id
        resolved.append({"filename": name, "device_file_version_id": v.id,
                         "version_no": v.version_no,
                         "state": "new" if v.version_no == 1 else "changed",
                         "size_bytes": v.size_bytes})
    db.flush()
    b = None
    published_ids = [r["device_file_version_id"] for r in resolved]
    if publish and published_ids:
        b = bundle.ensure_bundle(db, project_id, published_ids, label=label,
                                 created_by=created_by,
                                 comment=f"folder import ({len(resolved)} files)")
        db.flush()
    db.commit()
    audit(db, "flasher.files_import", "project", project_id,
          details=f"{len(resolved)} files ({label or 'folder import'})", actor=created_by)
    return {"label": (b.label if b else label),
            "bundle": bundle.bundle_json(db, b) if b else None,
            "files": sorted(resolved, key=lambda r: r["filename"]),
            "changed": sum(1 for r in resolved if r["state"] != "unchanged")}


@router.get("/projects/{project_id}/berry-bundles")
def list_berry_bundles(project_id: int, db: Session = Depends(get_db)):
    """The berryware SETS — what the user receives from the firmware repo,
    one row per distinct file set, newest first."""
    rows = (
        db.query(M.BerryBundle).filter(M.BerryBundle.project_id == project_id)
        .order_by(M.BerryBundle.id.desc()).all()
    )
    return [bundle.bundle_json(db, b) for b in rows]


class BundleIn(BaseModel):
    label: str
    file_version_ids: list[int]
    comment: str = ""
    created_by: str = ""


class BundlePatch(BaseModel):
    label: str | None = None
    comment: str | None = None


@router.post("/projects/{project_id}/berry-bundles")
def create_berry_bundle(project_id: int, body: BundleIn, db: Session = Depends(get_db)):
    """Name a file set by hand (the folder import is the usual route)."""
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "no such project")
    if not body.file_version_ids:
        raise HTTPException(400, "a bundle needs at least one file")
    for fv_id in body.file_version_ids:
        fv = db.get(M.DeviceFileVersion, fv_id)
        if fv is None or fv.file.project_id != project_id:
            raise HTTPException(400, f"device file version {fv_id} not in this project")
        if fv.status != "published":
            raise HTTPException(409, f"{fv.file.filename} v{fv.version_no} is {fv.status} — "
                                     "publish it before bundling")
    b = bundle.ensure_bundle(db, project_id, body.file_version_ids, label=body.label.strip(),
                             created_by=body.created_by, comment=body.comment)
    db.commit()
    return bundle.bundle_json(db, b)


@router.patch("/berry-bundles/{bundle_id}")
def patch_berry_bundle(bundle_id: int, body: BundlePatch, db: Session = Depends(get_db)):
    """Rename or annotate. The file SET is the identity and never changes — a
    different set is a different bundle."""
    b = db.get(M.BerryBundle, bundle_id)
    if b is None:
        raise HTTPException(404, "no such bundle")
    data = body.model_dump(exclude_unset=True)
    if data.get("label"):
        b.label = data["label"].strip()
        # Versions display the bundle's name, so keep them in step.
        for v in db.query(M.DeploymentVersion).filter(M.DeploymentVersion.berry_bundle_id == b.id):
            v.files_label = b.label
    if "comment" in data and data["comment"] is not None:
        b.comment = data["comment"]
    db.commit()
    return bundle.bundle_json(db, b)


@router.delete("/berry-bundles/{bundle_id}")
def delete_berry_bundle(bundle_id: int, db: Session = Depends(get_db)):
    """Refused while a deployment version uses it — that version's berryware
    identity is the bundle."""
    b = db.get(M.BerryBundle, bundle_id)
    if b is None:
        raise HTTPException(404, "no such bundle")
    used = (
        db.query(M.DeploymentVersion, M.Deployment)
        .join(M.Deployment, M.Deployment.id == M.DeploymentVersion.deployment_id)
        .filter(M.DeploymentVersion.berry_bundle_id == b.id).all()
    )
    if used:
        where = ", ".join(f"{d.name} v{v.version_no}" for v, d in used[:4])
        raise HTTPException(409, f'bundle "{b.label}" is used by {len(used)} version(s) '
                                 f"({where}) — it stays as their berryware identity")
    label = b.label
    db.delete(b)
    db.commit()
    audit(db, "flasher.bundle_delete", "berry_bundle", bundle_id, details=label)
    return {"ok": True}


@router.get("/files/{version_id}/{filename}")
def serve_device_file(version_id: int, filename: str, db: Session = Depends(get_db)):
    """What the DEVICE downloads with UrlFetch. Published versions only; the
    URL ends with the filename because Tasmota saves by the last path segment."""
    v = db.get(M.DeviceFileVersion, version_id)
    if v is None or v.status != "published":
        raise HTTPException(404, "no such published file version")
    if filename != v.file.filename:
        raise HTTPException(404, "filename does not match this version")
    return Response(content=v.content.encode("utf-8"), media_type="application/octet-stream")


# --------------------------------------------------------------- deployments
# ONE revision binds firmware + berryware + procedure + parameters (user
# decision 2026-07-29). Composing a new version is a single call: say what
# CHANGES, everything else is inherited from the version you start at.

class DeploymentIn(BaseModel):
    name: str
    description: str = ""
    chip: str = ""


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
    file_version_ids: list[int] | None = None
    files_label: str | None = None
    steps: list[dict] | None = None
    param_set_id: int | None = None
    param_defaults: dict | None = None
    transport_profile: str | None = None
    monitor_baud: int | None = None
    flash_config: dict | None = None
    # pin a whole berryware bundle instead of listing file versions
    berry_bundle_id: int | None = None
    # convenience: pin the newest published version of every file already in
    # the starting version (the composer's "latest berryware" button)
    latest_files: bool = False


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


@router.post("/projects/{project_id}/deployments")
def create_deployment(project_id: int, body: DeploymentIn, db: Session = Depends(get_db)):
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "no such project")
    d = M.Deployment(project_id=project_id, name=body.name.strip(),
                     description=body.description, chip=body.chip.strip())
    db.add(d)
    db.commit()
    return {"id": d.id}


@router.patch("/deployments/{deployment_id}")
def patch_deployment(deployment_id: int, body: DeploymentIn, db: Session = Depends(get_db)):
    d = db.get(M.Deployment, deployment_id)
    if d is None:
        raise HTTPException(404, "no such deployment")
    d.name = body.name.strip() or d.name
    d.description = body.description
    d.chip = body.chip.strip()
    db.commit()
    return _deployment_json(d, db)


@router.get("/deployments/{deployment_id}")
def get_deployment(deployment_id: int, db: Session = Depends(get_db)):
    d = db.get(M.Deployment, deployment_id)
    if d is None:
        raise HTTPException(404, "no such deployment")
    return _deployment_json(d, db, deep=True)


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
        status="draft", created_by=body.created_by, comment=body.comment,
        transport_profile=transport,
        monitor_baud=inherit("monitor_baud", base.monitor_baud if base else 115200,
                             body.monitor_baud),
        flash_config=inherit("flash_config", base.flash_config if base else None,
                             body.flash_config),
        steps=steps,
        param_set_id=inherit("param_set_id", base.param_set_id if base else None,
                             body.param_set_id),
        param_defaults=inherit("param_defaults", base.param_defaults if base else None,
                               body.param_defaults),
        files_label=inherit("files_label", base.files_label if base else "", body.files_label),
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

    # --- berryware files
    file_ids = body.file_version_ids
    if body.berry_bundle_id is not None:
        b = db.get(M.BerryBundle, body.berry_bundle_id)
        if b is None or b.project_id != d.project_id:
            raise HTTPException(400, "berry bundle not in this project")
        file_ids = [link.device_file_version_id for link in b.files]
    if file_ids is None and base is not None:
        if body.latest_files:
            # newest published version of each file the base pinned
            file_ids = []
            for link in sorted(base.files, key=lambda f: f.position):
                newest = (
                    db.query(M.DeviceFileVersion)
                    .filter(M.DeviceFileVersion.device_file_id == link.file_version.device_file_id,
                            M.DeviceFileVersion.status == "published")
                    .order_by(M.DeviceFileVersion.version_no.desc())
                    .first()
                )
                file_ids.append(newest.id if newest else link.device_file_version_id)
        else:
            file_ids = [f.device_file_version_id for f in sorted(base.files, key=lambda f: f.position)]
    ordered = _order_files(db, file_ids or [], d.project_id)
    for pos, fv_id in enumerate(ordered):
        db.add(M.DeploymentFile(deployment_version_id=version.id,
                                device_file_version_id=fv_id, position=pos))

    db.flush()
    db.refresh(version)
    bundle.stamp(db, version)
    bundle.link_bundle(db, version)
    if body.files_label:
        version.files_label = body.files_label
    db.commit()
    audit(db, "flasher.version_compose", "deployment_version", version.id,
          details=f"{d.name} v{version.version_no} (draft)", actor=body.created_by)
    return {**bundle.version_json(db, version),
            "validation": validate.check(db, version)}


def _order_files(db: Session, file_version_ids: list[int], project_id: int) -> list[int]:
    """Validate ownership, drop duplicates of the same file, and put
    autoexec.be last — a partial download must never leave a bootable device."""
    seen_files: set[int] = set()
    rows = []
    for fv_id in file_version_ids:
        fv = db.get(M.DeviceFileVersion, fv_id)
        if fv is None or fv.file.project_id != project_id:
            raise HTTPException(400, f"device file version {fv_id} not in this project")
        if fv.device_file_id in seen_files:
            raise HTTPException(400, f"two versions of {fv.file.filename} in one deployment")
        seen_files.add(fv.device_file_id)
        rows.append((fv.file.filename, fv.id))
    rows.sort(key=lambda r: (r[0] == "autoexec.be", r[0]))
    return [fv_id for _, fv_id in rows]


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
        "deployment": {"id": d.id, "name": d.name, "chip": d.chip, "project_id": d.project_id},
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
    berry_bundle_id: int | None = None
    steps: list[dict] | None = None
    images: list[ImageIn] | None = None
    file_version_ids: list[int] | None = None
    files_label: str | None = None
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
    for field in ("comment", "files_label", "param_set_id", "param_defaults",
                  "monitor_baud", "flash_config"):
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
    picked_file_ids = None
    if "berry_bundle_id" in data and data["berry_bundle_id"] is not None:
        b = db.get(M.BerryBundle, data["berry_bundle_id"])
        if b is None or b.project_id != d.project_id:
            raise HTTPException(400, "berry bundle not in this project")
        picked_file_ids = [link.device_file_version_id for link in b.files]
    elif "file_version_ids" in data and data["file_version_ids"] is not None:
        picked_file_ids = body.file_version_ids or []
    if picked_file_ids is not None:
        for old in list(v.files):
            db.delete(old)
        db.flush()
        for pos, fv_id in enumerate(_order_files(db, picked_file_ids, d.project_id)):
            db.add(M.DeploymentFile(deployment_version_id=v.id,
                                    device_file_version_id=fv_id, position=pos))
    db.flush()
    db.refresh(v)
    bundle.stamp(db, v)
    bundle.link_bundle(db, v)
    if "files_label" in data and data["files_label"]:
        v.files_label = data["files_label"]
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
    v.status = "published"
    v.approved_by = body.approved_by or None
    d = db.get(M.Deployment, v.deployment_id)
    d.current_version_id = v.id
    db.commit()
    audit(db, "flasher.version_publish", "deployment_version", v.id,
          details=f"{d.name} v{v.version_no}: {v.comment}", actor=body.approved_by)
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
    ch.updated_by = body.updated_by
    ch.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, "flasher.channel_set", "deployment", d.id,
          details=f"{d.name}: channel {name} -> version id {body.deployment_version_id}",
          actor=body.updated_by)
    return {"ok": True}


# ---------------------------------------------------------------- param sets

class ParamSetIn(BaseModel):
    values: dict[str, str | int | float]
    updated_by: str = ""


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
        out.append({"id": ps.id, "name": ps.name, "keys": keys,
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
    ps.values_enc = crypto.encrypt_token(json.dumps(body.values))
    ps.updated_by = body.updated_by
    ps.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": ps.id}


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
    db.delete(ps)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------- meta

@router.get("/meta")
def flasher_meta():
    return {"ops": STEP_OPS, "transport_profiles": TRANSPORT_PROFILES,
            "firmware_kinds": FIRMWARE_KINDS, "chips": CHIPS,
            "default_offsets": DEFAULT_OFFSETS}


# -------------------------------------------------------------------- devices

def _run_summary_json(r: M.ProgrammingRun, db: Session) -> dict:
    prod = db.get(M.ProductionRun, r.production_run_id) if r.production_run_id else None
    v = db.get(M.DeploymentVersion, r.deployment_version_id)
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


@router.get("/devices")
def list_devices(
    project_id: int | None = None,
    production_run_id: int | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 10000,
    db: Session = Depends(get_db),
):
    query = db.query(M.DeviceUnit)
    if project_id:
        query = query.filter(M.DeviceUnit.project_id == project_id)
    if status:
        query = query.filter(M.DeviceUnit.last_status == status)
    if production_run_id:
        ids = [
            r.device_unit_id
            for r in db.query(M.ProgrammingRun)
            .filter(M.ProgrammingRun.production_run_id == production_run_id,
                    M.ProgrammingRun.device_unit_id.isnot(None))
        ]
        query = query.filter(M.DeviceUnit.id.in_(ids or [-1]))
    if q:
        like = f"%{q}%"
        query = query.filter(
            M.DeviceUnit.mac.ilike(like)
            | M.DeviceUnit.serial.ilike(like)
            | M.DeviceUnit.tasmota_id.ilike(like)
            | M.DeviceUnit.imei.ilike(like)
            | M.DeviceUnit.iccid.ilike(like)
        )
    devices = query.order_by(M.DeviceUnit.last_seen.desc()).limit(min(limit, 10000)).all()
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
    out = []
    for d in devices:
        last = latest.get(d.id)
        prod = db.get(M.ProductionRun, last.production_run_id) if last else None
        out.append({
            "id": d.id, "mac": d.mac or "", "serial": d.serial, "chip": d.chip,
            "tasmota_id": d.tasmota_id, "imei": d.imei, "iccid": d.iccid,
            "imsi": d.imsi, "modem_model": d.modem_model,
            "project": {"id": d.project_id, "name": projects.get(d.project_id, "?")},
            "batch": {"id": prod.id, "label": prod.label} if prod else None,
            "last_status": d.last_status, "runs": counts.get(d.id, 0),
            "first_seen": _iso(d.first_seen), "last_seen": _iso(d.last_seen),
            "notes": d.notes,
        })
    return out


@router.get("/devices/{device_id}")
def device_detail(device_id: int, reveal: bool = False, db: Session = Depends(get_db)):
    d = db.get(M.DeviceUnit, device_id)
    if d is None:
        raise HTTPException(404, "no such device")
    project = db.get(M.Project, d.project_id)
    configs = [
        {
            "key": c.key,
            "value": (c.value if (reveal or not c.is_secret) else "•••"),
            "is_secret": c.is_secret, "current": c.current,
            "set_by_run_id": c.set_by_run_id, "set_at": _iso(c.set_at),
        }
        for c in sorted(d.configs, key=lambda c: (c.key, c.set_at.timestamp() if c.set_at else 0))
    ]
    return {
        "id": d.id, "mac": d.mac or "", "serial": d.serial, "chip": d.chip,
        "tasmota_id": d.tasmota_id, "imei": d.imei, "iccid": d.iccid, "imsi": d.imsi,
        "modem_model": d.modem_model, "modem_fw": d.modem_fw,
        "project": {"id": d.project_id, "name": project.name if project else "?"},
        "first_seen": _iso(d.first_seen), "last_seen": _iso(d.last_seen),
        "last_status": d.last_status, "notes": d.notes,
        "configs": configs,
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
    """
    production_run_id: int | None = None
    deployment_version_id: int | None = None
    operator: str = ""
    station: str = ""
    override_reason: str = ""


@router.post("/runs")
def create_run(body: RunCreate, db: Session = Depends(get_db)):
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
    if not draft_run:
        result = validate.check(db, v)
        if not result["ok"]:
            raise HTTPException(409, "this version no longer validates: "
                                     + " | ".join(result["errors"]))
    override = bool(assigned and version_id != assigned)
    if override and not body.override_reason.strip():
        raise HTTPException(409, "programming with a non-assigned version needs an override_reason")
    run = M.ProgrammingRun(
        production_run_id=prod.id if prod else None, deployment_version_id=v.id,
        firmware_fingerprint=v.firmware_fingerprint, files_fingerprint=v.files_fingerprint,
        draft_run=draft_run,
        release_override_reason=body.override_reason.strip() if override else "",
        operator=body.operator, station=body.station, status="running",
    )
    db.add(run)
    db.commit()
    if override:
        audit(db, "flasher.run_override", "programming_run", run.id,
              details=f"batch {prod.id if prod else '-'} assigned version {assigned}, "
                      f"ran {version_id}: {body.override_reason}", actor=body.operator)
    return {"run_id": run.id, "deployment_version_id": v.id, "draft_run": draft_run}


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
        "steps": [
            {
                "idx": s.idx, "op": s.op, "label": s.label, "status": s.status,
                "started_at": _iso(s.started_at), "duration_ms": s.duration_ms,
                "error": s.error, "response": s.response,
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
    runs = (
        db.query(M.ProgrammingRun)
        .filter(M.ProgrammingRun.production_run_id == production_run_id)
        .order_by(M.ProgrammingRun.started_at.desc())
        .all()
    )
    norm = lambda s: s.replace(":", "").replace("-", "").upper()  # noqa: E731
    planned = {norm(d.serial): d.serial for d in prod.devices}
    device_ids = {r.device_unit_id for r in runs if r.device_unit_id}
    devices = {
        d.id: d for d in db.query(M.DeviceUnit).filter(M.DeviceUnit.id.in_(device_ids or [-1]))
    }
    programmed_ok: set[str] = set()
    seen: set[str] = set()
    for r in runs:
        if not r.device_unit_id:
            continue
        serial = norm(devices[r.device_unit_id].serial)
        seen.add(serial)
        if r.status == "pass":
            programmed_ok.add(serial)
    return {
        "planned": len(planned),
        "programmed_ok": len(programmed_ok & set(planned)),
        "failed_only": sorted(seen - programmed_ok),
        "extra": sorted(programmed_ok - set(planned)),
        "missing": sorted(set(planned) - programmed_ok),
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

@router.get("/projects/{project_id}/mosquitto")
def mosquitto_export(project_id: int, db: Session = Depends(get_db)):
    """Regenerates the broker password file from device_config_values —
    replaces the hand-appended mosquitto_passwords.txt."""
    rows = (
        db.query(M.DeviceConfigValue)
        .join(M.DeviceUnit, M.DeviceUnit.id == M.DeviceConfigValue.device_unit_id)
        .filter(M.DeviceUnit.project_id == project_id,
                M.DeviceConfigValue.key == "mqtt_creds_line",
                M.DeviceConfigValue.current.is_(True))
        .all()
    )
    body = "\n".join(sorted(r.value for r in rows))
    return Response(content=body + ("\n" if body else ""), media_type="text/plain")


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
