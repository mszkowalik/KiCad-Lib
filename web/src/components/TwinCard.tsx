/** "How it was built": a device's twin — its steps, its parts, the invoices
 *  that paid for its steps, and its price (decisions 0059, 0060). Draws
 *  nothing for a device that has no twin.
 *
 *  Each step is shown in the words it had when it was done, with how the unit
 *  was chosen: a scan or a bench read is an observation, a pick from a list is
 *  a person's statement, and a found unit entered at zero value says so.
 */
import { getDeviceTwin, type TwinFitted, type TwinStepRow } from "../api";
import { localDate, pln } from "../format";
import DataTable from "./DataTable";
import FoldSection, { StatChip } from "./FoldSection";
import { ErrorBanner, StatusPill } from "./Ui";
import { useLoad } from "./useLoad";

/** How the unit was chosen, in one word — the cell is narrow; the sentence is
 *  on the hover. */
const CHOSEN: Record<string, [string, string]> = {
  stack: ["stack", "taken from a stack before it had a name"],
  scanned: ["scanned", "its label or MAC was scanned"],
  list: ["list", "picked from a list by a person"],
  bench: ["bench", "read by the bench"],
  merge: ["merge", "given its unit by a merge after programming"],
  found: ["found", "entered at a stock count, at zero value"],
  supplier: ["supplier", "the assembly step, recorded by a person from the supplier's assembly order (decision 0072)"],
  manual: ["by hand", "the assembly step, recorded by hand for an assembly house with no JLC order (decision 0072)"],
  rebuilt: ["records", "rebuilt from the batch's records (decision 0060)"],
  stated: ["stated", "a person stated it was done; no bench run records it (decision 0074)"],
};

const SOURCE: Record<string, string> = {
  "our stock": "our stock", supplier: "the supplier", both: "both", unknown: "not known",
};

/** A per-unit quantity: a batch's draw over its units is rarely a whole number. */
const round = (q: number) => Math.round(q * 1000) / 1000;

export default function TwinCard({ deviceId }: { deviceId: number }) {
  const { data, error } = useLoad((signal) => getDeviceTwin(deviceId, signal), [deviceId], { keep: true });
  const twin = data?.twin;
  if (error) return <ErrorBanner message={error} />;
  if (!twin) return null;
  const money = (v: number | null | undefined) => pln(v, twin.pln_per_usd);
  return (
    <div className="card pad">
      <h2 className="card-title">How it was built</h2>
      <p className="muted dim">
        Board from {twin.origin_run}{twin.run !== twin.origin_run ? `, programmed in ${twin.run}` : ""}.{" "}
        <StatusPill status={twin.status} />{" "}
        Price {money(twin.price.total_usd)}: own parts {money(twin.price.own_parts_usd)} + step invoices{" "}
        {money(twin.price.step_costs_usd)} + origin batch cost{" "}
        {money(twin.price.origin_share_usd)}{twin.found ? " (found unit, entered at zero)" : ""}.
      </p>
      <FoldSection
        bare
        title="Steps"
        count={twin.steps.length}
        foldKey={`device:${deviceId}:built-steps`}
        chips={<StatChip n={money(twin.steps.reduce((a, st) => a + st.parts_usd + st.costs_usd, 0))}>parts and invoices</StatChip>}
      >
      <DataTable<TwinStepRow>
        rows={twin.steps}
        rowKey={(s) => `${s.step}-${s.made_at}-${s.label}`}
        columns={[
          { key: "date", label: "Date", width: 24, className: "mono", get: (s) => s.made_at,
            title: (s) => `${s.made_at} · ${s.batch ?? ""} · ${s.actor}` },
          { key: "step", label: "Step", width: 36, get: (s) => s.label,
            render: (s) => (s.deployment_version
              ? <>{s.label} <span className="muted">· {s.deployment_version}</span></> : s.label),
            title: (s) => [s.note, s.programming_run_id ? `bench run #${s.programming_run_id}` : ""]
              .filter(Boolean).join("\n") },
          // One money cell: the card sits in a narrow column. The parts and
          // the invoices behind the figure are on the hover.
          { key: "cost", label: "Cost", width: 26, numeric: true, get: (s) => s.parts_usd + s.costs_usd,
            render: (s) => (s.parts_usd + s.costs_usd ? money(s.parts_usd + s.costs_usd) : "—"),
            title: (s) => [
              ...s.parts.map((p) => `${round(p.qty)} × ${p.name}${p.lot ? ` (${p.lot})` : ""}`),
              ...s.costs.map((c) => `${c.step_name || c.label} (${c.supplier} ${c.doc_number}): ${money(c.usd)}`
                + (c.shared_by.length ? ` — one invoice for ${c.shared_by.join(", ")}` : "")),
            ].join("\n") || "nothing drawn or invoiced" },
          { key: "how", label: "Chosen", width: 14, get: (s) => CHOSEN[s.chosen]?.[0] ?? s.chosen,
            title: (s) => CHOSEN[s.chosen]?.[1] ?? s.chosen },
        ]}
      />
      </FoldSection>
      {twin.reflashes.length ? (
        <p className="muted dim">
          Programmed again after it was named:{" "}
          {twin.reflashes.map((r) => `${r.deployment_version ?? "unknown version"}`
            + `${r.at ? ` on ${localDate(r.at)}` : ""} (run #${r.programming_run_id})`).join("; ")}.
        </p>
      ) : null}
      {twin.fitted.length ? (
        <FoldSection
          bare
          title="On the board"
          count={twin.fitted.length}
          foldKey={`device:${deviceId}:fitted`}
          chips={[...new Set(twin.fitted.map((f) => f.source))].slice(0, 4).map((src) => (
            <StatChip key={src} n={twin.fitted.filter((f) => f.source === src).length}>{SOURCE[src] ?? src}</StatChip>
          ))}
        >
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
        </FoldSection>
      ) : null}
    </div>
  );
}
