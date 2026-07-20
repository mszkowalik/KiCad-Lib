"""File mirror: a published-state, filesystem view of the DB.

Layout (served read-only at /files):
    mirror/
      manifest.json
      Symbols/<TopCategory>.kicad_sym
      Footprints/7Sigma.pretty/<name>.kicad_mod
      3DModels/<rel_path>

Rebuilt from the DB after import and after every publish; disposable by design.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import Settings
from .generator import (
    BaseSymbolProvider,
    build_component_symbol,
    build_library_text,
    injected_props,
    load_symbol_lib_from_text,
    property_row_to_dict,
)


def top_level_of(category: M.Category) -> M.Category:
    node = category
    while node.parent is not None:
        node = node.parent
    return node


def write_symbol_libs(db: Session, settings: Settings, only_tops: set[str] | None = None) -> dict:
    """Generate Symbols/<TopCategory>.kicad_sym files. When `only_tops` is
    given, only those libraries are rewritten (incremental update on edit)."""
    warnings: list[str] = []
    symbol_lib_count = 0
    component_count = 0

    sample_sv = db.execute(select(M.SymbolVersion).limit(1)).scalar_one_or_none()
    if sample_sv is None:
        return {"symbol_libs": 0, "components_in_libs": 0, "warnings": warnings}

    meta_lib = load_symbol_lib_from_text(sample_sv.source_text)
    provider = BaseSymbolProvider()

    sheets: dict[int, list] = {}
    for ds in db.execute(
        select(M.Datasheet).where(M.Datasheet.archived.is_(False)).order_by(M.Datasheet.position)
    ).scalars():
        sheets.setdefault(ds.component_id, []).append(ds)

    components = (
        db.execute(
            select(M.Component).options(selectinload(M.Component.versions))
        ).scalars().all()
    )
    by_top: dict[str, list] = {}
    for comp in components:
        if not comp.in_library:
            continue  # BOM-only part — never emitted into KiCad libraries
        cv = next((v for v in comp.versions if v.id == comp.current_version_id), None)
        if cv is None or cv.status != "published":
            continue
        top = top_level_of(cv.category)
        by_top.setdefault(top.name, []).append((comp, cv))

    # Every top-level category gets a file, even if currently empty
    top_cats = db.execute(select(M.Category).where(M.Category.parent_id.is_(None))).scalars().all()
    for cat in top_cats:
        by_top.setdefault(cat.name, [])

    if only_tops is not None:
        by_top = {k: v for k, v in by_top.items() if k in only_tops}

    symbols_dir = settings.mirror_dir / "Symbols"
    symbols_dir.mkdir(parents=True, exist_ok=True)
    for top_name in sorted(by_top):
        syms = []
        for comp, cv in sorted(by_top[top_name], key=lambda t: t[0].name):
            sv = cv.symbol_version
            if sv is None:
                warnings.append(f"{comp.name}: no pinned symbol version — skipped in mirror")
                continue
            try:
                template = provider.get(
                    cv.base_component, sv.source_text, cache_key=f"{cv.base_component}@{sv.id}"
                )
                props = [property_row_to_dict(p) for p in cv.properties] + injected_props(
                    sheets.get(comp.id)
                )
                syms.append(
                    build_component_symbol(template, comp.name, props, cv.removed_properties, warnings)
                )
                component_count += 1
            except Exception as e:
                warnings.append(f"{comp.name}: generation failed — {e}")
        (symbols_dir / f"{top_name}.kicad_sym").write_text(
            build_library_text(meta_lib, syms), encoding="utf-8"
        )
        symbol_lib_count += 1

    # Deduplicated base-symbol library: the ~50 unique graphical templates
    # every component derives from. This is what the PCM library package
    # ships and what HTTP-catalog parts reference (symbolIdStr) — adding a
    # component never changes it, only a new base drawing does.
    base_syms = []
    for sym in db.execute(select(M.Symbol).order_by(M.Symbol.name)).scalars():
        sv = next((v for v in sym.versions if v.id == sym.current_version_id), None)
        if sv is None:
            continue
        try:
            lib = load_symbol_lib_from_text(sv.source_text)
            entry = next((s for s in lib.symbols if s.entryName == sym.name), None)
            if entry is None and lib.symbols:
                entry = lib.symbols[0]
            if entry is not None:
                base_syms.append(entry)
        except Exception as e:
            warnings.append(f"base symbol {sym.name}: mirror generation failed — {e}")
    (symbols_dir / "7Sigma_Base.kicad_sym").write_text(
        build_library_text(meta_lib, base_syms), encoding="utf-8"
    )

    return {"symbol_libs": symbol_lib_count, "components_in_libs": component_count,
            "base_symbols": len(base_syms), "warnings": warnings}


def write_manifest(settings: Settings) -> int:
    mirror = settings.mirror_dir
    files = []
    for path in sorted(p for p in mirror.rglob("*") if p.is_file() and p.name != "manifest.json"):
        rel = path.relative_to(mirror).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({"path": rel, "sha256": digest, "size": path.stat().st_size})
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "files": files,
    }
    (mirror / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return len(files)


def update_mirror_symbols(db: Session, settings: Settings, top_names: set[str]) -> dict:
    """Incremental mirror update after a component edit: rewrite only the
    affected top-level symbol libraries, then refresh the manifest."""
    result = write_symbol_libs(db, settings, only_tops=top_names)
    result["manifest_files"] = write_manifest(settings)
    return result


def rebuild_mirror(db: Session, settings: Settings) -> dict:
    settings.ensure_dirs()
    mirror = settings.mirror_dir
    for child in mirror.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()

    # --- symbols: one .kicad_sym per top-level category --------------------
    sym_result = write_symbol_libs(db, settings)
    warnings = sym_result["warnings"]
    symbol_lib_count = sym_result["symbol_libs"]
    component_count = sym_result["components_in_libs"]

    # --- footprints ---------------------------------------------------------
    pretty = mirror / "Footprints" / "7Sigma.pretty"
    pretty.mkdir(parents=True, exist_ok=True)
    footprint_count = 0
    for fp in db.execute(select(M.Footprint)).scalars():
        fv = next((v for v in fp.versions if v.id == fp.current_version_id), None)
        if fv is None or fv.status != "published":
            continue
        (pretty / f"{fp.name}.kicad_mod").write_text(fv.source_text, encoding="utf-8")
        footprint_count += 1

    # --- 3D models ----------------------------------------------------------
    models_dir = mirror / "3DModels"
    model_count = 0
    for m in db.execute(select(M.Model3D).execution_options(yield_per=20)).scalars():
        target = models_dir / m.rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(m.data)
        model_count += 1

    # --- manifest ------------------------------------------------------------
    write_manifest(settings)

    return {
        "symbol_libs": symbol_lib_count,
        "components_in_libs": component_count,
        "footprints": footprint_count,
        "models3d": model_count,
        "warnings": warnings,
    }
