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
    SIM_ONLY_CATEGORY,
    BaseSymbolProvider,
    build_component_symbol,
    build_library_text,
    footprint_display_names,
    footprint_name_props,
    injected_props,
    load_symbol_lib_from_text,
    property_row_to_dict,
    set_build_exclusions,
    set_exclude_from_sim,
    sim_props,
    version_prop,
)
from . import material, memory
from .simmodel import SIM_LIB_FILE, link_material_sha, model_material_sha, sim_pins_value

# Lifecycle states hidden from every KiCad-facing surface (generated symbol
# libraries and the HTTP catalog): the part stays fully visible on the
# platform, KiCad's chooser just stops offering it (user decision 2026-08-23).
HIDDEN_LIFECYCLE = ("deprecated", "obsolete")


def top_level_of(category: M.Category) -> M.Category:
    node = category
    while node.parent is not None:
        node = node.parent
    return node


# --- incremental-rebuild caches -------------------------------------------
# Both exist because the mirror is refreshed after EVERY approval, while
# almost nothing in it actually changed. They are in-process only: a restart
# just costs one full rebuild, and correctness never depends on them (each is
# guarded by a check against the real filesystem/DB state).

# mirror-relative path -> (mtime_ns, size, sha256). Lets write_manifest skip
# re-hashing the ~1.4 GB of 3D models on every component approval.
_MANIFEST_HASHES: dict[str, tuple[int, int, str]] = {}

# Fingerprint of the base-symbol set the last written 7Sigma_Base.kicad_sym
# was built from, plus how many symbols went into it.
_BASE_LIB_STATE: tuple[str, int] | None = None


def _base_symbol_fingerprint(db: Session) -> str:
    """Cheap signature of every base symbol's live version. Changes only when a
    symbol proposal is approved (or a symbol is added/removed) — which is the
    only time 7Sigma_Base.kicad_sym can differ."""
    rows = db.execute(
        select(M.Symbol.id, M.Symbol.current_version_id).order_by(M.Symbol.id)
    ).all()
    # The base library also carries exclude_from_sim, which set_exclude_from_sim
    # DERIVES from the link set — so adding or removing a link changes this file
    # even when no symbol version moved. Without the links in the fingerprint the
    # flag lags until some unrelated symbol happens to be edited.
    links = db.execute(
        select(M.SymbolSimLink.symbol_id).order_by(M.SymbolSimLink.symbol_id)
    ).all()
    # It also carries in_bom / on_board, which set_build_exclusions DERIVES from
    # which categories a base symbol's components sit in. Moving the last
    # component out of Simulation changes this file with no symbol version
    # touched, so the category of every published component belongs here too.
    cats = db.execute(
        select(M.ComponentVersion.id, M.ComponentVersion.category_id)
        .order_by(M.ComponentVersion.id)
    ).all()
    return hashlib.sha256(repr((rows, links, cats)).encode()).hexdigest()


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
        if comp.lifecycle_state in HIDDEN_LIFECYCLE:
            continue  # deprecated/obsolete — platform-only, never offered to KiCad
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

    fp_display = footprint_display_names(db)
    # Footprint version numbers for the injected "7S Version" field — id and
    # number only, never the rows (a FootprintVersion row drags a .kicad_mod).
    fp_ver_no = dict(db.execute(
        select(M.FootprintVersion.id, M.FootprintVersion.version_no)
    ).all())
    sim_links = resolve_sim_links(db, warnings)
    # Base symbols drawn ONLY by simulation-only components. A template
    # shared with a real part stays on the board — the per-component
    # category libraries and the HTTP record carry the exact answer, and
    # this file is only the fallback drawing.
    tops_by_symbol: dict[int, set[str]] = {}
    for comp, cv in [pair for pairs in by_top.values() for pair in pairs]:
        if cv.symbol_version is not None:
            tops_by_symbol.setdefault(cv.symbol_version.symbol_id, set()).add(
                top_level_of(cv.category).name
            )
    sim_only_symbols = {
        sid for sid, tops in tops_by_symbol.items() if tops == {SIM_ONLY_CATEGORY}
    }
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
                own = [property_row_to_dict(p) for p in cv.properties]
                fp_ref = next((p.value for p in cv.properties if p.key == "Footprint"), "")
                # Footprint_Name first — see footprint_name_props() on why order matters.
                # sim_props also prepends: a component's own Sim.* rows come
                # later in the list and therefore win (per-part override).
                props = (
                    footprint_name_props(fp_ref, fp_display)
                    + sim_props(sim_links.get(sv.symbol_id))
                    + own
                    + injected_props(sheets.get(comp.id))
                    + version_prop(cv.version_no, sv.version_no,
                                   fp_ver_no.get(cv.footprint_version_id))
                )
                built = build_component_symbol(
                    template, comp.name, props, cv.removed_properties, warnings
                )
                set_exclude_from_sim(built, sv.symbol_id in sim_links)
                set_build_exclusions(built, top_name)
                syms.append(built)
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
    # component never changes it, only a new base drawing does. So it is
    # rebuilt only when the base-symbol set actually moved (or the file is
    # gone, e.g. after rebuild_mirror wiped the tree): re-parsing all ~140
    # base symbols and re-serializing ~1 MB on every component approval was
    # pure waste.
    global _BASE_LIB_STATE
    base_lib_path = symbols_dir / "7Sigma_Base.kicad_sym"
    fingerprint = _base_symbol_fingerprint(db)
    cached = _BASE_LIB_STATE
    if cached is not None and cached[0] == fingerprint and base_lib_path.exists():
        base_symbol_count = cached[1]
    else:
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
                    set_exclude_from_sim(entry, sym.id in sim_links)
                    set_build_exclusions(
                        entry,
                        SIM_ONLY_CATEGORY if sym.id in sim_only_symbols else "",
                    )
                    base_syms.append(entry)
            except Exception as e:
                warnings.append(f"base symbol {sym.name}: mirror generation failed — {e}")
        base_lib_path.write_text(build_library_text(meta_lib, base_syms), encoding="utf-8")
        base_symbol_count = len(base_syms)
        # Only trust the fingerprint once the file is safely on disk.
        _BASE_LIB_STATE = (fingerprint, base_symbol_count)

    sim_model_count = write_sim_lib(db, settings)

    return {"symbol_libs": symbol_lib_count, "components_in_libs": component_count,
            "base_symbols": base_symbol_count, "sim_models": sim_model_count,
            "warnings": warnings}


