/** Miniature of a symbol / footprint render, with a large preview on hover.
 *
 *  The small image loads lazily (a long list only fetches the visible rows)
 *  and the server caches renders by content hash, so repeat visits are disk
 *  reads. The hover preview is position:fixed and placed from the cell's
 *  bounding box — an absolutely-positioned popup would be clipped by the
 *  table cells' overflow:hidden single-line clamp.
 */
import { useState } from "react";
import { templatePreviewUrl, type TemplateKind } from "../api";

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
  const [failed, setFailed] = useState(false);

  if (failed) return <span className="dim" title="no published version to preview">—</span>;

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
      <img
        className="tpl-thumb"
        src={templatePreviewUrl(kind, id, versionId)}
        loading="lazy"
        alt={name}
        onError={() => setFailed(true)}
      />
      {pop ? (
        <img
          className="tpl-thumb-pop"
          style={{ left: pop.x, top: pop.y }}
          src={templatePreviewUrl(kind, id, versionId)}
          alt={name}
        />
      ) : null}
    </span>
  );
}
