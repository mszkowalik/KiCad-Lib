"""Import station — DESTRUCTIVE by design.

Wipes the whole database and mirror, then reloads everything from the mounted
library repo working tree: Sources/*.yaml, Symbols/base_library.kicad_symdir/,
Footprints/7Sigma.pretty/, 3DModels/, .claude/commands/*.md.

Re-run at will while the YAML repo and the platform coexist; there is never a
merge. The last import ever run is the clean cutover.
"""
from __future__ import annotations

import hashlib
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .. import models as M
from ..config import settings
from ..db import Base, SessionLocal, engine
from ..routers.util import current_version
from ..util.sexpr import _norm, parse_sexpr, sanitize_symbol_text, walk_nodes
from . import material
from .generator import PRICE_KEY_TO_COL
from .mirror import rebuild_mirror
from .parse_cache import footprint_parsed, symbol_parsed

# Copied VERBATIM from kicad_lib/kicad/validator.py::_load_config (the config
# file it optionally reads does not exist in the repo, so these hardcoded
# defaults ARE today's canonical global ruleset).
VALIDATOR_GLOBAL_DEFAULTS = {
    "required_properties": ["Footprint", "ki_description"],
    "non_empty_properties": ["Footprint", "ki_description"],
    "property_patterns": {"Footprint": "^7Sigma:", "LCSC Part": "^C\\d+$"},
    "max_property_length": 200,
    "manufacturer_properties": [
        "Manufacturer 1",
        "Manufacturer Part Number 1",
        "Supplier 1",
        "Supplier Part Number 1",
    ],
    "footprint_dimensions": {
        "min_drill_diameter": 0.3,
        "min_via_size": 0.3,
        "min_via_drill": 0.3,
        "min_pad_size": 0.6,
        "thermal_via_warning_only": True,
    },
    "footprint_required": True,
}

IMPORT_STATE: dict = {"running": False, "stage": "", "report": None, "error": None, "started_at": None}
_lock = threading.Lock()

_LAYOUT_KEYS = ("position", "effects", "showName")


