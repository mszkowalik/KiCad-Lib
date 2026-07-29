/** Info card for a part clicked on the board or schematic view: BOM line
 *  data + link to the matched library component. */
import { Link } from "react-router-dom";
import type { MapSymbol } from "../../api";

export default function PartInfo({ part, onClose }: { part: MapSymbol; onClose: () => void }) {
  const bom = part.bom;
  return (
    <div className="card pad partinfo">
      <div className="panel-head">
        <h3 className="card-title">
          <span className="mono">{part.ref}</span> {bom?.dnp ? <span className="pill err">DNP</span> : null}
        </h3>
        <button className="btn btn-sm" onClick={onClose}>Close</button>
      </div>
      <dl className="kv">
        <dt>Value</dt>
        <dd>{bom?.value || part.value || "—"}</dd>
        <dt>Component</dt>
        <dd>
          {bom?.component_id ? (
            <Link className="comp-link" to={`/library/components/${bom.component_id}`}>
              {bom.component_name}
            </Link>
          ) : (
            <span className="muted">not matched to the library</span>
          )}
        </dd>
        {bom?.footprint ? (
          <>
            <dt>Footprint</dt>
            <dd className="mono">{bom.footprint.replace(/^7Sigma:/, "")}</dd>
          </>
        ) : null}
        {bom?.lcsc ? (
          <>
            <dt>LCSC</dt>
            <dd className="mono">{bom.lcsc}</dd>
          </>
        ) : null}
        {bom?.mpn ? (
          <>
            <dt>MPN</dt>
            <dd className="mono">{bom.mpn}</dd>
          </>
        ) : null}
        {part.lib_id ? (
          <>
            <dt>Symbol</dt>
            <dd className="mono">{part.lib_id}</dd>
          </>
        ) : null}
        {part.side ? (
          <>
            <dt>Side</dt>
            <dd>{part.side === "B" ? "bottom" : "top"}</dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}
