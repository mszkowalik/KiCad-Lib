"""Production flasher: firmware releases, device files, deployment scripts,
programming runs, produced devices.

Vocabulary (user decision 2026-07-29, docs/flasher/design.md §13):
a RELEASE is only the flash (firmware images at offsets); a DEPLOYMENT SCRIPT
is the versioned config/test scenario that PINS one release version and a set
of device file versions. A programming run pins the script version it ran.

`GET /files/{version_id}/{filename}` is deliberately unauthenticated: the
DEVICE fetches it over plain HTTP with UrlFetch (no auth headers), same
reachability rule as the KiCad HTTP catalog.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, UploadFile, WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models as M
from ..services import storage
from ..services import crypto
from ..services.flasher.engine import RunEngine
from .util import audit

router = APIRouter(prefix="/api/flasher", tags=["flasher"])

TRANSPORT_PROFILES = ["uart_bridge", "usb_serial_jtag"]
FIRMWARE_KINDS = ["factory", "app", "filesystem", "safeboot"]
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
    return [_firmware_json(a) for a in rows]


def _firmware_json(a: M.FirmwareAsset) -> dict:
    return {
        "id": a.id, "filename": a.filename, "sha256": a.sha256,
        "size_bytes": a.size_bytes, "chip": a.chip, "kind": a.kind,
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
    sha = hashlib.sha256(data).hexdigest()
    existing = (
        db.query(M.FirmwareAsset)
        .filter(M.FirmwareAsset.project_id == project_id, M.FirmwareAsset.sha256 == sha)
        .one_or_none()
    )
    if existing:
        return {"existing": True, **_firmware_json(existing)}
    key = f"firmware/{project_id}/{sha}/{file.filename}"
    storage.put_bytes(key, data)
    asset = M.FirmwareAsset(
        project_id=project_id, filename=file.filename or "firmware.bin", sha256=sha,
        size_bytes=len(data), chip=chip, kind=kind, minio_key=key,
        build_label=build_label, notes=notes, uploaded_by=uploaded_by,
    )
    db.add(asset)
    db.commit()
    audit(db, "flasher.firmware_upload", "firmware_asset", asset.id,
          details=f"{asset.filename} ({len(data)} B, {kind})", actor=uploaded_by)
    return {"existing": False, **_firmware_json(asset)}


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


# ------------------------------------------------------------------ releases

class ReleaseIn(BaseModel):
    name: str
    chip: str = ""
    description: str = ""


class ReleaseImageIn(BaseModel):
    firmware_asset_id: int
    address: str = "0x0"


class ReleaseVersionIn(BaseModel):
    comment: str = ""
    created_by: str = ""
    flash_config: dict | None = None
    images: list[ReleaseImageIn] = []


def _release_version_json(v: M.ReleaseVersion) -> dict:
    return {
        "id": v.id, "version_no": v.version_no, "status": v.status,
        "comment": v.comment, "created_by": v.created_by,
        "approved_by": v.approved_by, "flash_config": v.flash_config,
        "created_at": _iso(v.created_at),
        "images": [
            {
                "firmware_asset_id": i.firmware_asset_id, "address": i.address,
                "filename": i.asset.filename, "kind": i.asset.kind,
                "size_bytes": i.asset.size_bytes, "sha256": i.asset.sha256,
            }
            for i in v.images
        ],
    }


@router.get("/projects/{project_id}/releases")
def list_releases(project_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(M.Release).filter(M.Release.project_id == project_id)
        .order_by(M.Release.name).all()
    )
    return [
        {
            "id": r.id, "name": r.name, "chip": r.chip, "description": r.description,
            "current_version_id": r.current_version_id,
            "versions": [_release_version_json(v) for v in r.versions],
        }
        for r in rows
    ]


@router.post("/projects/{project_id}/releases")
def create_release(project_id: int, body: ReleaseIn, db: Session = Depends(get_db)):
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "no such project")
    release = M.Release(project_id=project_id, name=body.name.strip(),
                        chip=body.chip.strip(), description=body.description)
    db.add(release)
    db.commit()
    return {"id": release.id}


@router.post("/releases/{release_id}/versions")
def create_release_version(release_id: int, body: ReleaseVersionIn, db: Session = Depends(get_db)):
    release = db.get(M.Release, release_id)
    if release is None:
        raise HTTPException(404, "no such release")
    if not body.images:
        raise HTTPException(400, "a release version needs at least one image")
    seen_addr = set()
    for img in body.images:
        asset = db.get(M.FirmwareAsset, img.firmware_asset_id)
        if asset is None or asset.project_id != release.project_id:
            raise HTTPException(400, f"firmware asset {img.firmware_asset_id} not in this project")
        if img.address in seen_addr:
            raise HTTPException(400, f"two images at address {img.address}")
        seen_addr.add(img.address)
    version_no = max((v.version_no for v in release.versions), default=0) + 1
    version = M.ReleaseVersion(
        release_id=release.id, version_no=version_no, status="draft",
        created_by=body.created_by, comment=body.comment, flash_config=body.flash_config,
    )
    db.add(version)
    db.flush()
    for pos, img in enumerate(body.images):
        db.add(M.ReleaseImage(release_version_id=version.id,
                              firmware_asset_id=img.firmware_asset_id,
                              address=img.address, position=pos))
    db.commit()
    return _release_version_json(version)


class PublishIn(BaseModel):
    approved_by: str = ""


@router.post("/release-versions/{version_id}/publish")
def publish_release_version(version_id: int, body: PublishIn, db: Session = Depends(get_db)):
    version = db.get(M.ReleaseVersion, version_id)
    if version is None:
        raise HTTPException(404, "no such release version")
    if version.status == "rejected":
        raise HTTPException(409, "version was rejected")
    version.status = "published"
    version.approved_by = body.approved_by or None
    version.release.current_version_id = version.id
    db.commit()
    audit(db, "flasher.release_publish", "release_version", version.id,
          details=f"{version.release.name} v{version.version_no}", actor=body.approved_by)
    return _release_version_json(version)


@router.post("/release-versions/{version_id}/reject")
def reject_release_version(version_id: int, body: PublishIn, db: Session = Depends(get_db)):
    version = db.get(M.ReleaseVersion, version_id)
    if version is None:
        raise HTTPException(404, "no such release version")
    if version.status == "published":
        raise HTTPException(409, "already published")
    version.status = "rejected"
    db.commit()
    return {"ok": True}


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
    content_bytes = body.content.encode("utf-8")
    version = M.DeviceFileVersion(
        device_file_id=file.id,
        version_no=max((v.version_no for v in file.versions), default=0) + 1,
        status="draft", content=body.content,
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


# ------------------------------------------------------- deployment scripts

class ScriptIn(BaseModel):
    name: str
    description: str = ""


class ScriptVersionIn(BaseModel):
    comment: str = ""
    created_by: str = ""
    release_version_id: int | None = None
    transport_profile: str = "uart_bridge"
    monitor_baud: int = 115200
    steps: list[dict] = []
    param_set_id: int | None = None
    param_defaults: dict | None = None
    file_version_ids: list[int] = []


def _script_version_json(v: M.DeploymentScriptVersion, db: Session) -> dict:
    release = None
    if v.release_version_id:
        rv = db.get(M.ReleaseVersion, v.release_version_id)
        if rv:
            release = {"release_version_id": rv.id, "release_id": rv.release_id,
                       "name": rv.release.name, "version_no": rv.version_no,
                       "status": rv.status, "chip": rv.release.chip}
    return {
        "id": v.id, "version_no": v.version_no, "status": v.status,
        "comment": v.comment, "created_by": v.created_by, "approved_by": v.approved_by,
        "transport_profile": v.transport_profile, "monitor_baud": v.monitor_baud,
        "steps": v.steps or [], "param_set_id": v.param_set_id,
        "param_defaults": v.param_defaults, "created_at": _iso(v.created_at),
        "release": release,
        "files": [
            {
                "device_file_version_id": link.device_file_version_id,
                "filename": link.file_version.file.filename,
                "version_no": link.file_version.version_no,
                "status": link.file_version.status,
                "size_bytes": link.file_version.size_bytes,
            }
            for link in v.files
        ],
    }


@router.get("/projects/{project_id}/scripts")
def list_scripts(project_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(M.DeploymentScript).filter(M.DeploymentScript.project_id == project_id)
        .order_by(M.DeploymentScript.name).all()
    )
    return [
        {
            "id": s.id, "name": s.name, "description": s.description,
            "current_version_id": s.current_version_id,
            "versions": [_script_version_json(v, db) for v in s.versions],
        }
        for s in rows
    ]


@router.post("/projects/{project_id}/scripts")
def create_script(project_id: int, body: ScriptIn, db: Session = Depends(get_db)):
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "no such project")
    script = M.DeploymentScript(project_id=project_id, name=body.name.strip(),
                                description=body.description)
    db.add(script)
    db.commit()
    return {"id": script.id}


@router.post("/scripts/{script_id}/versions")
def create_script_version(script_id: int, body: ScriptVersionIn, db: Session = Depends(get_db)):
    script = db.get(M.DeploymentScript, script_id)
    if script is None:
        raise HTTPException(404, "no such deployment script")
    if body.transport_profile not in TRANSPORT_PROFILES:
        raise HTTPException(400, f"transport_profile must be one of {TRANSPORT_PROFILES}")
    if body.release_version_id is not None:
        rv = db.get(M.ReleaseVersion, body.release_version_id)
        if rv is None or rv.release.project_id != script.project_id:
            raise HTTPException(400, "release version not in this project")
    for step in body.steps:
        if step.get("op") not in STEP_OPS:
            raise HTTPException(400, f"unknown op {step.get('op')!r}")
    file_versions = []
    for fvid in body.file_version_ids:
        fv = db.get(M.DeviceFileVersion, fvid)
        if fv is None or fv.file.project_id != script.project_id:
            raise HTTPException(400, f"device file version {fvid} not in this project")
        file_versions.append(fv)
    version = M.DeploymentScriptVersion(
        deployment_script_id=script.id,
        version_no=max((v.version_no for v in script.versions), default=0) + 1,
        status="draft", created_by=body.created_by, comment=body.comment,
        release_version_id=body.release_version_id,
        transport_profile=body.transport_profile, monitor_baud=body.monitor_baud,
        steps=body.steps, param_set_id=body.param_set_id,
        param_defaults=body.param_defaults,
    )
    db.add(version)
    db.flush()
    for pos, fv in enumerate(file_versions):
        db.add(M.DeploymentScriptFile(deployment_script_version_id=version.id,
                                      device_file_version_id=fv.id, position=pos))
    db.commit()
    return _script_version_json(version, db)


@router.get("/script-versions/{version_id}")
def get_script_version(version_id: int, db: Session = Depends(get_db)):
    v = db.get(M.DeploymentScriptVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such script version")
    return {"script_id": v.deployment_script_id, "script_name": v.script.name,
            **_script_version_json(v, db)}


@router.post("/script-versions/{version_id}/publish")
def publish_script_version(version_id: int, body: PublishIn, db: Session = Depends(get_db)):
    v = db.get(M.DeploymentScriptVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such script version")
    if v.status == "rejected":
        raise HTTPException(409, "version was rejected")
    # A published scenario must only reference published artifacts — a run
    # cannot flash a draft.
    if v.release_version_id:
        rv = db.get(M.ReleaseVersion, v.release_version_id)
        if rv.status != "published":
            raise HTTPException(409, f"pinned release version is {rv.status}, publish it first")
    for link in v.files:
        if link.file_version.status != "published":
            raise HTTPException(
                409,
                f"pinned file {link.file_version.file.filename} "
                f"v{link.file_version.version_no} is {link.file_version.status}, publish it first",
            )
    v.status = "published"
    v.approved_by = body.approved_by or None
    v.script.current_version_id = v.id
    db.commit()
    audit(db, "flasher.script_publish", "deployment_script_version", v.id,
          details=f"{v.script.name} v{v.version_no}", actor=body.approved_by)
    return _script_version_json(v, db)


@router.post("/script-versions/{version_id}/reject")
def reject_script_version(version_id: int, body: PublishIn, db: Session = Depends(get_db)):
    v = db.get(M.DeploymentScriptVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such script version")
    if v.status == "published":
        raise HTTPException(409, "already published")
    v.status = "rejected"
    db.commit()
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
            "firmware_kinds": FIRMWARE_KINDS}


# -------------------------------------------------------------------- devices

def _run_summary_json(r: M.ProgrammingRun, db: Session) -> dict:
    prod = db.get(M.ProductionRun, r.production_run_id) if r.production_run_id else None
    sv = db.get(M.DeploymentScriptVersion, r.deployment_script_version_id)
    return {
        "id": r.id, "status": r.status, "operator": r.operator, "station": r.station,
        "attempt_no": r.attempt_no, "error": r.error,
        "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
        "duration_ms": r.duration_ms,
        "production_run": {"id": prod.id, "label": prod.label} if prod else None,
        "script": {
            "version_id": sv.id, "name": sv.script.name, "version_no": sv.version_no,
        } if sv else None,
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
    production_run_id: int
    deployment_script_version_id: int | None = None
    operator: str = ""
    station: str = ""
    override_reason: str = ""


@router.post("/runs")
def create_run(body: RunCreate, db: Session = Depends(get_db)):
    prod = db.get(M.ProductionRun, body.production_run_id)
    if prod is None:
        raise HTTPException(404, "no such production run")
    assigned = prod.deployment_script_version_id
    version_id = body.deployment_script_version_id or assigned
    if not version_id:
        raise HTTPException(409, "the batch has no assigned deployment script and none was given")
    sv = db.get(M.DeploymentScriptVersion, version_id)
    if sv is None:
        raise HTTPException(404, "no such deployment script version")
    if sv.status != "published":
        raise HTTPException(409, f"script version is {sv.status} — publish it before programming")
    if sv.script.project_id != prod.project_id:
        raise HTTPException(409, "script belongs to a different project than the batch")
    override = bool(assigned and version_id != assigned)
    if override and not body.override_reason.strip():
        raise HTTPException(409, "programming with a non-assigned script needs an override_reason")
    run = M.ProgrammingRun(
        production_run_id=prod.id, deployment_script_version_id=sv.id,
        release_version_id=sv.release_version_id,
        release_override_reason=body.override_reason.strip() if override else "",
        operator=body.operator, station=body.station, status="running",
    )
    db.add(run)
    db.commit()
    if override:
        audit(db, "flasher.run_override", "programming_run", run.id,
              details=f"batch {prod.id} assigned v{assigned}, ran v{version_id}: "
                      f"{body.override_reason}", actor=body.operator)
    return {"run_id": run.id}


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
        "release_version_id": r.release_version_id,
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
        "assigned_script_version_id": prod.deployment_script_version_id,
    }


class BatchScriptIn(BaseModel):
    deployment_script_version_id: int | None


@router.put("/production-runs/{production_run_id}/script")
def assign_batch_script(production_run_id: int, body: BatchScriptIn, db: Session = Depends(get_db)):
    prod = db.get(M.ProductionRun, production_run_id)
    if prod is None:
        raise HTTPException(404, "no such production run")
    if body.deployment_script_version_id is not None:
        sv = db.get(M.DeploymentScriptVersion, body.deployment_script_version_id)
        if sv is None:
            raise HTTPException(404, "no such script version")
        if sv.script.project_id != prod.project_id:
            raise HTTPException(409, "script belongs to a different project")
    prod.deployment_script_version_id = body.deployment_script_version_id
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
