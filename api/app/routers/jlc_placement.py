"""JLC pick-and-place correction of a component (decision 0110).

One route, for an agent over MCP: measure the rotation and position offset
that turn our footprint into JLC's land for the same part. It writes nothing;
the result is a proposal that is written with `propose_component_edit` as the
`FT Rotation Offset` / `FT Position Offset` properties.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import jlc_placement as svc
from .util import current_version, props_dict

router = APIRouter(prefix="/api", tags=["jlc-placement"])


class MeasureIn(BaseModel):
    jlc_footprint: str = Field(
        ..., min_length=20,
        description="JLC's land for this part's LCSC code as .kicad_mod text "
                    "(easyeda2kicad --footprint writes one).")


@router.post("/components/{comp_id}/jlc-placement/measure",
             openapi_extra={"x-agent-tool": "measure_jlc_placement"})
def measure(comp_id: int, body: MeasureIn, db: Session = Depends(get_db)):
    """Propose the `FT Rotation Offset` and `FT Position Offset` of a part.

    Pads are matched BY NUMBER between the component's footprint and JLC's
    land. The answer is a proposal: confirm it in JLC's placement preview
    before relying on it (the EasyEDA land has missed JLC's real orientation
    on U.FL C411563 and DSHP08TS C3293147). Writes nothing.
    """
    comp = db.get(M.Component, comp_id)
    cv = current_version(comp) if comp is not None else None
    if cv is None:
        raise HTTPException(404, "component not found")
    if cv.footprint_version_id is None:
        raise HTTPException(409, "the component has no footprint")
    fv = db.get(M.FootprintVersion, cv.footprint_version_id)
    props = props_dict(cv)
    try:
        result = svc.measure(fv.source_text, body.jlc_footprint)
    except Exception as e:  # unparsable input is the caller's
        raise HTTPException(422, f"could not read a footprint: {e}") from e
    result["component"] = comp.name
    result["lcsc"] = props.get("LCSC Part") or ""
    result["current"] = {svc.ROTATION_KEY: props.get(svc.ROTATION_KEY),
                         svc.POSITION_KEY: props.get(svc.POSITION_KEY)}
    return result
