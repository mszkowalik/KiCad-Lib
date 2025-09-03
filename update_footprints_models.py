import os
import shutil
from kiutils.footprint import Footprint

EASYEDA2KICAD = "/Users/mateuszkowalik/Documents/KiCad/easyeda2kicad"
EASYEDA2KICAD_3DMODELS = os.path.join(EASYEDA2KICAD, "easyeda2kicad.3dshapes")
FOOTPRINTS_DIR = os.path.abspath("./Footprints/7Sigma.pretty")
TARGET_3DMODELS = os.path.abspath("./3DModels/easyeda2kicad.3dshapes")
SEVENSIGMA_MODEL_PREFIX = "${SEVENSIGMA_DIR}/3DModels/easyeda2kicad.3dshapes/"
EASYEDA_MODEL_PREFIX = "${EASYEDA2KICAD}/easyeda2kicad.3dshapes/"


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def process_footprint(filepath):
    fp = Footprint.from_file(filepath)
    changed = False
    for model in fp.models:
        # Always extract the filename
        model_filename = model.path.split("/")[-1]
        dst_model_path = os.path.join(TARGET_3DMODELS, model_filename)
        src_model_path = os.path.join(EASYEDA2KICAD_3DMODELS, model_filename)
        ensure_dir(TARGET_3DMODELS)
        # Copy model if missing in local dir, regardless of path prefix
        if not os.path.isfile(dst_model_path) and os.path.isfile(src_model_path):
            shutil.copy2(src_model_path, dst_model_path)
        # Update path if using EASYEDA or SEVENSIGMA prefix
        if model.path.startswith(EASYEDA_MODEL_PREFIX) or model.path.startswith(SEVENSIGMA_MODEL_PREFIX):
            if model.path != SEVENSIGMA_MODEL_PREFIX + model_filename:
                model.path = SEVENSIGMA_MODEL_PREFIX + model_filename
                changed = True
    if changed:
        fp.to_file(filepath)


def main():
    for fname in os.listdir(FOOTPRINTS_DIR):
        if fname.endswith(".kicad_mod"):
            process_footprint(os.path.join(FOOTPRINTS_DIR, fname))


if __name__ == "__main__":
    main()
