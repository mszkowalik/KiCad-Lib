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
 *  Only the PROBLEMS are listed. A batch where everything reconciles says so in
 *  one line: a wall of `ok` rows is the reliable way to make a reader stop
 *  reading the list that matters.
 */
import { useEffect, useState } from "react";
import {
  errorMessage,
  getSupplyCoverage,
  isAbortError,
  type SupplyCoverage as Coverage,
  type SupplyCoverageRow,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";

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
  const [data, setData] = useState<Coverage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setData(null);
    getSupplyCoverage(runId, ac.signal)
      .then(setData)
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    return () => ac.abort();
  }, [runId]);

  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Spinner label="Checking supply coverage…" />;

  if (!data.known && !data.checked_without_bom) {
    return (
      <p className="muted">
        No supplier BOM is cached for this batch, so who supplied each part is unknown.
        {data.orders.length
          ? ` Fetch it for ${data.orders.join(", ")} on the JLC tab.`
          : " No supplier order is linked to it."}
      </p>
    );
  }

  const problems = data.rows.filter((r) => r.verdict !== "ok");
  const ok = data.rows.length - problems.length;

  return (
    <>
      <p className="muted">
        {!data.known ? (
          <>
            No supplier BOM is cached, so who supplied each position is unknown. Only the
            double-supply check ran — it compares our own rows.{" "}
          </>
        ) : null}
        {ok} of {data.rows.length} positions reconcile
        {data.orders_without_bom.length
          ? ` · ${data.orders_without_bom.length} linked order(s) have no BOM cached`
          : ""}
        {data.unexpected_draws.length
          ? ` · ${data.unexpected_draws.length} draw(s) the supplier never mentions`
          : ""}
        .
      </p>

      {problems.length ? (
        <div className="table-wrap">
          <table className="data data-fixed supply-coverage-table">
            <thead>
              <tr>
                <th>Part</th>
                <th>Supplier says</th>
                <th className="num">Ours</th>
                <th className="num">Theirs</th>
                <th className="num">Drawn</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {problems.map((r) => <ProblemRow key={r.lcsc} r={r} />)}
            </tbody>
          </table>
        </div>
      ) : null}

      {data.unexpected_draws.length ? (
        <p className="muted">
          Drawn but absent from the supplier's BOM:{" "}
          {data.unexpected_draws.map((u) => `${u.lcsc} (${u.drawn})`).join(", ")}. Packaging
          and off-board parts belong here; a part that should have been on the board does not.
        </p>
      ) : null}
    </>
  );
}

function ProblemRow({ r }: { r: SupplyCoverageRow }) {
  const v = VERDICTS[r.verdict] || { tone: "neutral", label: r.verdict, why: "" };
  return (
    <tr>
      <td title={`${r.mpn} · orders ${r.orders.join(", ")}`}>
        <span className="mono">{r.lcsc}</span>{" "}
        <span className="dim">{r.mpn}</span>
      </td>
      <td title={`JLC: ${r.sources.join(", ")}`} className="dim">
        {r.sources.join(", ")}
      </td>
      <td className="num">{r.expected_from_pool}</td>
      <td className="num">{r.from_supplier}</td>
      <td className="num">{r.drawn}</td>
      <td>
        <span className={`pill ${v.tone}`} title={v.why}>{v.label}</span>
      </td>
    </tr>
  );
}
