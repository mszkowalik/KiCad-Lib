"""Simulation sources, sheet trees, overlay geometry and scenario runs.

Two kinds of source feed the same pipeline (docs/simulator/design.md §3.3):

  snapshot  a board's schematic inside an ingested commit — the files are
            already on the shared volume, so the render container sees them
  upload    a `.kicad_sch` (with its sub-sheets and any model files) the user
            dropped in the browser, unpacked under data/sim_uploads/<id>/

Nothing here knows about SPICE beyond calling the ops: kicad-cli flattens the
hierarchy and ngspice runs it, both inside project_ops.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid as uuidlib
from pathlib import Path

from ..config import settings
from . import gitrepo, pcm, project_render, sch_write, sim_geom, sim_scenario

UPLOAD_ROOT = "sim_uploads"
# What an upload may contain. Schematics and the model files a design keeps
# next to them — never a script, an archive or a symlink.
UPLOAD_SUFFIXES = frozenset({".kicad_sch", ".kicad_pro", ".lib", ".sp", ".cir", ".mod", ".sub", ".txt"})
MAX_UPLOAD_FILES = 60
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
# The editor document kept beside a saved sketch, so it can be reopened.
SKETCH_FILE = "sketch.json"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._ +-]*$")

# The colour theme kicad-cli renders with. `render/themes/` carries the same
# file byte-identical (the workflow's guard job checks it) because the browser
# draws schematics itself now, and a second palette would put the simulator
# and the project's schematic tab back into two colour schemes.
THEME_DIR = Path(__file__).with_name("themes")

# KiCad names a few colours only in the theme it inherits from. These are the
# stock values, used when a theme leaves a key out.
_THEME_FALLBACK = {
    "background": "rgb(255, 255, 255)", "wire": "rgb(0, 150, 0)",
    "bus": "rgb(0, 0, 132)", "junction": "rgb(0, 150, 0)",
    "component_outline": "rgb(132, 0, 0)", "component_body": "rgb(255, 255, 194)",
    "pin": "rgb(132, 0, 0)", "pin_name": "rgb(0, 100, 100)",
    "pin_number": "rgb(169, 0, 0)", "reference": "rgb(0, 100, 100)",
    "value": "rgb(0, 100, 100)", "fields": "rgb(132, 0, 132)",
    "label_local": "rgb(0, 0, 0)", "label_global": "rgb(132, 0, 0)",
    "label_hier": "rgb(132, 0, 132)", "no_connect": "rgb(0, 0, 132)",
    "note": "rgb(0, 0, 194)", "sheet": "rgb(132, 0, 0)",
    "sheet_background": "rgba(255, 255, 255, 0.0)", "sheet_name": "rgb(0, 100, 100)",
    "sheet_filename": "rgb(132, 0, 132)", "sheet_label": "rgb(0, 100, 100)",
    "sheet_fields": "rgb(132, 0, 132)", "dnp_marker": "rgb(220, 9, 13)",
    "excluded_from_sim": "rgb(194, 194, 194)", "hidden": "rgb(94, 194, 194)",
    "erc_warning": "rgb(255, 208, 66)", "erc_error": "rgb(230, 9, 13)",
}


def schematic_theme() -> dict:
    """The palette the browser's schematic renderer draws with.

    Every colour is already a CSS `rgb()`/`rgba()` string in the theme file,
    so nothing is converted here — a value that reaches the browser unchanged
    cannot be rounded differently from the one kicad-cli used.
    """
    name = settings.symbol_theme or "Skyline-7S"
    colours = dict(_THEME_FALLBACK)
    path = THEME_DIR / f"{name}.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
        for key, value in (data.get("schematic") or {}).items():
            if isinstance(value, str):
                colours[key] = value
    else:
        name = ""
    return {"name": name, "schematic": colours}


class SimSourceError(RuntimeError):
    pass


class SimSource:
    """Where a simulation's files are, and whether its artifacts are cacheable.

    `root_rel` is relative to DATA_DIR, which is `/data` in both containers —
    the render container reads exactly that path.
    """

    def __init__(self, kind: str, label: str, root_rel: str, cache_prefix: str = ""):
        self.kind = kind
        self.label = label
        self.root_rel = root_rel
        self.cache_prefix = cache_prefix

    @property
    def root_abs(self) -> Path:
        return (settings.data_dir / self.root_rel).resolve()

    def rel_of(self, abs_path: str | Path) -> str:
        """An absolute file inside this source -> its DATA_DIR-relative path."""
        p = Path(abs_path).resolve()
        root = settings.data_dir.resolve()
        try:
            return p.relative_to(root).as_posix()
        except ValueError as e:
            raise SimSourceError(f"file escapes the data root: {p}") from e


# ------------------------------------------------------------------ sources

def snapshot_source(snapshot, board: dict) -> SimSource:
    """A board's schematic inside an ingested commit. Re-materialises the
    checkout if a prune removed it, exactly like the render endpoints do."""
    if not board.get("sch"):
        raise SimSourceError("this board has no schematic file")
    try:
        gitrepo.materialize(snapshot.project_id, snapshot.sha)
    except (OSError, gitrepo.GitError) as e:
        # No git mirror on this server (a fresh machine, or a prune that took
        # the bare clone with it). The fix is a project fetch, so say that
        # instead of failing as an internal error.
        raise SimSourceError(
            f"the commit is not available on this server — fetch project "
            f"{snapshot.project_id} first ({e})"
        ) from e
    rel = project_render.rel_checkout(snapshot.project_id, snapshot.sha, board["sch"])
    return SimSource(
        kind="snapshot",
        label=f"{board.get('name', '')} @ {snapshot.sha[:8]}",
        root_rel=rel,
        # Immutable by commit sha, so anything derived from it is cacheable
        # for good — the same rule the board and schematic renders follow.
        cache_prefix=project_render.render_key(
            snapshot.project_id, snapshot.sha, board.get("name", "board"), "sim"),
    )


def upload_source(upload_id: str) -> SimSource:
    folder = settings.data_dir / UPLOAD_ROOT / upload_id
    meta_file = folder / "source.json"
    if not meta_file.exists():
        raise SimSourceError("upload not found — it may have expired")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    return SimSource(
        kind="upload",
        label=meta.get("label", upload_id),
        root_rel=f"{UPLOAD_ROOT}/{upload_id}/{meta['root']}",
    )


def store_upload(files: list[tuple[str, bytes]], root_name: str = "") -> dict:
    """Unpack an uploaded sheet set. Returns {id, root, files, label}.

    Files keep their names because a `(sheet)` node references its child by
    file name, and a relative `Sim.Library` resolves next to the sheet that
    names it. Sub-directories are flattened out: one level is all a dropped
    selection can express, and a path component is how a traversal starts.
    """
    if not files:
        raise SimSourceError("no files uploaded")
    if len(files) > MAX_UPLOAD_FILES:
        raise SimSourceError(f"too many files (limit {MAX_UPLOAD_FILES})")
    total = sum(len(data) for _, data in files)
    if total > MAX_UPLOAD_BYTES:
        raise SimSourceError(f"upload is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    cleaned: list[tuple[str, bytes]] = []
    for name, data in files:
        base = Path(name).name
        if not _SAFE_NAME.match(base) or Path(base).suffix.lower() not in UPLOAD_SUFFIXES:
            raise SimSourceError(f"file type not accepted here: {base}")
        cleaned.append((base, data))

    sheets = [n for n, _ in cleaned if n.lower().endswith(".kicad_sch")]
    if not sheets:
        raise SimSourceError("the upload contains no .kicad_sch file")
    root = Path(root_name).name if root_name else ""
    if root and root not in sheets:
        raise SimSourceError(f"root sheet {root} is not among the uploaded files")
    if not root:
        root = _guess_root(cleaned, sheets)

    prune_uploads()
    upload_id = uuidlib.uuid4().hex
    folder = settings.data_dir / UPLOAD_ROOT / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in cleaned:
        (folder / name).write_bytes(data)
    meta = {"id": upload_id, "root": root, "files": [n for n, _ in cleaned],
            "label": root, "created": time.time()}
    (folder / "source.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def store_sketch(doc: dict, upload_id: str = "") -> dict:
    """Save a schematic drawn in the browser, and make it runnable.

    It becomes an ordinary upload — the same source kind a `.kicad_sch` dropped
    from KiCad becomes — so drawing a circuit and simulating it need no second
    pipeline. The document is kept beside the file so the editor can reopen
    what it drew; the FILE stays the artefact, because that is the thing KiCad
    opens.

    `upload_id` rewrites a sketch IN PLACE. The editor saves on every pause in
    typing, and a new directory per keystroke would fill the disk and change
    the address bar under the user. Safe because an upload is not cached:
    `upload_source` sets no cache prefix, so the next netlist reads the file
    that is there now.
    """
    name = re.sub(r"[^A-Za-z0-9._+-]+", "_", str(doc.get("name") or "sketch")).strip("._-")
    name = name[:48] or "sketch"
    doc = {**doc, "name": name}
    try:
        sch = sch_write.document_to_sch(doc)
        pro = sch_write.document_to_pro(doc)
    except sch_write.WriteError as e:
        raise SimSourceError(str(e)) from e

    folder = settings.data_dir / UPLOAD_ROOT / Path(upload_id).name if upload_id else None
    if folder is not None and (folder / SKETCH_FILE).is_file():
        # Only ever a sketch: rewriting an upload that came from KiCad would
        # replace a file the user gave us with one we generated.
        for stale in list(folder.glob("*.kicad_sch")) + list(folder.glob("*.kicad_pro")):
            stale.unlink()
        (folder / f"{name}.kicad_sch").write_text(sch, encoding="utf-8")
        (folder / f"{name}.kicad_pro").write_text(pro, encoding="utf-8")
        meta = {"id": folder.name, "root": f"{name}.kicad_sch",
                "files": [f"{name}.kicad_sch", f"{name}.kicad_pro"],
                "label": f"{name}.kicad_sch", "created": time.time()}
        (folder / "source.json").write_text(json.dumps(meta), encoding="utf-8")
    else:
        meta = store_upload(
            [(f"{name}.kicad_sch", sch.encode()), (f"{name}.kicad_pro", pro.encode())],
            root_name=f"{name}.kicad_sch",
        )
        folder = settings.data_dir / UPLOAD_ROOT / meta["id"]
    (folder / SKETCH_FILE).write_text(json.dumps(doc), encoding="utf-8")
    return {**meta, "sch": sch}


def read_sketch(upload_id: str) -> dict | None:
    """The document a sketch was drawn from, if this upload is one."""
    folder = settings.data_dir / UPLOAD_ROOT / Path(upload_id).name
    path = folder / SKETCH_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _guess_root(files: list[tuple[str, bytes]], sheets: list[str]) -> str:
    """The sheet nobody references as a sub-sheet is the root."""
    referenced: set[str] = set()
    for name, data in files:
        if not name.lower().endswith(".kicad_sch"):
            continue
        text = data.decode("utf-8", "replace")
        referenced |= {Path(m).name for m in re.findall(r'"Sheetfile"\s+"([^"]+)"', text)}
    roots = [s for s in sheets if s not in referenced]
    if len(roots) == 1:
        return roots[0]
    if not roots:
        raise SimSourceError("every uploaded sheet is referenced by another — no root sheet")
    raise SimSourceError(
        "more than one sheet could be the root (" + ", ".join(sorted(roots)) + ") — name one")


def prune_uploads() -> int:
    """Drop uploads past their TTL. Called on every new upload, so a machine
    that simulates keeps itself tidy without a scheduler."""
    root = settings.data_dir / UPLOAD_ROOT
    if not root.is_dir():
        return 0
    cutoff = time.time() - settings.sim_upload_ttl_h * 3600
    removed = 0
    for folder in root.iterdir():
        meta = folder / "source.json"
        try:
            created = json.loads(meta.read_text(encoding="utf-8")).get("created", 0)
        except (OSError, ValueError):
            created = folder.stat().st_mtime if folder.exists() else 0
        if created < cutoff:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return removed


def snapshot_projects(snapshot) -> list[dict]:
    """The snapshot's KiCad projects, marked for whether they simulate.

    A repository holds the design AND a simulation project per block it
    exercises — EVSE_20_CTRL carries CP_sim, DIN_sim, DOUT_sim, RESET_sim,
    SAFETY_sim and TEMP_sim beside the board. Each is a real `.kicad_pro`, so
    the ingest already discovers them as boards; what it cannot say is which
    of them is a harness. A root sheet carrying SPICE directive text is.
    """
    out: list[dict] = []
    for board in snapshot.boards or []:
        entry = {"board": board.get("name", ""), "simulation": False, "directives": 0,
                 "has_schematic": bool(board.get("sch"))}
        if board.get("sch"):
            try:
                rel = project_render.rel_checkout(snapshot.project_id, snapshot.sha, board["sch"])
                text = (settings.data_dir / rel).read_text(encoding="utf-8")
                entry["directives"] = len(_DIRECTIVE_RE.findall(text))
                entry["simulation"] = entry["directives"] > 0
            except OSError:
                # The checkout is not materialised yet; the name still hints.
                entry["simulation"] = entry["board"].lower().endswith("_sim")
        out.append(entry)
    return out


# ------------------------------------------------------------------- sheets

# Counted rather than parsed: picking a default sheet must not cost a full
# geometry pass over every sheet in a hierarchy.
_PLACED_RE = re.compile(r"\(lib_id ")
_WIRE_RE = re.compile(r"\(wire\b")
_DIRECTIVE_RE = re.compile(r'\(text\s+"\\?\.(tran|ac|dc|op|noise|control|param|include|lib|four)\b',
                           re.IGNORECASE)


def sheets(src: SimSource) -> list[dict]:
    """Every sheet INSTANCE in the hierarchy, root first. `file` is replaced
    by a DATA_DIR-relative path — an absolute server path is nothing the
    browser should ever see.

    Each entry carries how much is DRAWN on it. The root of a simulation
    project is usually a page of SPICE text with one sub-sheet box on it, so
    "the first sheet" and "the deepest sheet" both pick the wrong thing to
    show; the counts let the client open the sheet under test.
    """
    out = []
    for entry in sim_geom.sheet_tree(src.root_abs):
        item = dict(entry)
        try:
            item["rel"] = src.rel_of(entry["file"])
        except SimSourceError:
            item["rel"] = ""
            item["error"] = "sub-sheet lies outside the source folder"
        text = ""
        if item["rel"]:
            try:
                text = (settings.data_dir / item["rel"]).read_text(encoding="utf-8")
            except OSError as e:
                item["error"] = f"cannot read the sheet: {e}"
        item["symbols"] = len(_PLACED_RE.findall(text))
        item["wires"] = len(_WIRE_RE.findall(text))
        item["directives"] = len(_DIRECTIVE_RE.findall(text))
        item.pop("file", None)
        out.append(item)
    return out


def _net_prefix(src: SimSource, entry: dict) -> str:
    """What KiCad puts in front of a local label on this sheet instance.

    The chain of sheet NAMES from the root down to this instance: the TEMP
    sub-sheet gives `/TEMP`, and a sheet inside it `/TEMP/<its name>`. Empty
    at the root, where a label is already the whole net name.
    """
    if entry.get("depth", 0) == 0:
        return ""
    chain = [
        other["name"] for other in sorted(sheets(src), key=lambda e: e["depth"])
        if other["depth"] > 0 and _is_ancestor_or_self(other["path"], entry["path"])
    ]
    return "".join(f"/{name}" for name in chain)


def _find_sheet(src: SimSource, instance_path: str = "") -> dict:
    tree = sheets(src)
    if not instance_path:
        return tree[0]
    for entry in tree:
        if entry["path"] == instance_path:
            return entry
    raise SimSourceError(f"no such sheet instance: {instance_path}")


def scenarios(src: SimSource) -> dict:
    """What the ROOT sheet offers to run.

    The root, not the sheet on screen: a simulation is a project, and the
    harness that drives it lives on the root beside the block it exercises
    (`docs/simulator/design.md` §3.4). Netlisting anything else drops the
    harness.
    """
    entry = _find_sheet(src, "")
    if entry.get("error"):
        raise SimSourceError(entry["error"])
    path = (settings.data_dir / entry["rel"]).resolve()
    geom = sim_geom.sheet_geometry(path.read_text(encoding="utf-8"))
    out = sim_scenario.classify(geom["texts"])
    out["analysis_forms"] = sim_scenario.ANALYSIS_FORMS
    return out


# ------------------------------------------------------------------ netlist

def netlist_xml(src: SimSource, root_rel: str = "") -> dict:
    """kicadxml for the whole hierarchy, parsed. Cached for snapshots, which
    are immutable; recomputed for uploads, which are not."""
    rel = root_rel or src.root_rel
    if src.cache_prefix:
        key = f"{src.cache_prefix}/{Path(rel).name}.netlist.xml"
        data, _ = project_render.cached_op(key, "sch_kicadxml", rel)
    else:
        data, _ = project_render.run_project_op("sch_kicadxml", rel)
    return sim_geom.parse_kicadxml(data)


def netlist_spice(src: SimSource, root_rel: str = "") -> str:
    rel = root_rel or src.root_rel
    data, _ = project_render.run_project_op("sch_spice", rel)
    return data.decode("utf-8", "replace")


def _is_ancestor_or_self(candidate: str, path: str) -> bool:
    """Instance-path prefix test on whole uuid segments."""
    a, b = candidate.strip("/").split("/"), path.strip("/").split("/")
    return len(a) <= len(b) and a == b[: len(a)]


# ----------------------------------------------------------------- geometry

def geometry(src: SimSource, instance_path: str = "") -> dict:
    """Overlay geometry for one sheet instance, with net names attached."""
    entry = _find_sheet(src, instance_path)
    if entry.get("error"):
        raise SimSourceError(entry["error"])
    path = (settings.data_dir / entry["rel"]).resolve()
    geom = sim_geom.sheet_geometry(
        path.read_text(encoding="utf-8"), entry["path"], net_prefix=_net_prefix(src, entry),
    )
    geom = sim_geom.assign_nets(geom, netlist_xml(src))
    geom["sheet"] = {k: entry[k] for k in ("name", "path", "depth", "page") if k in entry}
    geom["source"] = {"kind": src.kind, "label": src.label}
    return geom


# --------------------------------------------------------------------- live

def live_target(src: SimSource) -> str:
    """DATA_DIR-relative root sheet, which is what a live session simulates.

    Same rule as a batch run: the whole project, harness included. A live
    session differs only in never ending."""
    pcm.server_pcm_root()  # the netlist inside the render container needs it
    return src.root_rel


# ---------------------------------------------------------------------- run

def run(src: SimSource, *, control: str | None = None, analysis: str = "",
        timeout: int = 0) -> bytes:
    """One batch scenario run -> the 7SIM payload the browser plots.

    ALWAYS the source's root sheet, whatever sheet the viewer is looking at.
    A simulation is a PROJECT: `SAFETY_sim.kicad_pro` holds a root sheet that
    includes the real `SAFETY.kicad_sch` and adds the harness — supplies,
    stimulus, loads, the `.control` verdict block — as SPICE text beside it.
    Netlisting the sheet under test on its own drops all of that and ngspice
    answers "incomplete or empty netlist", which is exactly what it did
    before this rule existed. Simulating a block in isolation is not a mode:
    it is a reason to make a `_sim` project for it.
    """
    data, _ = project_render.run_project_op(
        "sim_run", src.root_rel, control=control, analysis=analysis,
        timeout=timeout or settings.sim_timeout_s,
    )
    return data
