"""
Centralized path configuration for the KiCad Library Management System.

All directory paths and external tool locations used across the project
are defined here. Update these values to match your local environment.
"""

import os

# ---------------------------------------------------------------------------
# Project directories (relative to project root)
# ---------------------------------------------------------------------------
SOURCES_DIR = os.path.abspath("./Sources")
SYMBOLS_DIR = os.path.abspath("./Symbols")
FOOTPRINTS_DIR = os.path.abspath("./Footprints/7Sigma.pretty")
TARGET_3DMODELS_ROOT = os.path.abspath("./3DModels")
BASE_LIB_DIR = os.path.join(SYMBOLS_DIR, "base_library.kicad_symdir")

# ---------------------------------------------------------------------------
# External tool / environment paths
# ---------------------------------------------------------------------------
USER_KICAD9_3DMODEL_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels"

# ---------------------------------------------------------------------------
# KiCad environment variable prefixes used in footprint model paths
# ---------------------------------------------------------------------------
SEVENSIGMA_MODELS_BASE = "${SEVENSIGMA_DIR}/3DModels/"

SOURCE_BASE_MAP = {
    "${KICAD9_3DMODEL_DIR}/": USER_KICAD9_3DMODEL_DIR,
    SEVENSIGMA_MODELS_BASE: TARGET_3DMODELS_ROOT,
}

# ---------------------------------------------------------------------------
# API URLs
# ---------------------------------------------------------------------------
LCSC_API_URL = "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={}"


# ---------------------------------------------------------------------------
# JLCPCB OpenAPI credentials (JLC-first pricing; LCSC is the fallback)
# ---------------------------------------------------------------------------
def _platform_env() -> dict[str, str]:
    """KEY=VALUE pairs from platform/.env, so the pipeline shares the
    platform deployment's JLC credentials without duplicating them."""
    out: dict[str, str] = {}
    try:
        with open(os.path.abspath("./platform/.env"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                out[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return out


_PLATFORM_ENV = _platform_env()


def _jlc_setting(key: str, default: str = "") -> str:
    return os.environ.get(key) or _PLATFORM_ENV.get(key) or default


JLC_APP_ID = _jlc_setting("JLC_APP_ID")
JLC_ACCESS_KEY = _jlc_setting("JLC_ACCESS_KEY")
JLC_SECRET_KEY = _jlc_setting("JLC_SECRET_KEY")
JLC_ENDPOINT = _jlc_setting("JLC_ENDPOINT", "https://open.jlcpcb.com")

# ---------------------------------------------------------------------------
# Cache files
# ---------------------------------------------------------------------------
LCSC_METADATA_CACHE = os.path.abspath("./.lcsc_cache.json")
