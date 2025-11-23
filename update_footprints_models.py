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
            return s[len(prefix) :]
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


def _find_step_alternative(wrl_path: str, rel_subpath: str) -> Optional[str]:
    """
    Try to find a STEP format alternative for a WRL file by checking
    the same base name with .step or .stp extensions in known sources.
    """
    base_path = os.path.splitext(rel_subpath)[0]
    
    # Try both .step and .stp extensions
    for step_ext in ['.step', '.stp']:
        step_rel_path = base_path + step_ext
        
        # Check in EASYEDA2KICAD
        easyeda_candidate = os.path.join(EASYEDA2KICAD, step_rel_path)
        if os.path.isfile(easyeda_candidate):
            return easyeda_candidate
        
        # Check in USER_KICAD9_3DMODEL_DIR
        kicad_candidate = os.path.join(USER_KICAD9_3DMODEL_DIR, step_rel_path)
        if os.path.isfile(kicad_candidate):
            return kicad_candidate
    
    return None


def process_footprint(filepath: str):
    fp = Footprint.from_file(filepath)
    changed = False
    models_to_remove = []
    
    for idx, model in enumerate(fp.models):
        model_ext = os.path.splitext(model.path)[1].lower()
        
        # Handle WRL files - try to find STEP alternative
        if model_ext in ['.wrl', '.vrml']:
            rel_subpath = _extract_rel_3d_subpath(model.path)
            step_source = _find_step_alternative(model.path, rel_subpath)
            
            if step_source:
                # Found a STEP alternative
                step_ext = os.path.splitext(step_source)[1]
                step_rel_path = os.path.splitext(rel_subpath)[0] + step_ext
                dst_model_path = os.path.join(TARGET_3DMODELS_ROOT, step_rel_path)
                ensure_dir(os.path.dirname(dst_model_path))
                
                # Copy the STEP file if needed
                if not os.path.isfile(dst_model_path):
                    shutil.copy2(step_source, dst_model_path)
                    print(f"Info: Replaced WRL with STEP alternative: {os.path.basename(step_source)}")
                
                # Update model path to STEP format
                new_model_path = SEVENSIGMA_MODELS_BASE + _normalize_model_path(step_rel_path)
                model.path = new_model_path
                changed = True
            else:
                # No STEP alternative found, remove WRL
                print(f"Warning: No STEP alternative found for WRL model in '{filepath}': {model.path}")
                models_to_remove.append(idx)
                changed = True
            continue
        
        # Skip other unsupported formats
        if model_ext not in ['.step', '.stp']:
            print(f"Warning: Skipping unsupported 3D model format '{model_ext}' in '{filepath}': {model.path}")
            models_to_remove.append(idx)
            changed = True
            continue
        
        # Process STEP files normally
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
    
    # Remove unsupported models from the footprint
    for idx in reversed(models_to_remove):
        fp.models.pop(idx)

    if changed:
        fp.to_file(filepath)


def update_footprints_models():
    """Update 3D models for all footprints in the 7Sigma.pretty directory."""
    for fname in os.listdir(FOOTPRINTS_DIR):
        if fname.endswith(".kicad_mod"):
            process_footprint(os.path.join(FOOTPRINTS_DIR, fname))


def main():
    update_footprints_models()


if __name__ == "__main__":
    main()