# (link id, symbol version id, model version id, stored shas, pin_map) ->
# resolved entry. In-process and advisory like the caches above: the key pins
# every input the resolution reads — the version rows AND the link's own
# stored fields, hashed directly rather than via updated_at, so even a direct
# DB write that skips the service layer cannot produce a stale hit. Exists
# because the HTTP catalog also resolves links, once per chooser request, and
# re-parsing sixty symbol sources per request is waste.
_SIM_LINK_CACHE: dict[tuple, dict] = {}


def resolve_sim_links(db: Session, warnings: list[str]) -> dict[int, dict]:
    """`{symbol_id: {"model", "sim_pins", "stale"}}` for every SymbolSimLink.
    `stale` is "" for a healthy link, else the joined reasons (truthy).

    Staleness is decided here, once per mirror write, by recomputing both
    narrow fingerprints and comparing them with the ones stamped on the link
    when its map was authored. A stale link still resolves (the UI needs to
    show it) but `sim_props` emits nothing for it — a map whose symbol pins
    or model ports moved since authoring must not reach a netlist. Each stale
    link costs one warning, so it surfaces on every publish until fixed.
    """
    out: dict[int, dict] = {}
    live_keys: set[tuple] = set()
    links = db.execute(
        select(M.SymbolSimLink).options(
            selectinload(M.SymbolSimLink.symbol).selectinload(M.Symbol.versions),
            selectinload(M.SymbolSimLink.sim_model).selectinload(M.SimModel.versions),
        )
    ).scalars().all()
    for link in links:
        sym = link.symbol
        model = link.sim_model
        sv = next((v for v in sym.versions if v.id == sym.current_version_id), None)
        mv = next((v for v in model.versions if v.id == model.current_version_id), None)
        if sv is None or mv is None or mv.status != "published":
            continue
        key = (link.id, sv.id, mv.id, link.symbol_material_sha,
               link.model_material_sha, json.dumps(link.pin_map, sort_keys=True))
        live_keys.add(key)
        cached = _SIM_LINK_CACHE.get(key)
        if cached is not None:
            out[sym.id] = cached
            if cached["stale"]:
                warnings.append(f"sim link {sym.name} -> {model.name}: {cached['stale']} — Sim fields withheld")
            continue
        stale_reasons = []
        try:
            pins = material.symbol_material(sv.source_text)["pins"]
            if link_material_sha(pins) != link.symbol_material_sha:
                stale_reasons.append("symbol pins changed since the map was authored")
        except Exception:  # noqa: BLE001 — unparseable symbol == cannot vouch for the map
            stale_reasons.append("symbol source is unparseable")
        if model_material_sha(mv.source_text) != link.model_material_sha:
            stale_reasons.append("model ports changed since the map was authored")
        if stale_reasons:
            warnings.append(f"sim link {sym.name} -> {model.name}: {'; '.join(stale_reasons)} — Sim fields withheld")
        entry = {
            "model": model.name,
            "sim_pins": sim_pins_value(link.pin_map),
            # the joined reasons, so a cache hit can re-emit the warning
            "stale": "; ".join(stale_reasons),
        }
        _SIM_LINK_CACHE[key] = entry
        out[sym.id] = entry
    for gone in _SIM_LINK_CACHE.keys() - live_keys:
        del _SIM_LINK_CACHE[gone]
    return out


