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
BASE_LIB_PATH = os.path.join(SYMBOLS_DIR, "base_library.kicad_sym")

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
