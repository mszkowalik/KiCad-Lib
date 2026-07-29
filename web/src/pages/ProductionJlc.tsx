/** JLC — the import pipeline, laid out in execution order.
 *
 *  1. Session: the one input only a human can supply. A dead session is the
 *     most common reason a sync fails, and the fix (paste fresh cookies) is
 *     only possible here — so it sits first, and pasting new cookies
 *     refreshes the panels below (the onChange wire that the old mega-page
 *     never connected).
 *  2. Decision queue: each assembly order linked to a run or marked external,
 *     with the evidence on screen, previewed through the real write path.
 *  3. Staged batches and parts orders: sync only stages; importing is the
 *     separate, previewable, reversible step. Parts-order lines become the
 *     purchase lots that draws bind to.
 */
import { useState } from "react";
import JlcImportPanel from "../components/invoices/JlcImportPanel";
import JlcSessionStrip from "../components/invoices/JlcSessionStrip";
import JlcStagedPanel from "../components/invoices/JlcStagedPanel";

export default function ProductionJlc() {
  // Bumped when the session changes or an import lands, so the sibling
  // panels reload instead of showing state from before the write.
  const [seq, setSeq] = useState(0);
  const bump = () => setSeq((n) => n + 1);

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>JLCPCB</h1>
          <span className="toolbar-total">
            session → sync → decide → apply → import, top to bottom
          </span>
        </div>
        <JlcSessionStrip onChange={bump} />
        <JlcImportPanel key={`q-${seq}`} onApplied={bump} />
        <JlcStagedPanel key={`s-${seq}`} onImported={bump} />
      </div>
    </div>
  );
}
