/** Miniature of a symbol / footprint render, with a large preview on hover.
 *
 *  The drawing itself goes through `GeometryPreview` like every other preview
 *  in the app, so the miniature and the popup sit on the same canvas as the
 *  full-size views. This file owns only the list-cell behaviour: lazy loading
 *  (a long list only fetches the visible rows) and the hover popup, which is
 *  position:fixed and placed from the cell's bounding box — an absolutely
 *  positioned one would be clipped by the table cells' single-line
 *  overflow:hidden clamp.
 */
import { useState } from "react";

import { templatePreviewUrl, type TemplateKind } from "../api";
import GeometryPreview from "./GeometryPreview";

const POP_W = 340;
const POP_H = 260;

export default function TemplateThumb({
  kind,
  id,
  name,
  versionId,
}: {
  kind: TemplateKind;
  id: number;
  name: string;
  /** Live version id — keys the URL so a republished drawing shows the NEW
   *  picture instead of whatever the browser already had. */
  versionId?: number | null;
}) {
  const [pop, setPop] = useState<{ x: number; y: number } | null>(null);
  const url = templatePreviewUrl(kind, id, versionId);

  return (
    <span
      className="tpl-thumb-wrap"
      onMouseEnter={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const x = Math.min(r.left, window.innerWidth - POP_W - 12);
        const y =
          r.bottom + POP_H + 12 > window.innerHeight ? r.top - POP_H - 6 : r.bottom + 6;
        setPop({ x: Math.max(x, 8), y: Math.max(y, 8) });
      }}
      onMouseLeave={() => setPop(null)}
    >
      <GeometryPreview
        src={url}
        alt={name}
        className="tpl-thumb"
        missingText="—"
        lazy
      />
      {pop ? (
        <GeometryPreview
          src={url}
          alt={name}
          className="tpl-thumb-pop"
          style={{ left: pop.x, top: pop.y }}
          missingText="no published version to preview"
          lazy
        />
      ) : null}
    </span>
  );
}
