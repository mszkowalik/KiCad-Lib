import os
import shutil
from kiutils.footprint import Footprint
from typing import Optional

EASYEDA2KICAD = "/Users/mateuszkowalik/Documents/KiCad/easyeda2kicad"
USER_KICAD9_3DMODEL_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels"
TARGET_3DMODELS_ROOT = os.path.abspath("./3DModels")
SEVENSIGMA_MODELS_BASE = "${SEVENSIGMA_DIR}/3DModels/"
FOOTPRINTS_DIR = os.path.abspath("./Footprints/7Sigma.pretty")

SOURCE_BASE_MAP = {
    "${KICAD9_3DMODEL_DIR}/": USER_KICAD9_3DMODEL_DIR,
    "${EASYEDA2KICAD}/": EASYEDA2KICAD,
    SEVENSIGMA_MODELS_BASE: TARGET_3DMODELS_ROOT,
}


def ensure_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path)


def _normalize_model_path(p: str) -> str:
    return p.replace("\\", "/")


def _extract_rel_3d_subpath(model_path: str) -> str:
    """
    Return the relative path by stripping one of the known prefixes,
    preserving the '<Name>.3dshapes/...'.
    Falls back to detecting '.3dshapes/' or the basename.
    """
    s = _normalize_model_path(model_path)
    for prefix in SOURCE_BASE_MAP.keys():
        if s.startswith(prefix):
            return s[len(prefix):]
    # Fallback: keep from '<Name>.3dshapes/...'
    marker = ".3dshapes/"
    idx = s.find(marker)
    if idx != -1:
        start = s.rfind("/", 0, idx) + 1
        if start <= 0:
            start = 0
        return s[start:]
    # Fallback: strip leading ${VAR}/ if present
    if s.startswith("${"):
        r = s.find("}")
        if r != -1:
            tail = s[r + 1 :]
            return tail[1:] if tail.startswith("/") else tail
    return os.path.basename(s)


def _resolve_source_path(model_path: str, rel_subpath: str) -> Optional[str]:
    """
    Resolve the absolute source using the two universal sources or local cache.
    """
    s = _normalize_model_path(model_path)
    for prefix, base in SOURCE_BASE_MAP.items():
        if s.startswith(prefix):
            candidate = os.path.join(base, rel_subpath)
            if os.path.isfile(candidate):
                return candidate
    # Minimal fallback: try expanding env vars
    expanded = os.path.expandvars(s)
    if os.path.isfile(expanded):
        return expanded
    return None


def process_footprint(filepath: str):
    fp = Footprint.from_file(filepath)
    changed = False
    for model in fp.models:
        # Compute the relative path preserving the '.3dshapes/...' structure
        rel_subpath = _extract_rel_3d_subpath(model.path)
        dst_model_path = os.path.join(TARGET_3DMODELS_ROOT, rel_subpath)
        ensure_dir(os.path.dirname(dst_model_path))

        # Resolve the source file and copy if needed
        src_model_path = _resolve_source_path(model.path, rel_subpath)
        if src_model_path:
            if not os.path.isfile(dst_model_path):
                shutil.copy2(src_model_path, dst_model_path)
        else:
            print(f"Warning: Could not resolve source for model '{model.path}' in '{filepath}'")

        # Always rewrite to local ${SEVENSIGMA_DIR} base while preserving structure
        new_model_path = SEVENSIGMA_MODELS_BASE + _normalize_model_path(rel_subpath)
        if model.path != new_model_path:
            model.path = new_model_path
            changed = True

    if changed:
        fp.to_file(filepath)


def main():
    for fname in os.listdir(FOOTPRINTS_DIR):
        if fname.endswith(".kicad_mod"):
            process_footprint(os.path.join(FOOTPRINTS_DIR, fname))


if __name__ == "__main__":
    main()
