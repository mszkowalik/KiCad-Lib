/** "How it was built": a device's twin — its steps, its parts, the invoices
 *  that paid for its steps, and its price (decisions 0059, 0060). Draws
 *  nothing for a device that has no twin.
 *
 *  Each step is shown in the words it had when it was done, with how the unit
 *  was chosen: a scan or a bench read is an observation, a pick from a list is
 *  a person's statement, and a found unit entered at zero value says so.
 */
import { useEffect, useState } from "react";
import { errorMessage, getDeviceTwin, isAbortError, type TwinFitted, type TwinInfo, type TwinStepRow } from "../api";
import { usd } from "../format";
import DataTable from "./DataTable";
import { ErrorBanner, StatusPill } from "./Ui";

/** How the unit was chosen, in one word — the cell is narrow; the sentence is
 *  on the hover. */
const CHOSEN: Record<string, [string, string]> = {
  stack: ["stack", "taken from a stack before it had a name"],
  scanned: ["scanned", "its label or MAC was scanned"],
  list: ["list", "picked from a list by a person"],
  bench: ["bench", "read by the bench"],
  merge: ["merge", "given its unit by a merge after programming"],
  found: ["found", "entered at a stock count, at zero value"],
  supplier: ["supplier", "recorded from the supplier's assembly order"],
  rebuilt: ["records", "rebuilt from the batch's records (decision 0060)"],
};

const SOURCE: Record<string, string> = {
  "our stock": "our stock", supplier: "the supplier", both: "both", unknown: "not known",
};

/** A per-unit quantity: a batch's draw over its units is rarely a whole number. */
const round = (q: number) => Math.round(q * 1000) / 1000;

export default function TwinCard({ deviceId }: { deviceId: number }) {
  const [twin, setTwin] = useState<TwinInfo | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    getDeviceTwin(deviceId, ac.signal)
      .then((r) => setTwin(r.twin))
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    return () => ac.abort();
  }, [deviceId]);
  if (error) return <ErrorBanner message={error} />;
  if (!twin) return null;
  return (
    <div className="card pad">
      <h2 className="card-title">How it was built</h2>
      <p className="muted dim">
        Board from {twin.origin_run}{twin.run !== twin.origin_run ? `, programmed in ${twin.run}` : ""}.{" "}
        <StatusPill status={twin.status} />{" "}
        Price {usd(twin.price.total_usd)}: own parts {usd(twin.price.own_parts_usd)} + step invoices{" "}
        {usd(twin.price.step_costs_usd)} + origin batch cost{" "}
        {usd(twin.price.origin_share_usd)}{twin.found ? " (found unit, entered at zero)" : ""}.
      </p>
      <DataTable<TwinStepRow>
        rows={twin.steps}
        rowKey={(s) => `${s.step}-${s.made_at}-${s.label}`}
        columns={[
          { key: "date", label: "Date", width: 24, className: "mono", get: (s) => s.made_at,
            title: (s) => `${s.made_at} · ${s.batch ?? ""} · ${s.actor}` },
          { key: "step", label: "Step", width: 36, get: (s) => s.label, title: (s) => s.note },
          // One money cell: the card sits in a narrow column. The parts and
          // the invoices behind the figure are on the hover.
          { key: "cost", label: "Cost", width: 26, numeric: true, get: (s) => s.parts_usd + s.costs_usd,
            render: (s) => (s.parts_usd + s.costs_usd ? usd(s.parts_usd + s.costs_usd) : "—"),
            title: (s) => [
              ...s.parts.map((p) => `${round(p.qty)} × ${p.name}${p.lot ? ` (${p.lot})` : ""}`),
              ...s.costs.map((c) => `${c.step_name || c.label} (${c.supplier} ${c.doc_number}): ${usd(c.usd)}`
                + (c.shared_by.length ? ` — one invoice for ${c.shared_by.join(", ")}` : "")),
            ].join("\n") || "nothing drawn or invoiced" },
          { key: "how", label: "Chosen", width: 14, get: (s) => CHOSEN[s.chosen]?.[0] ?? s.chosen,
            title: (s) => CHOSEN[s.chosen]?.[1] ?? s.chosen },
        ]}
      />
      {twin.fitted.length ? (
        <details>
          <summary className="muted">On the board: {twin.fitted.length} position(s) from the supplier's own BOM</summary>
          <p className="muted dim">The supplier's designators, which can differ from the schematic.</p>
          <DataTable<TwinFitted>
            rows={twin.fitted}
            rowKey={(f) => `${f.order}-${f.designator}-${f.lcsc}`}
            columns={[
              { key: "ref", label: "Designators", width: 30, className: "mono", get: (f) => f.designator },
              { key: "n", label: "Per board", width: 10, numeric: true, get: (f) => f.per_board },
              { key: "part", label: "Part", width: 34, get: (f) => f.mpn || f.lcsc, title: (f) => f.lcsc },
              { key: "src", label: "From", width: 26, get: (f) => SOURCE[f.source] ?? f.source,
                title: (f) => (f.source === "our stock" ? "our stock held at the supplier" :
                  f.source === "supplier" ? "bought by the supplier for this order" : f.source) },
            ]}
          />
        </details>
      ) : null}
    </div>
  );
}
