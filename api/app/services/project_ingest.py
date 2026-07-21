"""Snapshot ingest pipeline.

For a git ref: materialize the tree, back up a tar.gz to MinIO, discover
KiCad boards (a repo may hold several .kicad_pro), read each board's
variants (.kicad_pro → schematic.variants, KiCad 10; absent on KiCad 9 →
single default variant) and layer stack, then extract a grouped BOM per
board × variant with kicad-cli (which resolves hierarchy, DNP and variants
authoritatively) and match lines to library components.

Matching: ${SYMBOL_NAME} == Component.name first (library symbols are named
after their component), then LCSC Part. Unmatched lines stay as external
parts with whatever fields the schematic carried.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .. import models as M
from ..db import SessionLocal
from . import gitrepo, project_render, storage

log = logging.getLogger(__name__)

# (ordinal "Name" type ["User Name"]) rows inside the board's (layers ...) block
_LAYER_RE = re.compile(r'^\s*\(\d+\s+"([^"]+)"\s+(signal|power|mixed|jumper|user)(?:\s+"([^"]+)")?\s*\)')

# Ingest status shared with the router (per snapshot id)
_active: dict[int, str] = {}
_active_lock = threading.Lock()


def active_stage(snapshot_id: int) -> str | None:
    with _active_lock:
        return _active.get(snapshot_id)


def _set_stage(snapshot_id: int, stage: str | None) -> None:
    with _active_lock:
        if stage is None:
            _active.pop(snapshot_id, None)
        else:
            _active[snapshot_id] = stage


def parse_variants(pro_text: str) -> list[dict]:
    """Variant list from a .kicad_pro. KiCad 10 stores them under
    schematic.variants; a recursive fallback scan tolerates format moves.
    Returns [] for KiCad 9 projects (no variant support)."""
    try:
        pro = json.loads(pro_text)
    except (json.JSONDecodeError, ValueError):
        return []

    def normalize(raw) -> list[dict]:
        out = []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict) and entry.get("name"):
                    out.append({"name": str(entry["name"]), "description": str(entry.get("description", ""))})
                elif isinstance(entry, str) and entry:
                    out.append({"name": entry, "description": ""})
        return out

    found = normalize((pro.get("schematic") or {}).get("variants"))
    if found:
        return found

    def scan(node) -> list[dict]:
        if isinstance(node, dict):
            for key, val in node.items():
                if key == "variants":
                    got = normalize(val)
                    if got:
                        return got
                got = scan(val)
                if got:
                    return got
        elif isinstance(node, list):
            for val in node:
                got = scan(val)
                if got:
                    return got
        return []

    return scan(pro)


def parse_layers(pcb_text: str) -> list[dict]:
    """Layer stack from the .kicad_pcb header: [{name, user_name, type}]."""
    layers = []
    in_block = False
    for line in pcb_text.splitlines():
        stripped = line.strip()
        if not in_block:
            if stripped.startswith("(layers"):
                in_block = True
            continue
        m = _LAYER_RE.match(line)
        if m:
            layers.append({"name": m.group(1), "type": m.group(2), "user_name": m.group(3) or ""})
        elif stripped.startswith(")") or (stripped.startswith("(") and not m):
            break
    return layers


def discover_boards(checkout: Path) -> list[dict]:
    """Find KiCad projects in the tree. Board name = .kicad_pro stem;
    duplicate stems get their directory prefixed."""
    boards = []
    for pro in sorted(checkout.rglob("*.kicad_pro")):
        rel = pro.relative_to(checkout)
        if any(part.startswith(".") or part.endswith("-backups") for part in rel.parts):
            continue
        stem = pro.stem
        sch = pro.with_suffix(".kicad_sch")
        pcb = pro.with_suffix(".kicad_pcb")
        boards.append(
            {
                "name": stem,
                "dir": str(rel.parent) if str(rel.parent) != "." else "",
                "pro": str(rel),
                "sch": str(sch.relative_to(checkout)) if sch.exists() else None,
                "pcb": str(pcb.relative_to(checkout)) if pcb.exists() else None,
            }
        )
    # de-duplicate names across directories
    seen: dict[str, int] = {}
    for b in boards:
        seen[b["name"]] = seen.get(b["name"], 0) + 1
    for b in boards:
        if seen[b["name"]] > 1 and b["dir"]:
            b["name"] = f"{b['dir'].replace('/', '_')}_{b['name']}"
    return boards


def _flag(v: str | None) -> bool:
    return bool((v or "").strip())


def parse_bom_csv(data: bytes) -> list[dict]:
    rows = []
    text = data.decode("utf-8-sig", errors="replace")
    for row in csv.DictReader(io.StringIO(text)):
        try:
            qty = int(float(row.get("Quantity") or 0))
        except (TypeError, ValueError):
            qty = 0
        rows.append(
            {
                "refs": (row.get("Reference") or "").strip(),
                "qty": qty,
                "value": (row.get("Value") or "").strip(),
                "footprint": (row.get("Footprint") or "").strip(),
                "lcsc": (row.get("LCSC") or "").strip(),
                "mpn": (row.get("MPN") or "").strip(),
                "manufacturer": (row.get("Manufacturer") or "").strip(),
                "symbol_name": (row.get("SymbolName") or "").strip(),
                "symbol_library": (row.get("SymbolLibrary") or "").strip(),
                "dnp": _flag(row.get("DNP")),
                "exclude_from_bom": _flag(row.get("ExcludeBOM")),
                "exclude_from_board": _flag(row.get("ExcludeBoard")),
            }
        )
    return rows


def _match_maps(db) -> tuple[dict[str, int], dict[str, int]]:
    """(component name -> id, LCSC part -> id) for published components."""
    comps = db.execute(
        select(M.Component).options(
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties)
        )
    ).scalars().all()
    by_name: dict[str, int] = {}
    by_lcsc: dict[str, int] = {}
    for comp in comps:
        cv = next((v for v in comp.versions if v.id == comp.current_version_id), None)
        if cv is None or cv.status != "published":
            continue
        by_name[comp.name] = comp.id
        for p in cv.properties:
            if p.key == "LCSC Part" and not p.is_null and p.value and p.value.strip():
                by_lcsc.setdefault(p.value.strip(), comp.id)
    return by_name, by_lcsc


def ingest(project_id: int, ref: str, ref_name: str = "", is_tag: bool = False,
           prerender: bool = False) -> int:
    """Full ingest of one ref; own DB session (background-thread friendly).
    Returns the snapshot id. Existing ready snapshots are returned as-is."""
    db = SessionLocal()
    snapshot_id = -1
    try:
        sha = gitrepo.rev_parse(project_id, ref)
        snap = db.query(M.ProjectSnapshot).filter_by(project_id=project_id, sha=sha).first()
        if snap and snap.status == "ready":
            return snap.id
        if snap is None:
            snap = M.ProjectSnapshot(project_id=project_id, sha=sha)
            db.add(snap)
        snap.ref_name = ref_name or ref
        snap.is_tag = is_tag
        snap.status = "ingesting"
        snap.error = None
        info = gitrepo.commit_info(project_id, sha)
        snap.commit_message = info.get("message", "")
        snap.committed_at = gitrepo.parse_iso(info.get("date", ""))
        db.commit()
        snapshot_id = snap.id
        _set_stage(snapshot_id, "checkout")

        warnings: list[str] = []
        try:
            checkout = gitrepo.materialize(project_id, sha)

            _set_stage(snapshot_id, "archive")
            archive_key = f"projects/{project_id}/snapshots/{sha}/source.tar.gz"
            if not storage.exists(archive_key):
                storage.put_bytes(archive_key, gitrepo.archive_tgz(project_id, sha), "application/gzip")

            _set_stage(snapshot_id, "discover")
            boards = discover_boards(checkout)
            if not boards:
                warnings.append("no .kicad_pro found in the tree")
            for b in boards:
                try:
                    b["variants"] = parse_variants((checkout / b["pro"]).read_text(encoding="utf-8"))
                except OSError as e:
                    b["variants"] = []
                    warnings.append(f"{b['name']}: cannot read project file — {e}")
                if b["pcb"]:
                    try:
                        b["layers"] = parse_layers((checkout / b["pcb"]).read_text(encoding="utf-8"))
                    except OSError as e:
                        b["layers"] = []
                        warnings.append(f"{b['name']}: cannot read board file — {e}")
                else:
                    b["layers"] = []

            _set_stage(snapshot_id, "bom")
            db.query(M.SnapshotBomLine).filter_by(snapshot_id=snapshot_id).delete()
            by_name, by_lcsc = _match_maps(db)
            line_count = 0
            matched_count = 0
            for b in boards:
                if not b["sch"]:
                    continue
                rel_sch = project_render.rel_checkout(project_id, sha, b["sch"])
                variant_names = [""] + [v["name"] for v in b.get("variants", [])]
                for variant in variant_names:
                    try:
                        data, _ = project_render.run_project_op("bom_csv", rel_sch, variant=variant)
                    except Exception as e:
                        warnings.append(f"{b['name']} variant '{variant or 'default'}': BOM export failed — {e}")
                        continue
                    for pos, row in enumerate(parse_bom_csv(data)):
                        comp_id = by_name.get(row["symbol_name"]) or by_lcsc.get(row["lcsc"])
                        if comp_id:
                            matched_count += 1
                        db.add(
                            M.SnapshotBomLine(
                                snapshot_id=snapshot_id,
                                board=b["name"],
                                variant=variant,
                                position=pos,
                                component_id=comp_id,
                                **row,
                            )
                        )
                        line_count += 1
            snap.boards = boards
            snap.report = {
                "boards": len(boards),
                "bom_lines": line_count,
                "matched_lines": matched_count,
                "warnings": warnings,
            }
            snap.status = "ready"
            db.commit()
        except Exception as e:
            db.rollback()
            snap = db.get(M.ProjectSnapshot, snapshot_id)
            if snap is not None:
                snap.status = "error"
                snap.error = str(e)
                db.commit()
            log.exception(f"ingest failed for project {project_id} ref {ref}")
            return snapshot_id

        if prerender:
            _set_stage(snapshot_id, "prerender")
            try:
                prerender_snapshot(project_id, sha, snap.boards or [])
            except Exception as e:
                log.warning(f"prerender failed for {project_id}@{sha[:10]}: {e}")
        return snapshot_id
    finally:
        _set_stage(snapshot_id, None)
        db.close()


def prerender_snapshot(project_id: int, sha: str, boards: list[dict]) -> None:
    """Warm the MinIO render cache: board GLB + all layer SVGs + schematic
    SVGs (default variant) + ERC/DRC. Sequential — one kicad-cli at a time."""
    for b in boards:
        name = b["name"]
        if b.get("pcb"):
            rel_pcb = project_render.rel_checkout(project_id, sha, b["pcb"])
            key = project_render.render_key(project_id, sha, name, "board.glb")
            _warm(key, "board_glb", rel_pcb)
            for layer in b.get("layers") or []:
                _try(lambda n=name, r=rel_pcb, ly=layer["name"]:
                     project_render.board_layer(project_id, sha, n, r, ly),
                     f"layer {layer['name']}")
            _warm(project_render.render_key(project_id, sha, name, "drc.json"), "drc", rel_pcb)
        if b.get("sch"):
            rel_sch = project_render.rel_checkout(project_id, sha, b["sch"])
            _try(lambda n=name, r=rel_sch: project_render.sch_pages_zip(project_id, sha, n, r, ""),
                 "schematic")
            _warm(project_render.render_key(project_id, sha, name, "erc.json"), "erc", rel_sch)


def _try(fn, what: str) -> None:
    try:
        fn()
    except Exception as e:
        log.warning(f"prerender {what}: {e}")


def _warm(key: str, op: str, rel_src: str, **kw) -> None:
    try:
        project_render.cached_op(key, op, rel_src, **kw)
    except Exception as e:
        log.warning(f"prerender {op} {key}: {e}")


def start_ingest(project_id: int, ref: str, ref_name: str = "", is_tag: bool = False,
                 prerender: bool = False) -> threading.Thread:
    t = threading.Thread(
        target=ingest, args=(project_id, ref, ref_name, is_tag, prerender), daemon=True
    )
    t.start()
    return t


def fetch_and_autoingest(project_id: int, git_url: str, token: str | None,
                         default_branch: str) -> dict:
    """Fetch the mirror, then ingest (with prerender) every tag and the
    default-branch head that has no ready snapshot yet. Runs synchronously
    for the fetch; ingests happen in one background worker."""
    gitrepo.fetch_mirror(project_id, git_url, token)
    db = SessionLocal()
    try:
        have = {
            s.sha
            for s in db.query(M.ProjectSnapshot)
            .filter_by(project_id=project_id)
            .filter(M.ProjectSnapshot.status.in_(("ready", "ingesting", "pending")))
            .all()
        }
    finally:
        db.close()

    todo: list[tuple[str, str, bool]] = []
    for tag in gitrepo.tags(project_id):
        if tag["sha"] not in have:
            todo.append((tag["sha"], tag["name"], True))
    branch = default_branch or "HEAD"
    try:
        head_sha = gitrepo.rev_parse(project_id, branch)
        if head_sha not in have and head_sha not in [t[0] for t in todo]:
            todo.append((head_sha, branch, False))
    except gitrepo.GitError:
        pass

    def worker():
        for sha, ref_name, is_tag in todo:
            try:
                ingest(project_id, sha, ref_name=ref_name, is_tag=is_tag, prerender=True)
            except Exception as e:
                log.warning(f"auto-ingest {ref_name} failed: {e}")

    if todo:
        threading.Thread(target=worker, daemon=True).start()
    return {"fetched": True, "queued": [{"sha": t[0], "ref": t[1], "tag": t[2]} for t in todo]}
