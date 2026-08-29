"""KiCad PCM (Plugin and Content Manager) repository built from the mirror.

Serves the whole 7Sigma library as installable KiCad *content packages*: the
user adds ONE repository URL in KiCad's Plugin and Content Manager and
installs the library from inside KiCad — no sync script.

Three packages, each versioned from ITS OWN content (so a symbols change
never re-flags the 1.4 GB models package):

  com.sevensigma.library   base symbols + footprints — the ~50 unique
                           drawings only; per-component symbols are NOT
                           shipped (HTTP-catalog parts reference their base
                           drawing), so adding components never changes it
  com.sevensigma.models3d  3dmodels/                (~1.4 GB)
  com.sevensigma.sync      IPC action plugin — a toolbar button in the PCB
                           AND schematic editors that re-fetches the two
                           library packages and refreshes the installed
                           copies in place (day-to-day updates without
                           opening the PCM dialog; source in pcm_plugin/)

PCM specifics this module encodes:
  * KiCad auto-registers installed libraries in the GLOBAL tables with a
    hardcoded ``PCM_`` nickname prefix (``PCM_Resistor``, ``PCM_7Sigma``) —
    so symbol footprint references inside the package are rewritten
    ``"7Sigma:`` → ``"PCM_7Sigma:`` to stay self-consistent.
  * Packages install under ``$KICAD10_3RD_PARTY/<kind>/<identifier with
    dots replaced by underscores>/`` — footprint 3D paths are rewritten from
    ``${SEVENSIGMA_DIR}/3DModels/`` to that location. Identifiers themselves
    must match PCM's regex (letters/digits/dots/dashes, NO underscores).
  * Library package versions derive from the mirror manifest's generated_at
    (``2026.719.1420``) at the time their OWN subtree last changed; a
    package whose files are untouched carries its previous version and zip
    forward, so PCM only offers updates for real changes.

Artifacts are cached under DATA_DIR/pcm; zips are keyed by their content
(subtree) hash, metadata by the manifest hash + builder revision.
packages.json is stored as exact bytes because repository.json must carry
its sha256.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from ..config import settings
from .simmodel import SIM_LIB_FILE

log = logging.getLogger(__name__)

THIRD_PARTY_VAR = "KICAD10_3RD_PARTY"  # matches the user's KiCad 10.x
SOURCE_NICKNAME = "7Sigma"  # the nickname used inside mirror files (repo convention)
LIB_ID = "com.sevensigma.library"
MODELS_ID = "com.sevensigma.models3d"
PLUGIN_ID = "com.sevensigma.sync"
PLUGIN_VERSION = "1.4.0"  # bump when the plugin source changes — PCM update detection
# ^ MANUAL, and PCM decides "update available" purely from this string. A new
# zip with the same version reaches nobody: the content hash changes, the
# download changes, and every installed copy stays on the old code. Shipping
# plugin source without bumping this is a silent no-op — it happened twice.
MODELS_INSTALL_DIR = MODELS_ID.replace(".", "_")
LIB_INSTALL_DIR = LIB_ID.replace(".", "_")
PCM_FP_PREFIX = "PCM_"  # KiCad's hardcoded auto-registration nickname prefix

# Where the generated SPICE library lands once the library package is
# installed. This is what every served/shipped `Sim.Library` field must say —
# the mirror's canonical `${SEVENSIGMA_DIR}/Symbols/...` value only resolves
# server-side. Same deliberate KiCad-10 pin as THIRD_PARTY_VAR above.
SIM_LIB_INSTALLED = f"${{{THIRD_PARTY_VAR}}}/symbols/{LIB_INSTALL_DIR}/{SIM_LIB_FILE}"
SCHEMA = "https://go.kicad.org/pcm/schemas/v1"
BUILDER_REV = 11  # bump when the package builder output changes for the same mirror
# ^ AND whenever anything in THIS FILE changes what a package advertises —
# PLUGIN_VERSION, a package name/description, a manifest field. `tag` hashes the
# mirror digest and the plugin FILE contents only, so a pcm.py-only edit leaves
# the tag unchanged, `meta-<tag>.json` still exists, and ensure_built returns the
# cached meta without ever reaching _resolve_package. A PLUGIN_VERSION bump on
# its own therefore reaches nobody: verified 2026-07-31, the repository kept
# advertising 1.0.4 through two deploys.

# A schematic drawn against the installed library stores the INSTALLED
# Sim.Library path — `${KICAD10_3RD_PARTY}/symbols/…` — because that is what
# the user's KiCad resolves. Server-side that variable does not exist, so
# every real project failed to netlist ("could not find base model
# 'sigma_diode'"). This gives the servers a directory shaped like a PCM
# install whose library folder IS the mirror, so both spellings of the path
# reach the same file and neither has to be rewritten.
SERVER_PCM_ROOT = "pcmroot"


def server_pcm_root() -> Path:
    """DATA_DIR/pcmroot, laid out so `${KICAD10_3RD_PARTY}` resolves here.

    ONLY the SPICE model file is exposed, as a relative symlink, so it stays
    current against a regenerated library. Do NOT link the mirror's Symbols
    FOLDER instead: that brings `7Sigma_Base.kicad_sym` along, and kicad-cli
    10.0.5 SEGFAULTS (rc 139, no message) when a `.kicad_sym` sits in the
    directory a PCM symbol library resolves to. Measured 2026-08-29 — the
    same schematic exports in 512 lines with the model file alone beside it,
    and dies the moment the symbol library is copied in next to it.

    Idempotent, and it repairs the folder-symlink layout an earlier build
    left behind.
    """
    root = settings.data_dir / SERVER_PCM_ROOT
    lib_dir = root / "symbols" / LIB_INSTALL_DIR
    link = lib_dir / SIM_LIB_FILE
    target = Path("..") / ".." / ".." / "mirror" / "Symbols" / SIM_LIB_FILE
    try:
        if lib_dir.is_symlink():  # the folder-wide link this replaced
            lib_dir.unlink()
        lib_dir.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() and Path(os.readlink(link)) == target:
            return root
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
    except OSError as e:  # a read-only volume, or a directory in the way
        log.warning("cannot prepare the server PCM root at %s: %s", link, e)
    return root


_PLUGIN_SRC = Path(__file__).parent / "pcm_plugin"

_lock = threading.Lock()


def _pcm_dir() -> Path:
    d = settings.data_dir / "pcm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mirror_state() -> tuple[str, str, list[dict]] | None:
    """(manifest sha256, date version, manifest file entries), or None."""
    manifest = settings.mirror_dir / "manifest.json"
    if not manifest.exists():
        return None
    raw = manifest.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw)
    try:
        dt = datetime.fromisoformat(data.get("generated_at", ""))
        version = f"{dt.year}.{dt.month}{dt.day:02d}.{dt.hour}{dt.minute:02d}"
    except (ValueError, TypeError):
        version = "0.0.1"
    return digest, version, data.get("files", [])


def _subtree_hash(entries: list[dict], prefixes: tuple[str, ...]) -> str:
    keys = sorted(
        f"{e['path']}:{e['sha256']}" for e in entries
        if any(e["path"].startswith(p) for p in prefixes)
    )
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


# Every zip member is stamped with this instead of "now", which is what
# `writestr(str, ...)` and `write(path, ...)` use by default. A package zip is
# named by its CONTENT hash and its sha256 is published in packages.json, so the
# same content must always produce the same bytes: rebuilding an unchanged
# package (a version bump, a pruned cache, a restart) otherwise emits a
# different file at the same URL, and any cache in front of the origin — the
# Cloudflare tunnel this deployment runs behind caches .zip by default — then
# hands PCM the old bytes with the new hash. That is the "Downloaded archive
# hash ... does not match repository entry" install failure. 1980-01-01 is the
# earliest timestamp the zip format can store.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _zip_entry(arcname: str) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(arcname, ZIP_EPOCH)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    return zi


def _zip_add(zf: zipfile.ZipFile, arcname: str, data: bytes) -> int:
    zf.writestr(_zip_entry(arcname), data)
    return len(data)


BASE_LIB_FILE = "7Sigma_Base.kicad_sym"


def _build_library_zip(path: Path) -> int:
    """The DEDUPLICATED geometry: only the base-symbol library (the ~50
    unique drawings every component derives from) + footprints, with
    self-consistent PCM references. Per-component symbols are deliberately
    NOT shipped — HTTP-catalog parts reference their base drawing, so adding
    components never changes this package. Returns uncompressed size."""
    size = 0
    models_prefix = f"${{{THIRD_PARTY_VAR}}}/3dmodels/{MODELS_INSTALL_DIR}/"
    base = settings.mirror_dir / "Symbols" / BASE_LIB_FILE
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        text = base.read_text(encoding="utf-8")
        text = text.replace(f'"{SOURCE_NICKNAME}:', f'"{PCM_FP_PREFIX}{SOURCE_NICKNAME}:')
        size += _zip_add(zf, f"symbols/{base.name}", text.encode("utf-8"))
        sim_lib = settings.mirror_dir / "Symbols" / SIM_LIB_FILE
        if sim_lib.exists():
            size += _zip_add(zf, f"symbols/{sim_lib.name}", sim_lib.read_bytes())
        pretty = settings.mirror_dir / "Footprints" / f"{SOURCE_NICKNAME}.pretty"
        for f in sorted(pretty.glob("*.kicad_mod")):
            text = f.read_text(encoding="utf-8")
            text = text.replace("${SEVENSIGMA_DIR}/3DModels/", models_prefix)
            size += _zip_add(zf, f"footprints/{pretty.name}/{f.name}", text.encode("utf-8"))
    return size


def _build_models_zip(path: Path) -> int:
    """3dmodels/ — the mirror's 3DModels tree verbatim. Level-1 deflate:
    STEP is text and compresses fine; the tree is 1.4 GB so speed matters."""
    size = 0
    root = settings.mirror_dir / "3DModels"
    # level 6: ~10-15% smaller than level 1 on STEP text; the build is
    # cached per content hash, so the extra CPU is paid once per change
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(root).as_posix()
            # NOT zf.write(f, ...): that stamps each member with the source
            # file's mtime, which a mirror regeneration changes even when the
            # model bytes do not — see ZIP_EPOCH. Largest model is ~15 MB, so
            # reading one at a time is fine.
            zf.writestr(_zip_entry(f"3dmodels/{rel}"), f.read_bytes(), compresslevel=6)
            size += f.stat().st_size
    return size


def _plugin_files(token: str = "") -> list[tuple[str, bytes]]:
    """The sync plugin's zip members: templates get the platform URL and the
    caller's API token baked in; icons ship verbatim. plugin.json must sit at
    the root of the package's plugins/ folder.

    `__THIRD_PARTY_VAR__` is the same constant the library zip's model-path
    rewrite uses, so push.py can spell an installed model path exactly as the
    packager would — the two can never drift apart across a KiCad release.

    `token` defaults to EMPTY on purpose, and the empty build is the one whose
    hash feeds the repository tag (see `ensure_built`). Personalisation must
    never move the tag — otherwise every user's first install would look like a
    library change and rebuild the 1.4 GB models package.

    A plugin built with no token still works: it falls back to `token.json`
    beside itself and, failing that, asks the user to paste one.
    """
    out: list[tuple[str, bytes]] = []
    for f in sorted(_PLUGIN_SRC.iterdir()):
        if not f.is_file():
            continue  # a __pycache__ left by running a plugin from the source tree
        if f.suffix == ".tmpl":
            body = (f.read_text(encoding="utf-8")
                    .replace("__BASE_URL__", settings.public_base_url)
                    .replace("__THIRD_PARTY_VAR__", THIRD_PARTY_VAR)
                    .replace("__TOKEN__", token))
            out.append((f"plugins/{f.name[:-5]}", body.encode("utf-8")))
        elif f.name == "icon-pcm.png":
            out.append(("resources/icon.png", f.read_bytes()))
        else:
            # icons, requirements.txt (MANDATORY — KiCad aborts the plugin's
            # Python env setup without it), kicad_canon.py (imported by both
            # entrypoints), any future static file
            out.append((f"plugins/{f.name}", f.read_bytes()))
    return out


def _build_plugin_zip(path: Path) -> int:
    size = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in _plugin_files():
            size += _zip_add(zf, arcname, data)
    return size



# How long a superseded artifact stays downloadable. PCM caches `packages.json`
# and only refreshes the repository when it is asked to, so a user can hold a
# record naming a tag the mirror has already moved past — and every component
# publish moves the mirror. Deleting the old zip immediately turned that stale
# record into a 404, whose 80-byte JSON error body KiCad hashes like any other
# download and reports as "Downloaded archive hash does not match repository
# entry" — an install failure that reads as corruption and is nothing of the
# kind (reported 2026-08-25 on library-fb1c4c239d2fr10.zip).
#
# Keeping the superseded bytes means a stale client downloads exactly what its
# record advertised, so the hash matches and the install succeeds. It is the
# same reasoning that already keeps this revision's personal plugin zips.
# The budget is in BYTES, not generations. A generation cap looks equivalent and
# is not: the library package rebuilds on every component publish, so "keep the
# last two" is minutes of cover on a busy day, while the retention has to span
# however long a user leaves a pending update sitting in PCM. Sized per package
# instead, the same 14 days costs ~400 library zips (0.5 MB each) or one extra
# 3D models zip (260 MB) — the small artifact gets the deep history it needs and
# the big one cannot fill the disk.
_GRACE_DAYS = 14
_GRACE_BYTES = 400 * 1024 * 1024


def _within_grace(f: Path) -> bool:
    """True for a superseded artifact still worth serving: recent enough that a
    client may still hold its record, and inside its package's size budget."""
    try:
        age = time.time() - f.stat().st_mtime
    except OSError:
        return False
    if age > _GRACE_DAYS * 86400:
        return False
    prefix = f.name.split("-")[0]
    newer_bytes = 0
    for sib in f.parent.glob(f"{prefix}-*"):
        try:
            st = sib.stat()
        except OSError:
            continue
        # Newer siblings claim the budget first, so retention drops the OLDEST
        # of a package once the budget is spent.
        if sib.is_file() and st.st_mtime > f.stat().st_mtime:
            newer_bytes += st.st_size
    return newer_bytes < _GRACE_BYTES


