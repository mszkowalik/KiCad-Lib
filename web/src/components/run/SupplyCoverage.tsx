/** Is every part this batch used accounted for exactly ONCE?
 *
 *  Two ways a position can be satisfied and the supplier states which: out of
 *  OUR pool, which needs a draw, or out of the SUPPLIER's own stock, which is
 *  inside the assembly fee and must have NO draw. Getting that wrong in either
 *  direction was invisible until somebody went looking — `void_shop_draws`
 *  existed to undo the double charge by hand, and decision
 *  [0038] was written after a position met by the supplier
 *  looked exactly like a forgotten one.
 *
 *  Only the PROBLEMS are listed, and a batch where everything reconciles draws no
 *  card at all (user, 2026-11-07): a line that says all is well is the reliable way
 *  to make a reader stop reading the one that says it is not. A card stays when the
 *  check could not run, because no supplier BOM is cached.
 */
import { type ReactNode } from "react";
import {
  getSupplyCoverage,
  type SupplyCoverageRow,
} from "../../api";
import DataTable from "../DataTable";
import FoldSection, { StatChip } from "../FoldSection";
import { ErrorBanner } from "../Ui";
import { useLoad } from "../useLoad";

/** What each verdict means, and how loudly to say it. `ok` never renders. */
const VERDICTS: Record<string, { tone: string; label: string; why: string }> = {
  drawn_but_supplier_supplied: {
    tone: "err",
    label: "paid for twice",
    why: "The supplier supplied this part and billed it inside the assembly fee, "
       + "and a pool draw took it out of our stock as well. The batch is charged twice.",
  },
  bought_for_batch_and_drawn: {
    tone: "err",
    label: "paid for twice",
    why: "This batch bought the part directly — it is on an invoice line charged straight "
       + "to the batch — and ALSO drew it out of the shared pool. Both are charged, so the "
       + "batch pays twice. This check needs no supplier BOM: it compares our own rows, "
       + "which is why it also covers a hand-entered invoice.",
  },
  no_draw: {
    tone: "err",
    label: "no draw",
    why: "The supplier says this came out of OUR stock, but nothing was drawn for it — "
       + "so the batch is not paying for parts it used.",
  },
  over_drawn: {
    tone: "warn",
    label: "over-drawn",
    why: "More was drawn than the supplier says came from our stock. On a position the "
       + "supplier part-filled, the draw should cover our share only.",
  },
  short: {
    tone: "warn",
    label: "short",
    why: "Less was drawn than the supplier says came from our stock.",
  },
  supplier_numbers_disagree: {
    tone: "neutral",
    label: "supplier numbers disagree",
    why: "The supplier's own figures do not add up for this position "
       + "(their pool share plus their shop share is not the position total), so its "
       + "coverage cannot be checked. The MONEY is unaffected.",
  },
};

export default function SupplyCoverage({ runId }: { runId: number }) {
  const { data, error } = useLoad((signal) => getSupplyCoverage(runId, signal), [runId]);

  const plain = (body: ReactNode) => (
    <div className="card pad">
      <h3 className="card-title">Supply coverage</h3>
      {body}
    </div>
  );

  if (error) return plain(<ErrorBanner message={error} />);
  // No spinner: on most batches this card never appears, and it must not flash.
  if (!data) return null;

  if (!data.known && !data.checked_without_bom) {
    return plain(
      <p className="muted">
        No supplier BOM is cached for this batch, so who supplied each part is unknown.
        {data.orders.length
          ? ` Fetch it for ${data.orders.join(", ")} on the JLC tab.`
          : " No supplier order is linked to it."}
      </p>,
    );
  }

  const problems = data.rows.filter((r) => r.verdict !== "ok");
  if (data.known && !problems.length && !data.orders_without_bom.length && !data.unexpected_draws.length) {
    return null;
  }
  const ok = data.rows.length - problems.length;
  // One chip per verdict, the loudest first: a fold never hides a problem.
  const byVerdict = new Map<string, { label: string; tone: string; n: number }>();
  for (const r of problems) {
    const v = VERDICTS[r.verdict] || { tone: "neutral", label: r.verdict, why: "" };
    const seen = byVerdict.get(v.label);
    if (seen) seen.n += 1;
    else byVerdict.set(v.label, { label: v.label, tone: v.tone, n: 1 });
  }
  const verdictRank = (tone: string) => (tone === "err" ? 0 : tone === "warn" ? 1 : 2);
  const verdictChips = [...byVerdict.values()].sort((a, b) => verdictRank(a.tone) - verdictRank(b.tone));

  return (
    <FoldSection
      title="Supply coverage"
      count={problems.length}
      foldKey={`run:${runId}:supply-coverage`}
      chips={
        <>
          {verdictChips.slice(0, ok ? 3 : 4).map((c) => (
            <StatChip key={c.label} n={c.n} tone={c.tone === "err" || c.tone === "warn" ? c.tone : undefined}>{c.label}</StatChip>
          ))}
          {ok ? <StatChip n={ok} tone="ok">reconcile</StatChip> : null}
        </>
      }
    >
      <p className="muted">
        {!data.known ? (
          <>
            No supplier BOM is cached, so who supplied each position is unknown. Only the
            double-supply check ran — it compares our own rows.{" "}
          </>
        ) : null}
        {[
          problems.length ? `${ok} of ${data.rows.length} positions reconcile` : "",
          data.orders_without_bom.length ? `${data.orders_without_bom.length} linked order(s) have no BOM cached` : "",
          data.unexpected_draws.length ? `${data.unexpected_draws.length} draw(s) the supplier never mentions` : "",
        ].filter(Boolean).join(" · ")}
      </p>

      {problems.length ? (
        <div className="table-wrap">
          <DataTable
            rows={problems}
            rowKey={(r) => r.lcsc}
            columns={[
              { key: "part", label: "Part", width: 34, get: (r) => `${r.lcsc} ${r.mpn}`,
                title: (r) => `${r.mpn} · orders ${r.orders.join(", ")}`,
                render: (r) => (
                  <>
                    <span className="mono">{r.lcsc}</span>{" "}
                    <span className="dim">{r.mpn}</span>
                  </>
                ) },
              { key: "says", label: "Supplier says", width: 16, className: "dim", get: (r) => r.sources.join(", "),
                title: (r) => `JLC: ${r.sources.join(", ")}` },
              { key: "ours", label: "Ours", width: 10, numeric: true, get: (r) => r.expected_from_pool },
              { key: "theirs", label: "Theirs", width: 10, numeric: true, get: (r) => r.from_supplier },
              { key: "drawn", label: "Drawn", width: 10, numeric: true, get: (r) => r.drawn },
              { key: "verdict", label: "Verdict", width: 20, get: (r) => verdictOf(r).label,
                render: (r) => {
                  const v = verdictOf(r);
                  return <span className={`pill ${v.tone}`} title={v.why}>{v.label}</span>;
                } },
            ]}
          />
        </div>
      ) : null}

      {data.unexpected_draws.length ? (
        <p className="muted">
          Drawn but absent from the supplier's BOM:{" "}
          {data.unexpected_draws.map((u) => `${u.lcsc} (${u.drawn})`).join(", ")}. Packaging
          and off-board parts belong here; a part that should have been on the board does not.
        </p>
      ) : null}
    </FoldSection>
  );
}

function verdictOf(r: SupplyCoverageRow) {
  return VERDICTS[r.verdict] || { tone: "neutral", label: r.verdict, why: "" };
}