def _start(target) -> bool:
    """Kick off a background job (import or sync). Returns False if one is running.
    Both jobs share IMPORT_STATE and the lock, so they are mutually exclusive."""
    with _lock:
        if IMPORT_STATE["running"]:
            return False
        IMPORT_STATE.update(
            running=True, stage="starting", report=None, error=None,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
    threading.Thread(target=_run_safe, args=(target,), daemon=True).start()
    return True


def start_import() -> bool:
    """Kick off a full (DESTRUCTIVE) wipe-and-reload import. False if a job is running."""
    return _start(run_import)


def start_sync() -> bool:
    """Kick off a non-destructive YAML→proposals sync. False if a job is running.

    NO LONGER REACHABLE from the API (2026-08-24): `POST /api/import/sync`
    answers 410, because the drafts this files have no approval path since the
    Proposals view was removed. Kept for the `archive/yaml-library` branch.
    """
    return _start(run_sync)


def _run_safe(target) -> None:
    try:
        report = target()
        IMPORT_STATE.update(report=report, stage="done")
    except Exception:
        IMPORT_STATE.update(error=traceback.format_exc(), stage="failed")
    finally:
        IMPORT_STATE["running"] = False


def _stage(name: str) -> None:
    IMPORT_STATE["stage"] = name


def _symbol_entry_name(source_text: str, fallback: str) -> str:
    """The base-ref key is the symbol's entryName, not the filename."""
    try:
        tree = parse_sexpr(sanitize_symbol_text(source_text))
        for sym in walk_nodes(tree, "symbol"):
            if len(sym) > 1:
                return _norm(sym[1])
    except Exception:
        pass
    return fallback


def _read_libraries(repo: Path, warn) -> list[dict]:
    """Load Sources/*.yaml into library dicts, each tagged with `_lib_name`.
    Shared by run_import (destructive reload) and run_sync (diff → proposals)."""
    libraries: list[dict] = []
    for f in sorted((repo / "Sources").glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            warn(f"{f.name}: YAML parse error, library skipped — {e}")
            continue
        lib_name = data.get("library_name") or f.stem
        if lib_name != f.stem:
            warn(f"{f.name}: library_name {lib_name!r} != filename stem {f.stem!r}")
        data["_lib_name"] = lib_name
        libraries.append(data)
    return libraries


def run_import() -> dict:
    t0 = time.monotonic()
    repo = settings.repo_dir
    report: dict = {"warnings": []}
    warn = report["warnings"].append

    _stage("wiping database")
    # Skills SURVIVE imports (user-edited agent knowledge is not library data).
    keep_tables = {M.Skill.__table__, M.SkillVersion.__table__}
    # Component notes survive too — snapshot by component NAME and re-attach
    # after the reload (components get new ids).
    comment_snapshot: list[dict] = []
    try:
        snap_db = SessionLocal()
        for c, comp_name in (
            snap_db.query(M.ComponentComment, M.Component.name)
            .join(M.Component, M.Component.id == M.ComponentComment.component_id)
            .all()
        ):
            comment_snapshot.append({
                "component_name": comp_name, "author": c.author,
                "body": c.body, "created_at": c.created_at,
            })
        snap_db.close()
    except Exception:
        comment_snapshot = []  # fresh DB — nothing to preserve

    Base.metadata.drop_all(
        engine, tables=[t for t in Base.metadata.sorted_tables if t not in keep_tables]
    )
    Base.metadata.create_all(engine)

    db = SessionLocal()
    run = M.ImportRun(status="running")
    db.add(run)
    db.commit()

    try:
        # ------------------------------------------------------ sources yaml
        _stage("reading Sources/*.yaml")
        libraries = _read_libraries(repo, warn)
        report["libraries"] = len(libraries)

        _stage("creating categories")
        categories: dict[str, M.Category] = {}
        for pos, lib in enumerate(sorted(libraries, key=lambda d: d["_lib_name"])):
            cat = M.Category(name=lib["_lib_name"], parent_id=None, position=pos, defaults=lib.get("defaults"))
            db.add(cat)
            categories[lib["_lib_name"]] = cat
        db.commit()
        report["categories"] = len(categories)

        _stage("seeding rules")
        db.add(M.Rule(name="global defaults", scope="global", block=VALIDATOR_GLOBAL_DEFAULTS))
        rule_count = 1
        for lib in libraries:
            block = lib.get("validation_rules")
            if block:
                db.add(M.Rule(name=f"{lib['_lib_name']} rules", scope="library",
                              library_name=lib["_lib_name"], block=block))
                rule_count += 1
        db.commit()
        report["rules"] = rule_count

        _stage("seeding skills")
        skill_count = 0
        # Jaravis's skills are AUTHORED FOR THE AGENT, not the old terminal
        # workflow. They live in app/seed_skills/ (not the library repo): the
        # repo's .claude/commands/*.md and CLAUDE.md files describe a shell +
        # scripts pipeline Jaravis cannot run, so seeding from them would give
        # it non-actionable, misleading instructions. Operating knowledge (its
        # tools, the draft gate, what it can and cannot do) lives in the agent's
        # system prompt; these seeded skills carry only editable conventions.
        seed_dir = Path(__file__).resolve().parent.parent / "seed_skills"
        skill_sources: list[tuple[str, object]] = [
            (f.stem, f) for f in sorted(seed_dir.glob("*.md"))
        ]
        existing_skills = {s.name for s in db.query(M.Skill).all()}
        for skill_name, f in skill_sources:
            if skill_name in existing_skills:
                continue  # skills are preserved across imports — never overwrite
            skill = M.Skill(name=skill_name)
            db.add(skill)
            db.flush()
            sv = M.SkillVersion(skill_id=skill.id, version_no=1, content=f.read_text(encoding="utf-8"))
            db.add(sv)
            db.flush()
            skill.current_version_id = sv.id
            skill_count += 1
        db.commit()
        report["skills_seeded"] = skill_count
        report["skills_preserved"] = len(existing_skills)

        # ------------------------------------------------------ base symbols
        _stage("importing base symbols")
        symbols_by_name: dict[str, M.Symbol] = {}
        base_dir = repo / "Symbols" / "base_library.kicad_symdir"
        for f in sorted(base_dir.glob("*.kicad_sym")):
            text = f.read_text(encoding="utf-8")
            name = _symbol_entry_name(text, f.stem)
            if name != f.stem:
                warn(f"base symbol {f.name}: entryName {name!r} != filename stem")
            if name in symbols_by_name:
                warn(f"base symbol {name!r}: duplicate entryName, keeping first")
                continue
            try:
                parsed = symbol_parsed(text)
            except Exception as e:
                parsed = None
                warn(f"base symbol {name!r}: parse-cache failed — {e}")
            sym = M.Symbol(name=name)
            db.add(sym)
            db.flush()
            sv = M.SymbolVersion(symbol_id=sym.id, version_no=1, source_text=text, parsed=parsed,
                                 material_sha=material.material_sha("symbol", text))
            db.add(sv)
            db.flush()
            sym.current_version_id = sv.id
            symbols_by_name[name] = sym
        db.commit()
        report["symbols"] = len(symbols_by_name)

        # -------------------------------------------------------- footprints
        _stage("importing footprints")
        footprints_by_name: dict[str, M.Footprint] = {}
        pretty = repo / "Footprints" / "7Sigma.pretty"
        for f in sorted(pretty.glob("*.kicad_mod")):
            text = f.read_text(encoding="utf-8")
            try:
                parsed = footprint_parsed(text)
                models = parsed.get("models", [])
            except Exception as e:
                parsed, models = None, []
                warn(f"footprint {f.stem}: parse-cache failed — {e}")
            fp = M.Footprint(name=f.stem)
            db.add(fp)
            db.flush()
            fv = M.FootprintVersion(footprint_id=fp.id, version_no=1, source_text=text,
                                    parsed=parsed, models=models,
                                    material_sha=material.material_sha("footprint", text))
            db.add(fv)
            db.flush()
            fp.current_version_id = fv.id
            footprints_by_name[f.stem] = fp
        db.commit()
        report["footprints"] = len(footprints_by_name)

        # --------------------------------------------------------- 3D models
        _stage("importing 3D models")
        models_root = repo / "3DModels"
        model_count = 0
        if models_root.is_dir():
            for f in sorted(models_root.rglob("*")):
                if not f.is_file() or f.name == ".DS_Store":
                    continue
                data = f.read_bytes()
                db.add(M.Model3D(
                    rel_path=f.relative_to(models_root).as_posix(),
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                    data=data,
                ))
                model_count += 1
                if model_count % 50 == 0:
                    db.commit()  # bound memory
        db.commit()
        report["models3d"] = model_count

        # -------------------------------------------------------- components
        _stage("importing components")
        component_count = 0
        property_count = 0
        price_count = 0
        datasheet_count = 0
        seen_names: set[str] = set()
        for lib in libraries:
            cat = categories[lib["_lib_name"]]
            for comp in lib.get("components") or []:
                name = comp.get("name")
                if not name:
                    warn(f"{lib['_lib_name']}: component without name skipped")
                    continue
                if name in seen_names:
                    warn(f"{name}: duplicate component name (also in another library) — second skipped")
                    continue
                seen_names.add(name)

                base_name = comp.get("base_component") or ""
                base_sym = symbols_by_name.get(base_name)
                if base_sym is None:
                    warn(f"{name}: base component {base_name!r} not found in base library")

                # footprint pin from the Footprint property
                fp_version_id = None
                fp_prop = next(
                    (p for p in comp.get("properties") or [] if p.get("key") == "Footprint"), None
                )
                fp_value = (fp_prop or {}).get("value") or ""
                if isinstance(fp_value, str) and fp_value.startswith("7Sigma:"):
                    fp = footprints_by_name.get(fp_value.split(":", 1)[1])
                    if fp is None:
                        warn(f"{name}: footprint {fp_value!r} has no .kicad_mod file")
                    else:
                        fp_version_id = fp.current_version_id
                elif fp_value:
                    warn(f"{name}: footprint {fp_value!r} is not in the 7Sigma namespace")

                # Prices and the Datasheet link are NOT ordinary properties:
                # they move into their own tables (auto-managed data) and are
                # re-injected at generation time.
                price_vals: dict[str, str | None] = {}
                datasheet_url: str | None = None
                plain_props: list[dict] = []
                for prop in comp.get("properties") or []:
                    key = str(prop.get("key"))
                    raw = prop.get("value")
                    if key in PRICE_KEY_TO_COL:
                        price_vals[PRICE_KEY_TO_COL[key]] = None if raw is None else str(raw)
                    elif key == "Datasheet":
                        datasheet_url = None if raw is None else str(raw)
                    else:
                        plain_props.append(prop)

                component = M.Component(name=name)
                db.add(component)
                db.flush()
                cv = M.ComponentVersion(
                    component_id=component.id,
                    version_no=1,
                    base_component=base_name,
                    symbol_version_id=base_sym.current_version_id if base_sym else None,
                    footprint_version_id=fp_version_id,
                    category_id=cat.id,
                    removed_properties=comp.get("remove_properties") or None,
                )
                db.add(cv)
                db.flush()
                component.current_version_id = cv.id

                for pos, prop in enumerate(plain_props):
                    raw_value = prop.get("value")
                    effects = prop.get("effects") or {}
                    layout = {k: prop[k] for k in _LAYOUT_KEYS if k in prop} or None
                    db.add(M.ComponentProperty(
                        component_version_id=cv.id,
                        position=pos,
                        key=str(prop.get("key")),
                        value=None if raw_value is None else str(raw_value),
                        is_null=raw_value is None,
                        hide=effects.get("hide", True),
                        show_name=prop.get("showName", False),
                        layout=layout,
                    ))
                    property_count += 1
                if any(v is not None for v in price_vals.values()):
                    db.add(M.ComponentPrice(component_id=component.id, **price_vals))
                    price_count += 1
                if datasheet_url:
                    db.add(M.Datasheet(component_id=component.id, position=0,
                                       label="Datasheet", source_url=datasheet_url))
                    datasheet_count += 1
                component_count += 1
            db.commit()
        report["components"] = component_count
        report["properties"] = property_count
        report["prices"] = price_count
        report["datasheets"] = datasheet_count

        # ------------------------------------------------- restore user notes
        if comment_snapshot:
            _stage("restoring component notes")
            by_name = {c.name: c.id for c in db.query(M.Component).all()}
            restored = 0
            for snap in comment_snapshot:
                comp_id = by_name.get(snap["component_name"])
                if comp_id is None:
                    warn(f"note on {snap['component_name']!r} dropped — component no longer exists")
                    continue
                db.add(M.ComponentComment(
                    component_id=comp_id, author=snap["author"],
                    body=snap["body"], created_at=snap["created_at"],
                ))
                restored += 1
            db.commit()
            report["notes_restored"] = restored

        # ------------------------------------------------------------ mirror
        _stage("rebuilding file mirror")
        report["mirror"] = rebuild_mirror(db, settings)

        db.add(M.AuditLog(actor="user", action="import", entity_type="import_run",
                          entity_id=str(run.id), details={k: v for k, v in report.items() if k != "warnings"}))

        report["duration_s"] = round(time.monotonic() - t0, 1)
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        run.duration_s = report["duration_s"]
        run.report = report
        db.commit()
        return report
    except Exception:
        db.rollback()
        try:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.report = {"error": traceback.format_exc(), "partial": report}
            db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


# ============================================================ sync (proposals)
# Non-destructive alternative to run_import: diff each YAML component against the
# DB and create DRAFT proposals (the Jaravis pattern) for new / changed parts.
# Never wipes, never deletes, never publishes. Base symbols, footprints and
# categories are resolved from what is ALREADY in the DB; a component that
# references a missing one is reported and skipped (run a full import to add it).

SYNC_ACTOR = "import-sync"


@dataclass
class _Desired:
    """The component state built from one YAML entry (no side effects)."""
    name: str
    base_name: str
    base_missing: bool
    symbol_version_id: int | None
    footprint_name: str            # bare name (no "7Sigma:" prefix), "" if none
    footprint_missing: bool
    footprint_version_id: int | None
    category_id: int
    removed_properties: list | None
    plain_props: list[dict]        # {key, value(str|None), is_null, hide, show_name, layout}
    datasheet_url: str | None


def _build_desired(comp: dict, cat: M.Category, symbols_by_name: dict,
                   footprints_by_name: dict) -> _Desired | None:
    """Build a _Desired from a YAML component. Mirrors run_import's per-component
    construction (importer.py component loop) but returns data instead of rows,
    and flags unresolved base-symbol / footprint references for the caller.
    Keep this consistent with run_import if the YAML→component shape changes."""
    name = comp.get("name")
    if not name:
        return None

    base_name = comp.get("base_component") or ""
    base_sym = symbols_by_name.get(base_name)
    base_missing = bool(base_name) and base_sym is None

    fp_prop = next((p for p in comp.get("properties") or [] if p.get("key") == "Footprint"), None)
    fp_value = (fp_prop or {}).get("value") or ""
    footprint_name, footprint_missing, footprint_version_id = "", False, None
    if isinstance(fp_value, str) and fp_value.startswith("7Sigma:"):
        footprint_name = fp_value.split(":", 1)[1]
        fp = footprints_by_name.get(footprint_name)
        if fp is None:
            footprint_missing = True
        else:
            footprint_version_id = fp.current_version_id
    elif fp_value:
        footprint_name, footprint_missing = str(fp_value), True  # not in 7Sigma namespace

    # Prices and the Datasheet link are auto-managed and are NOT part of a
    # component version — strip them out exactly like run_import does.
    datasheet_url: str | None = None
    plain_props: list[dict] = []
    for prop in comp.get("properties") or []:
        key = str(prop.get("key"))
        raw = prop.get("value")
        if key in PRICE_KEY_TO_COL:
            continue
        if key == "Datasheet":
            datasheet_url = None if raw is None else str(raw)
            continue
        effects = prop.get("effects") or {}
        layout = {k: prop[k] for k in _LAYOUT_KEYS if k in prop} or None
        plain_props.append({
            "key": key,
            "value": None if raw is None else str(raw),
            "is_null": raw is None,
            "hide": effects.get("hide", True),
            "show_name": prop.get("showName", False),
            "layout": layout,
        })

    return _Desired(
        name=name,
        base_name=base_name,
        base_missing=base_missing,
        symbol_version_id=base_sym.current_version_id if base_sym else None,
        footprint_name=footprint_name,
        footprint_missing=footprint_missing,
        footprint_version_id=footprint_version_id,
        category_id=cat.id,
        removed_properties=comp.get("remove_properties") or None,
        plain_props=plain_props,
        datasheet_url=datasheet_url,
    )


def _desired_state(d: _Desired) -> tuple:
    """Comparable signature of a desired component (versioned data only)."""
    props = tuple((p["key"], None if p["is_null"] else p["value"]) for p in d.plain_props)
    removed = tuple(sorted(d.removed_properties or []))
    return (d.base_name or "", d.footprint_name or "", d.category_id, removed, props)


def _version_state(cv: M.ComponentVersion) -> tuple:
    """Comparable signature of an existing component version — same shape as
    _desired_state, so equality means 'no meaningful difference'."""
    fp_name = cv.footprint_version.footprint.name if cv.footprint_version else ""
    props = tuple(
        (p.key, None if p.is_null else p.value)
        for p in sorted(cv.properties, key=lambda x: x.position)
    )
    removed = tuple(sorted(cv.removed_properties or []))
    return (cv.base_component or "", fp_name or "", cv.category_id, removed, props)


def _add_proposal(db, comp: M.Component, d: _Desired, version_no: int, comment: str) -> M.ComponentVersion:
    """Create a DRAFT ComponentVersion + property rows + audit (Jaravis pattern).
    Leaves comp.current_version_id untouched — approval flips it live."""
    cv = M.ComponentVersion(
        component_id=comp.id,
        version_no=version_no,
        base_component=d.base_name,
        symbol_version_id=d.symbol_version_id,
        footprint_version_id=d.footprint_version_id,
        category_id=d.category_id,
        removed_properties=d.removed_properties,
        status="draft",
        created_by=SYNC_ACTOR,
        comment=comment,
    )
    db.add(cv)
    db.flush()
    for pos, p in enumerate(d.plain_props):
        db.add(M.ComponentProperty(
            component_version_id=cv.id, position=pos, key=p["key"],
            value=p["value"], is_null=p["is_null"], hide=p["hide"],
            show_name=p["show_name"], layout=p["layout"],
        ))
    db.add(M.AuditLog(actor=SYNC_ACTOR, action="proposal.create", entity_type="component_version",
                      entity_id=str(cv.id), details={"component": comp.name,
                                                     "new": comp.current_version_id is None}))
    return cv


def run_sync() -> dict:
    """Diff Sources/*.yaml against the DB and create draft proposals for new and
    changed components. Non-destructive and idempotent (re-running over unchanged
    YAML creates nothing). Blocking; run via start_sync()."""
    t0 = time.monotonic()
    repo = settings.repo_dir
    report: dict = {"mode": "sync", "warnings": []}
    warn = report["warnings"].append

    db = SessionLocal()
    run = M.ImportRun(status="running")
    db.add(run)
    db.commit()
    try:
        _stage("reading Sources/*.yaml")
        libraries = _read_libraries(repo, warn)

        _stage("indexing database")
        symbols_by_name = {s.name: s for s in db.query(M.Symbol)}
        footprints_by_name = {f.name: f for f in db.query(M.Footprint)}
        categories_by_name = {c.name: c for c in db.query(M.Category)}
        existing = {c.name: c for c in db.query(M.Component)}

        _stage("diffing components")
        new_props: list[str] = []
        edit_props: list[str] = []
        already_pending: list[str] = []
        skipped: list[dict] = []
        unchanged = 0
        yaml_names: set[str] = set()

        for lib in libraries:
            cat = categories_by_name.get(lib["_lib_name"])
            for comp_yaml in lib.get("components") or []:
                name = comp_yaml.get("name")
                if not name:
                    warn(f"{lib['_lib_name']}: component without name skipped")
                    continue
                if name in yaml_names:
                    warn(f"{name}: duplicate component name — second occurrence skipped")
                    continue
                yaml_names.add(name)

                if cat is None:
                    skipped.append({"name": name,
                                    "reason": f"category {lib['_lib_name']!r} not in DB — run a full import first"})
                    continue
                desired = _build_desired(comp_yaml, cat, symbols_by_name, footprints_by_name)
                if desired is None:
                    continue
                if desired.base_missing:
                    skipped.append({"name": name, "reason": f"base symbol {desired.base_name!r} not in DB"})
                    continue
                if desired.footprint_missing:
                    skipped.append({"name": name, "reason": f"footprint {desired.footprint_name!r} not in DB"})
                    continue

                dstate = _desired_state(desired)
                comp = existing.get(name)
                if comp is None:
                    comp = M.Component(name=name)  # current_version_id stays None until approved
                    db.add(comp)
                    db.flush()
                    _add_proposal(db, comp, desired, version_no=1, comment="New component from YAML sync")
                    if desired.datasheet_url:
                        db.add(M.Datasheet(component_id=comp.id, position=0, label="Datasheet",
                                           source_url=desired.datasheet_url))
                    new_props.append(name)
                    continue

                # Idempotency: skip if a matching draft is already pending.
                if any(_version_state(v) == dstate for v in comp.versions if v.status == "draft"):
                    already_pending.append(name)
                    continue
                cur = current_version(comp)
                if cur is not None and _version_state(cur) == dstate:
                    unchanged += 1
                    continue
                next_no = max((v.version_no for v in comp.versions), default=0) + 1
                _add_proposal(db, comp, desired, version_no=next_no,
                              comment="Differs from YAML" if cur is not None else "New component from YAML sync")
                (edit_props if cur is not None else new_props).append(name)

        db.commit()

        only_in_db = sorted(set(existing) - yaml_names)
        report.update(
            libraries=len(libraries),
            yaml_components=len(yaml_names),
            new_proposals=new_props,
            edit_proposals=edit_props,
            unchanged=unchanged,
            already_pending=already_pending,
            skipped=skipped,
            only_in_db=only_in_db,
            proposals_created=len(new_props) + len(edit_props),
        )
        db.add(M.AuditLog(actor="user", action="sync", entity_type="import_run", entity_id=str(run.id),
                          details={"new": len(new_props), "edits": len(edit_props),
                                   "unchanged": unchanged, "skipped": len(skipped)}))
        report["duration_s"] = round(time.monotonic() - t0, 1)
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        run.duration_s = report["duration_s"]
        run.report = report
        db.commit()
        return report
    except Exception:
        db.rollback()
        try:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.report = {"error": traceback.format_exc(), "partial": report}
            db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