def write_sim_lib(db: Session, settings: Settings) -> int:
    """Emit Symbols/7Sigma_sim.sp — every published model in one file.

    Primitives first, then part wrappers, each group sorted by name, so the
    output is byte-stable for an unchanged model set (the manifest and the
    PCM tag both hash it). SPICE does not require definition-before-use, so
    no dependency ordering is needed. The file is small (tens of models, a
    few KB) — regenerating it on every mirror write costs nothing worth a
    cache.
    """
    # populate_existing: the mirror states what the DATABASE holds, so it must
    # not read a stale collection left in the identity map by a writer earlier
    # in the same session. Without it a just-published version is invisible
    # here, because expire_on_commit is False and selectinload will not
    # overwrite a relationship that is already loaded on an identity-mapped
    # object.
    rows = (
        db.execute(
            select(M.SimModel)
            .options(selectinload(M.SimModel.versions))
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    chunks: list[str] = [
        "* 7Sigma simulation library — GENERATED from the platform, do not edit.",
        "* Simplified functional models: logic, rail and pin behaviour only.",
        "* NOT electrically accurate. Parameters come from each component's",
        "* Sim.Params field; defaults below are placeholder-grade.",
    ]
    count = 0
    for model in sorted(rows, key=lambda m: (m.kind != "primitive", m.name)):
        mv = next((v for v in model.versions if v.id == model.current_version_id), None)
        if mv is None or mv.status != "published":
            continue
        chunks.append("")
        chunks.append(mv.source_text.strip())
        count += 1
    symbols_dir = settings.mirror_dir / "Symbols"
    symbols_dir.mkdir(parents=True, exist_ok=True)
    (symbols_dir / SIM_LIB_FILE).write_text("\n".join(chunks) + "\n", encoding="utf-8")
    return count


def _sha256_file(path) -> str:
    """SHA-256 of a file, read in 1 MB blocks.

    NOT `read_bytes()`. The mirror is 4977 files and 1.4 GB, the largest 13.7
    MB, and on a cold cache write_manifest hashes all of them in one pass —
    that is 1.4 GB pushed through the allocator in multi-MB chunks, which is
    what leaves 64 MB malloc heaps behind (see services/memory.py). Blocked
    reads keep the peak at one buffer and reuse it."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_manifest(settings: Settings) -> int:
    """Rewrite manifest.json — the hash index the PCM builder and sync clients
    key off. Hashing is memoised on (mtime_ns, size): a component approval
    changes a couple of .kicad_sym files, but the tree also holds ~1.4 GB of
    3D models that would otherwise be re-hashed every single time. The stat()
    still happens per file, so any content change is picked up; only the
    read+SHA-256 is skipped. The manifest's own format is unchanged."""
    mirror = settings.mirror_dir
    files = []
    seen: set[str] = set()
    for path in sorted(p for p in mirror.rglob("*") if p.is_file() and p.name != "manifest.json"):
        rel = path.relative_to(mirror).as_posix()
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
        cached = _MANIFEST_HASHES.get(rel)
        if cached is not None and cached[:2] == stamp:
            digest = cached[2]
        else:
            digest = _sha256_file(path)
            _MANIFEST_HASHES[rel] = (*stamp, digest)
        seen.add(rel)
        files.append({"path": rel, "sha256": digest, "size": st.st_size})
    # Drop cache entries for files that no longer exist, so the dict tracks the
    # mirror rather than growing forever across rebuilds.
    for stale in _MANIFEST_HASHES.keys() - seen:
        del _MANIFEST_HASHES[stale]
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "files": files,
    }
    (mirror / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    memory.trim()
    return len(files)


def update_mirror_symbols(db: Session, settings: Settings, top_names: set[str]) -> dict:
    """Incremental mirror update after a component edit: rewrite only the
    affected top-level symbol libraries, then refresh the manifest."""
    result = write_symbol_libs(db, settings, only_tops=top_names)
    result["manifest_files"] = write_manifest(settings)
    return result


def update_mirror_footprint(db: Session, settings: Settings, name: str) -> dict:
    """Incremental mirror update after a footprint publish: rewrite the one
    .kicad_mod from the footprint's current published version, then refresh
    the manifest (which the PCM builder and sync clients key off)."""
    fp = db.execute(select(M.Footprint).where(M.Footprint.name == name)).scalar_one_or_none()
    fv = None
    if fp is not None:
        fv = next((v for v in fp.versions if v.id == fp.current_version_id), None)
    if fv is None or fv.status != "published":
        return {"footprints": 0, "manifest_files": write_manifest(settings),
                "warnings": [f"footprint {name}: no published version — mirror unchanged"]}
    pretty = settings.mirror_dir / "Footprints" / "7Sigma.pretty"
    pretty.mkdir(parents=True, exist_ok=True)
    (pretty / f"{fp.name}.kicad_mod").write_text(fv.source_text, encoding="utf-8")
    return {"footprints": 1, "manifest_files": write_manifest(settings), "warnings": []}


def update_mirror_model3d(settings: Settings, m: M.Model3D) -> dict:
    """Incremental mirror update after a 3D model upload: write the one file
    (models3d carries no version/draft gate, so a successful upload is live
    immediately), then refresh the manifest."""
    target = settings.mirror_dir / "3DModels" / m.rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(m.data)
    return {"models3d": 1, "manifest_files": write_manifest(settings)}


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