# Per-token plugin zips. Named apart from the shared artifacts so `ensure_built`
# can leave them alone while it prunes, and so they are obvious on disk.
PERSONAL_PREFIX = "psync-"


def personal_plugin(meta: dict, token: str) -> dict:
    """The plugin package entry for ONE user, with their token inside the zip.

    Returns the same shape `_resolve_package` produces (`zip`, `version`,
    `sha256`, `download_size`, `install_size`), so `_package_entry` consumes it
    unchanged. Built lazily and cached on disk, keyed by the plugin's content
    hash AND the token — a plugin source change or a rotated token both yield a
    new name, so a stale personal zip can never be served.

    The sha256 MUST be recomputed here: PCM verifies the download against the
    value in packages.json, and a personalised zip is a different file.
    """
    base = meta["packages"]["plugin"]
    if not token:
        return base
    out = _pcm_dir()
    key = hashlib.sha256(f"{base['subtree']}:{token}".encode()).hexdigest()[:16]
    # The plugin's content hash is IN THE NAME so `ensure_built` can tell a
    # current personal zip from one built for an older plugin, and keep the
    # first while pruning the second.
    zip_path = out / f"{PERSONAL_PREFIX}{base['subtree'][:12]}r{BUILDER_REV}-{key}.zip"
    if not zip_path.exists():
        with _lock:
            if not zip_path.exists():
                tmp = zip_path.with_suffix(".part")
                size = 0
                with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                    for arcname, data in _plugin_files(token):
                        size += _zip_add(zf, arcname, data)
                # Atomic publish: a half-written zip must never be downloadable,
                # because PCM would fail its sha256 check and blame the server.
                tmp.replace(zip_path)
                log.info(f"PCM: built personal plugin zip {zip_path.name} ({size} B installed)")
    with zipfile.ZipFile(zip_path) as zf:
        install_size = sum(i.file_size for i in zf.infolist())
    return {
        **base,
        "zip": zip_path.name,
        "sha256": _sha256_file(zip_path),
        "download_size": zip_path.stat().st_size,
        "install_size": install_size,
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _prev_packages(out: Path, current_meta: Path) -> dict:
    """Per-package state from the newest previous meta of the SAME builder
    revision — the carry-forward source for unchanged packages."""
    candidates = [
        p for p in out.glob(f"meta-*r{BUILDER_REV}.json") if p.name != current_meta.name
    ]
    if not candidates:
        return {}
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        return json.loads(newest.read_text()).get("packages", {})
    except (ValueError, OSError):
        return {}


def _resolve_package(out: Path, prev: dict, key: str, subtree: str, version: str,
                     zip_prefix: str, builder, pinned_version: bool = False) -> dict:
    """Reuse the previous zip when the package's content hash is unchanged;
    build a fresh zip (named by content hash) otherwise.

    The ZIP and the VERSION are decided separately, and conflating them cost
    the deployment real money twice:

    * Reusing the zip but keeping the old version made a manual PLUGIN_VERSION
      bump a silent no-op — PCM decides "update available" from the version
      string alone, so the bump has to reach the repository even though the
      plugin sources did not move. Hence `pinned_version`: the plugin's version
      is authored by hand and always wins.
    * Making the version part of the REUSE TEST re-encoded the 260 MB models
      package on EVERY mirror regeneration, because a content package's version
      comes from the mirror timestamp and that moves on every component publish.
      Same bytes, same URL, minutes of CPU — and, worse, PCM saw a new version
      string and offered every user a 260 MB update for an unchanged tree.

    So: a content package (`pinned_version=False`) whose subtree is unchanged
    carries its PREVIOUS version forward, which is what the module docstring
    promised all along — each package versioned from its own content.
    """
    p = prev.get(key)
    if p and p.get("subtree") == subtree and (out / p.get("zip", "")).exists():
        return {**p, "version": version} if pinned_version else p
    # The builder revision is part of the NAME, not just the meta tag: the zip
    # bytes for one content hash are fixed (ZIP_EPOCH), but a change to the
    # builder itself legitimately re-encodes them, and re-encoding under the old
    # URL is what a CDN in front of the origin cannot see. A new revision = a new
    # URL = a guaranteed cache miss.
    zip_path = out / f"{zip_prefix}-{subtree[:12]}r{BUILDER_REV}.zip"
    # Atomic publish, same reason as `personal_plugin`: this rewrites a name a
    # client may be downloading right now, and a half-written zip must never be
    # served — PCM would fail its sha256 check and blame the server.
    tmp = zip_path.with_suffix(".part")
    install_size = builder(tmp)
    tmp.replace(zip_path)
    return {
        "zip": zip_path.name,
        "version": version,
        "subtree": subtree,
        "sha256": _sha256_file(zip_path),
        "download_size": zip_path.stat().st_size,
        "install_size": install_size,
    }


def _packages_document(packages_meta: dict, token: str = "") -> dict:
    """The `packages.json` body. ONE definition, used by the shared build and
    by every personalised response — the package names, descriptions and types
    must never fork between them."""
    return {
        "packages": [
            _package_entry(
                LIB_ID, "7Sigma Library",
                "7Sigma base symbols and footprints (auto-registered as "
                "PCM_7Sigma_Base / PCM_7Sigma). Parts are picked from the live "
                "HTTP catalog, which references these drawings.",
                "library", packages_meta["library"], token=token,
            ),
            _package_entry(
                MODELS_ID, "7Sigma 3D Models",
                "STEP/WRL models referenced by the 7Sigma footprints.",
                "library", packages_meta["models"], token=token,
            ),
            _package_entry(
                PLUGIN_ID, "7Sigma Library Sync",
                "Two toolbar buttons in the PCB editor: Sync pulls library updates "
                "from the platform and applies them in place, Push sends footprints "
                "and symbols you edited locally back as draft proposals. Edit in the "
                "footprint or symbol editor, save, then push from the PCB editor.",
                "plugin", packages_meta["plugin"], kicad_version="9.0", token=token,
            ),
        ]
    }


def _with_token(url: str, token: str) -> str:
    """Append `?t=<token>`. KiCad's Plugin and Content Manager sends no headers
    of any kind, so a query parameter is the only credential it can carry."""
    return f"{url}?t={token}" if token else url


def _package_entry(identifier: str, name: str, description: str, ptype: str,
                   pmeta: dict, kicad_version: str = "8.0", token: str = "") -> dict:
    return {
        "$schema": f"{SCHEMA}/package",
        "name": name,
        "description": description,
        "description_full": f"{description} Served by the 7Sigma Project Management Platform.",
        "identifier": identifier,
        "type": ptype,
        "author": {"name": "7Sigma", "contact": {"web": settings.public_base_url}},
        # must be a value from the schema's License enum (SPDX ids +
        # open-source/unrestricted) — "unrestricted" = private/in-house
        "license": "unrestricted",
        "resources": {"homepage": settings.public_base_url},
        "versions": [
            {
                "version": pmeta["version"],
                "status": "stable",
                "kicad_version": kicad_version,
                "download_url": _with_token(
                    f"{settings.public_base_url}/api/kicad/pcm/{pmeta['zip']}", token),
                "download_sha256": pmeta["sha256"],
                "download_size": pmeta["download_size"],
                "install_size": pmeta["install_size"],
            }
        ],
    }


def ensure_built() -> dict | None:
    """Build (or reuse) the PCM artifacts for the current mirror + plugin
    source. Returns the meta dict or None when there is no mirror yet. Safe
    to call from any thread."""
    state = _mirror_state()
    if state is None:
        return None
    digest, version, entries = state
    out = _pcm_dir()
    # plugin content participates in the meta key so a plugin source change
    # rebuilds the repository even with an unchanged mirror
    plugin_hash = hashlib.sha256(
        b"".join(name.encode() + data for name, data in _plugin_files())
    ).hexdigest()
    tag = f"{hashlib.sha256(f'{digest}:{plugin_hash}'.encode()).hexdigest()[:12]}r{BUILDER_REV}"
    meta_path = out / f"meta-{tag}.json"
    with _lock:
        if meta_path.exists():
            return json.loads(meta_path.read_text())
        log.info(f"PCM: building packages for mirror {digest[:12]} (version {version})")
        prev = _prev_packages(out, meta_path)
        packages_meta = {
            "library": _resolve_package(
                out, prev, "library",
                # ONLY the base lib + footprints — per-component symbol libs
                # deliberately excluded so new components don't bump this
                _subtree_hash(entries, (f"Symbols/{BASE_LIB_FILE}", f"Symbols/{SIM_LIB_FILE}", "Footprints/")),
                version, "library", _build_library_zip,
            ),
            "models": _resolve_package(
                out, prev, "models",
                _subtree_hash(entries, ("3DModels/",)),
                version, "models3d", _build_models_zip,
            ),
            "plugin": _resolve_package(
                out, prev, "plugin", plugin_hash, PLUGIN_VERSION, "sync", _build_plugin_zip,
                pinned_version=True,
            ),
        }
        packages = _packages_document(packages_meta)
        packages_bytes = json.dumps(packages, indent=2).encode("utf-8")
        packages_file = out / f"packages-{tag}.json"
        packages_file.write_bytes(packages_bytes)
        repository = {
            "$schema": f"{SCHEMA}/repository",
            "name": "7Sigma Library Platform",
            "maintainer": {"name": "7Sigma", "contact": {"web": settings.public_base_url}},
            "packages": {
                "url": f"{settings.public_base_url}/api/kicad/pcm/{packages_file.name}",
                "sha256": hashlib.sha256(packages_bytes).hexdigest(),
                "update_time_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "update_timestamp": int(datetime.utcnow().timestamp()),
            },
        }
        meta = {
            "hash": digest,
            "version": version,
            "packages": packages_meta,
            "repository": repository,
            "packages_file": packages_file.name,
            "files": [p["zip"] for p in packages_meta.values()] + [packages_file.name],
        }
        meta_path.write_text(json.dumps(meta, indent=2))
        # prune artifacts of older states (carried-forward zips are in `files`)
        keep = set(meta["files"]) | {meta_path.name}
        # Personal plugin zips are not in `files` — one per user, built lazily.
        # Keep the ones built from THIS plugin revision: deleting them made the
        # next repository.json rebuild them, and before ZIP_EPOCH that produced
        # different bytes and a different sha256 for an already-advertised URL.
        personal = f"{PERSONAL_PREFIX}{packages_meta['plugin']['subtree'][:12]}r{BUILDER_REV}-"
        for f in out.iterdir():
            if f.name in keep or f.name.startswith(personal) or _within_grace(f):
                continue
            f.unlink(missing_ok=True)
        sizes = {k: f"{(out / p['zip']).stat().st_size >> 20} MB" for k, p in packages_meta.items()}
        log.info(f"PCM: packages ready {sizes}")
        return meta


def meta_for_packages_file(filename: str) -> dict | None:
    """The build a `packages-<tag>.json` request belongs to — including a tag
    the mirror has already moved past.

    PCM caches `repository.json` and only re-reads it when asked, so a client
    can come back for an index whose tag is several publishes old. Serving that
    request from the CURRENT build is wrong twice over: the hash the client's
    repository record published belongs to the old document, and the on-disk
    shared copy carries no token on its download URLs, so every zip fetch that
    follows is unauthenticated. Rebuilding the old document from its own meta
    keeps a stale record working end to end — the retention grace keeps the
    zips it names, and the personal plugin zip it names, on disk.
    """
    if not (filename.startswith("packages-") and filename.endswith(".json")):
        return None
    tag = filename[len("packages-"):-len(".json")]
    if "/" in tag or "." in tag:
        return None
    meta_file = _pcm_dir() / f"meta-{tag}.json"
    if not meta_file.is_file():
        return None
    try:
        return json.loads(meta_file.read_text())
    except (ValueError, OSError):
        return None


def artifact_path(filename: str) -> Path | None:
    """A previously built artifact by exact name (zip / packages json)."""
    p = _pcm_dir() / filename
    return p if (p.exists() and p.is_file() and "/" not in filename) else None


# ------------------------------------------------------- personal repository
# One user, one repository URL. Pasting
#   {public_base_url}/api/kicad/pcm/repository.json?t=<their token>
# into KiCad's Plugin and Content Manager installs the library, the 3D models
# and a sync plugin that already carries that token — so the user pastes once
# and never types a credential into a dialog.
#
# Everything below is generated PER REQUEST rather than stored, because the
# three documents are chained by hash: personalising a download_url changes
# packages.json, which changes the sha256 that repository.json publishes. They
# are small, and generation is deterministic for a given (meta, token), so the
# hash a client verifies always matches the bytes it later fetches.

def personal_packages(meta: dict, token: str) -> bytes:
    """`packages.json` for one user: their token on every download URL, and
    their own plugin zip (different bytes, therefore a different sha256)."""
    packages_meta = dict(meta["packages"])
    packages_meta["plugin"] = personal_plugin(meta, token)
    return json.dumps(_packages_document(packages_meta, token), indent=2).encode("utf-8")


def personal_repository(meta: dict, token: str) -> dict:
    """`repository.json` for one user, pointing at their `packages.json` and
    publishing its hash."""
    if not token:
        return meta["repository"]
    body = personal_packages(meta, token)
    repository = json.loads(json.dumps(meta["repository"]))  # deep copy
    repository["packages"]["url"] = _with_token(
        f"{settings.public_base_url}/api/kicad/pcm/{meta['packages_file']}", token)
    repository["packages"]["sha256"] = hashlib.sha256(body).hexdigest()
    return repository


_warmed = False


def start_background_build(delay_s: float = 30.0) -> None:
    """Warm the PCM artifacts shortly after startup so the first PCM
    request doesn't wait for the 1.4 GB models zip."""
    global _warmed
    if _warmed:
        return
    _warmed = True

    def build():
        try:
            ensure_built()
        except Exception as e:
            log.warning(f"PCM warm build failed: {e}")

    t = threading.Timer(delay_s, build)
    t.daemon = True
    t.start()
