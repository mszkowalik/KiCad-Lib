/** What a part IS, and what it can be set to — on the part, not in a table.
 *
 *  The panel this replaces listed every steerable part in the design under
 *  the drawing: forty text boxes with a reference beside each, in an order
 *  nobody chose, for a circuit the user was looking at three inches above.
 *  Falstad solves it the way schematic editors have always solved it — click
 *  the component, get a dialog about that component — and so does this.
 *
 *  It is deliberately two halves:
 *
 *  1. **What the part is.** Its reference, its value, the library part behind
 *     it, and whatever else the placement carries: footprint, datasheet,
 *     description, the manufacturer's number, the simulation model. This half
 *     is not about simulation at all, which is the point — the same dialog is
 *     meant to open on a project's schematic tab and answer "what IS this?"
 *     from the catalogue.
 *  2. **What it can be set to.** `ComponentInspector`, unchanged: a form per
 *     shape the part takes, a row per number, and a slider where one suits.
 *
 *  It floats over the drawing and is dragged by its title bar, because the
 *  part it describes is underneath it and the user has to be able to see both.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import ComponentInspector from "./edit/ComponentInspector";
import type { ParamField, ParamForm } from "./edit/params";

export interface PartFacts {
  /** The reference on the sheet — `R12`, `U1`. */
  ref: string;
  value: string;
  libId: string;
  /** Every field on the placement, in file order. */
  props: { k: string; v: string }[];
  /** The name `alter` takes, when it differs from the reference. */
  spice?: string;
}

interface Props {
  part: PartFacts;
  forms: ParamForm[];
  value: string;
  params: string;
  onValue?: (next: string) => void;
  onParams?: (next: string) => void;
  onLive?: (field: ParamField, value: string) => void;
  /** The file cannot be rewritten — a sheet KiCad wrote. The RUN still
   *  follows what is typed, through `onLive`. */
  readOnly?: boolean;
  /** Where to open, in pixels inside the drawing's own box. */
  at: { x: number; y: number };
  onClose: () => void;
  /** Extra rows under the identity block — a reference field, a contact
   *  toggle, Rotate/Mirror/Delete. */
  children?: React.ReactNode;
}

/** Fields worth showing, in the order a person reads them. Reference and
 *  Value are in the header already, and the `Sim.*` machinery is the
 *  inspector's business — except the model name, which is the one line that
 *  says what this part is simulated AS. */
const SHOWN: [string, string][] = [
  ["Description", "Description"],
  ["Footprint", "Footprint"],
  ["Footprint_Name", "Package"],
  ["Datasheet", "Datasheet"],
  ["MPN", "Manufacturer part"],
  ["Manufacturer", "Manufacturer"],
  ["Manufacturer_Name", "Manufacturer"],
  ["LCSC", "LCSC"],
  ["JLCPCB", "JLCPCB"],
  ["Sim.Name", "Simulated as"],
];

const WIDTH = 340;

export default function PartPopup({
  part, forms, value, params, onValue, onParams, onLive, readOnly, at, onClose, children,
}: Props) {
  const [pos, setPos] = useState(at);
  /** Where the pointer was and where the box was when the drag began. Deltas
   *  only: no rectangles, so nothing has to be re-measured while dragging. */
  const drag = useRef<{ px: number; py: number; x: number; y: number } | null>(null);
  const box = useRef<HTMLDivElement | null>(null);

  // Re-anchor when a DIFFERENT part is picked. Dragging this one where the
  // user wants it must survive the re-renders a live run causes, which is why
  // this watches the coordinates and not the object.
  useEffect(() => { setPos({ x: at.x, y: at.y }); }, [at.x, at.y]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const onMove = useCallback((e: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    setPos({ x: d.x + (e.clientX - d.px), y: Math.max(0, d.y + (e.clientY - d.py)) });
  }, []);
  const onUp = useCallback(() => { drag.current = null; }, []);
  useEffect(() => {
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [onMove, onUp]);

  const startDrag = (e: React.PointerEvent) => {
    drag.current = { px: e.clientX, py: e.clientY, x: pos.x, y: pos.y };
  };

  const byKey = new Map(part.props.map((f) => [f.k, (f.v ?? "").trim()]));
  const seen = new Set<string>();
  const rows: [string, string][] = [];
  for (const [key, label] of SHOWN) {
    const v = byKey.get(key);
    if (!v || seen.has(label)) continue;
    seen.add(label);
    rows.push([label, v]);
  }

  return (
    <div
      ref={box}
      className="part-popup"
      style={{ left: pos.x, top: pos.y, width: WIDTH }}
      role="dialog"
      aria-label={`${part.ref} ${part.value}`}
      // The drawing under this listens for clicks on wires and parts. Without
      // this, every click inside the dialog also picks whatever is behind it.
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="part-popup-bar" onPointerDown={startDrag}>
        <span className="part-popup-ref mono">{part.ref || "part"}</span>
        <span className="part-popup-value">{part.value}</span>
        <button type="button" className="part-popup-x" onClick={onClose} aria-label="Close">×</button>
      </div>

      <div className="part-popup-body">
        <dl className="part-facts">
          {part.libId ? (
            <>
              <dt>Library part</dt>
              <dd className="mono">{part.libId}</dd>
            </>
          ) : null}
          {rows.map(([label, v]) => (
            <div key={label} className="part-fact">
              <dt>{label}</dt>
              <dd>
                {/^https?:\/\//i.test(v) ? (
                  <a href={v} target="_blank" rel="noreferrer">{v.replace(/^https?:\/\//i, "").slice(0, 46)}</a>
                ) : (
                  v
                )}
              </dd>
            </div>
          ))}
          {part.spice && part.spice !== part.ref.toLowerCase() ? (
            <div className="part-fact">
              <dt>In the netlist</dt>
              {/* `Sim.Device R` on a switch makes KiCad PREFIX the reference,
                  so `SW1` is `rsw1` — and an `alter sw1` is accepted and does
                  nothing. Anyone typing a raw alter needs to see this. */}
              <dd className="mono">{part.spice}</dd>
            </div>
          ) : null}
        </dl>

        <ComponentInspector
          title=""
          forms={forms}
          value={value}
          params={params}
          onValue={onValue}
          onParams={onParams}
          onLive={onLive}
          readOnly={readOnly}
        />
        {readOnly && onLive ? (
          <p className="muted part-popup-note">
            This sheet came from KiCad, so the file is not rewritten — the RUNNING
            circuit follows what you type, and the next run starts from the file again.
          </p>
        ) : null}
        {children}
      </div>
    </div>
  );
}
