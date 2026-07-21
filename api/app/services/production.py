"""Production file sets for production runs.

The user fabs at JLCPCB via the Fabrication Toolkit exporter, which writes a
`production/` directory next to the board (gerber zip + bom.csv + positions
csv). Sets are VERSIONED and immutable:

    repo       imported from the snapshot's production/ dir (default on run
               creation when present)
    upload     user-uploaded replacement (always allowed, even when the repo
               has a production dir)
    generated  kicad-cli fab bundle (gerbers/drill/pos), for boards without
               an exporter output

The JLC bom.csv lists only the components JLCPCB places — it is assembly
info, NEVER the total BOM. Gerber zips are stored both as the zip and as
extracted members so the gerber viewer can address individual layers.
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from . import gitrepo, project_render, storage

log = logging.getLogger(__name__)

GERBER_EXTS = {
    ".gbr", ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gtp", ".gbp",
    ".gm1", ".gm13", ".gko", ".g1", ".g2", ".g3", ".g4", ".gd1", ".gg1",
}
DRILL_EXTS = {".drl", ".xln", ".exc"}


def classify(filename: str) -> str:
    name = PurePosixPath(filename).name.lower()
    ext = PurePosixPath(name).suffix
    if ext == ".csv":
        if "bom" in name:
            return "jlc_bom"
        if "position" in name or "cpl" in name or name.endswith("-pos.csv") or "top-pos" in name:
            return "jlc_cpl"
        return "other"
    if ext == ".zip":
        return "gerber_zip"
    if ext in GERBER_EXTS or (ext and ext[1:].isdigit() and ext.startswith(".g")):
        return "gerber"
    if ext in DRILL_EXTS:
        return "drill"
    return "other"


def _set_prefix(run: M.ProductionRun, version_no: int) -> str:
    return f"projects/{run.project_id}/runs/{run.id}/production/v{version_no}"


def create_set(db: Session, run: M.ProductionRun, source: str,
               files: list[tuple[str, bytes]], comment: str = "") -> M.ProductionFileSet:
    """New immutable version from (filename, bytes) pairs. Zip members that
    look like gerber/drill layers are additionally stored extracted."""
    if not files:
        raise ValueError("no files to store")
    last = (
        db.query(M.ProductionFileSet).filter_by(run_id=run.id)
        .order_by(M.ProductionFileSet.version_no.desc()).first()
    )
    pset = M.ProductionFileSet(
        run_id=run.id, version_no=(last.version_no + 1 if last else 1),
        source=source, comment=comment,
    )
    db.add(pset)
    db.flush()
    prefix = _set_prefix(run, pset.version_no)
    for filename, data in files:
        safe = PurePosixPath(filename).name
        kind = classify(safe)
        key = f"{prefix}/{safe}"
        storage.put_bytes(key, data)
        db.add(M.ProductionFile(set_id=pset.id, filename=safe, kind=kind,
                                size_bytes=len(data), minio_key=key))
        if kind == "gerber_zip":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for member in z.namelist():
                        mkind = classify(member)
                        if mkind not in ("gerber", "drill"):
                            continue
                        mdata = z.read(member)
                        mname = PurePosixPath(member).name
                        mkey = f"{prefix}/gerbers/{mname}"
                        storage.put_bytes(mkey, mdata)
                        db.add(M.ProductionFile(set_id=pset.id, filename=mname, kind=mkind,
                                                extracted=True, size_bytes=len(mdata),
                                                minio_key=mkey))
            except zipfile.BadZipFile:
                log.warning(f"production upload {safe}: not a valid zip, stored as-is")
    db.commit()
    return pset


def repo_production_paths(project_id: int, sha: str, board: dict) -> list[str]:
    """Paths of production/ files for this board at `sha` (bare-repo lookup,
    no checkout needed). Board-dir production/ first, repo root as fallback."""
    try:
        all_files = gitrepo.list_files(project_id, sha)
    except gitrepo.GitError:
        return []
    board_dir = str(PurePosixPath(board["pro"]).parent)
    prefixes = []
    if board_dir and board_dir != ".":
        prefixes.append(f"{board_dir}/production/")
    prefixes.append("production/")
    for prefix in prefixes:
        hits = [
            f["path"]
            for f in all_files
            # only the flat exporter output — the Fabrication Toolkit keeps
            # dated old exports in production/backups/, which we skip
            if f["path"].startswith(prefix) and "/" not in f["path"][len(prefix):]
        ]
        if hits:
            return hits
    return []


def import_from_repo(db: Session, run: M.ProductionRun, snapshot: M.ProjectSnapshot,
                     board: dict) -> M.ProductionFileSet | None:
    paths = repo_production_paths(snapshot.project_id, snapshot.sha, board)
    if not paths:
        return None
    files = []
    for path in paths:
        try:
            files.append((PurePosixPath(path).name,
                          gitrepo.show_file(snapshot.project_id, snapshot.sha, path)))
        except gitrepo.GitError as e:
            log.warning(f"production import {path}: {e}")
    if not files:
        return None
    return create_set(db, run, "repo", files,
                      comment=f"production/ at {snapshot.ref_name or snapshot.sha[:10]}")


def generate_fab(db: Session, run: M.ProductionRun, snapshot: M.ProjectSnapshot,
                 board: dict) -> M.ProductionFileSet:
    """kicad-cli gerbers/drill/pos bundle as a new production set."""
    if not board.get("pcb"):
        raise ValueError("board has no .kicad_pcb")
    gitrepo.materialize(snapshot.project_id, snapshot.sha)
    rel = project_render.rel_checkout(snapshot.project_id, snapshot.sha, board["pcb"])
    key = project_render.render_key(snapshot.project_id, snapshot.sha, board["name"], "fab.zip")
    data, _media = project_render.cached_op(key, "fab", rel)
    return create_set(db, run, "generated", [(f"{board['name']}-fab.zip", data)],
                      comment=f"kicad-cli fab at {snapshot.ref_name or snapshot.sha[:10]}")


def current_set(db: Session, run_id: int) -> M.ProductionFileSet | None:
    return (
        db.query(M.ProductionFileSet).filter_by(run_id=run_id)
        .order_by(M.ProductionFileSet.version_no.desc()).first()
    )


def _detect_column(header: list[str], *needles: str) -> int | None:
    for i, col in enumerate(header):
        low = col.strip().lower()
        if any(n in low for n in needles):
            return i
    return None


def parse_jlc_bom(data: bytes) -> dict:
    """JLC assembly BOM (Comment/Designator/Footprint/LCSC): rows + the set
    of designators JLCPCB will place."""
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return {"rows": [], "designators": []}
    header = rows[0]
    di = _detect_column(header, "designator")
    ci = _detect_column(header, "comment", "value")
    fi = _detect_column(header, "footprint", "package")
    li = _detect_column(header, "lcsc", "part #", "part#")
    out_rows = []
    designators: list[str] = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        refs = [r.strip() for r in (row[di] if di is not None and di < len(row) else "").split(",") if r.strip()]
        designators.extend(refs)
        out_rows.append({
            "comment": row[ci].strip() if ci is not None and ci < len(row) else "",
            "designators": refs,
            "footprint": row[fi].strip() if fi is not None and fi < len(row) else "",
            "lcsc": row[li].strip() if li is not None and li < len(row) else "",
        })
    return {"rows": out_rows, "designators": sorted(set(designators))}


def parse_jlc_cpl(data: bytes) -> dict:
    """JLC placement file: just the designator list (positions live at JLC)."""
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return {"designators": []}
    di = _detect_column(rows[0], "designator", "ref")
    if di is None:
        return {"designators": []}
    designators = [row[di].strip() for row in rows[1:] if di < len(row) and row[di].strip()]
    return {"designators": sorted(set(designators))}


def set_json(pset: M.ProductionFileSet) -> dict:
    return {
        "id": pset.id,
        "version_no": pset.version_no,
        "source": pset.source,
        "comment": pset.comment,
        "created_at": pset.created_at.isoformat(),
        "files": [
            {"id": f.id, "filename": f.filename, "kind": f.kind, "extracted": f.extracted,
             "size_bytes": f.size_bytes}
            for f in pset.files
        ],
    }


def production_info(db: Session, run: M.ProductionRun, snapshot: M.ProjectSnapshot | None,
                    board: dict | None) -> dict:
    """Everything the run UI needs: all set versions, JLC assembly info from
    the current set, and whether the repo offers a production/ dir."""
    sets = (
        db.query(M.ProductionFileSet).filter_by(run_id=run.id)
        .order_by(M.ProductionFileSet.version_no.desc()).all()
    )
    cur = sets[0] if sets else None
    jlc_bom = None
    jlc_designators: list[str] = []
    if cur is not None:
        for f in cur.files:
            if f.kind == "jlc_bom":
                data = storage.get_bytes(f.minio_key)
                if data:
                    jlc_bom = parse_jlc_bom(data)
                    jlc_designators = jlc_bom["designators"]
                break
        if not jlc_designators:
            for f in cur.files:
                if f.kind == "jlc_cpl":
                    data = storage.get_bytes(f.minio_key)
                    if data:
                        jlc_designators = parse_jlc_cpl(data)["designators"]
                    break
    repo_available = bool(
        snapshot is not None and board is not None
        and repo_production_paths(snapshot.project_id, snapshot.sha, board)
    )
    return {
        "sets": [set_json(s) for s in sets],
        "current_set_id": cur.id if cur else None,
        "repo_available": repo_available,
        "jlc_bom": jlc_bom,
        "jlc_designators": jlc_designators,
    }


# ------------------------------------------------------------ gerber viewer

def gerber_workdir(pset: M.ProductionFileSet) -> str:
    """Materialize the set's viewable gerber/drill files onto the shared
    DATA_DIR volume (render container sees them read-only); returns the
    path relative to DATA_DIR."""
    rel = f"gerber-work/{pset.id}"
    root = settings.data_dir / rel
    marker = root / ".complete"
    if not marker.exists():
        root.mkdir(parents=True, exist_ok=True)
        for f in pset.files:
            if f.kind not in ("gerber", "drill"):
                continue
            data = storage.get_bytes(f.minio_key)
            if data is None:
                continue
            (root / f.filename).write_bytes(data)
        marker.touch()
    return rel


def render_gerber_svg(pset: M.ProductionFileSet, run: M.ProductionRun,
                      selection: list[dict]) -> bytes:
    """Composite SVG of the selected layers (cached per selection)."""
    import hashlib
    import json as _json

    rel = gerber_workdir(pset)
    digest = hashlib.sha256(_json.dumps(selection, sort_keys=True).encode()).hexdigest()[:16]
    key = f"{_set_prefix(run, pset.version_no)}/render/{digest}.svg"
    data, _media = project_render.cached_op(key, "gerber_svg", rel, files=selection)
    return data
