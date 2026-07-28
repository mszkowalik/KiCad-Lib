import { useCallback, useEffect, useState } from "react";
import {
  deleteStockAdjustment,
  errorMessage,
  getAllStockAdjustments,
  getPartsStock,
  isAbortError,
  type PartsStock,
  type PartsStockRow,
  type StockAdjustment,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";

/** Money, always two decimals. `toLocaleString()` alone renders whatever precision
 *  the number happens to carry — the delta column was showing $102.128 and $0.027. */
function money(v: number | null | undefined): string {
  if (v == null) return "—";
  return `$${v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/**
 * Does the stock account close? Whatever went in, went out or is still here.
 *
 * This screen exists because the platform's two conservation identities cannot
 * answer that question and never could. `pool.balanced` is
 * `purchased +/- adjustments - drawn == on_hand` with `on_hand` COMPUTED from the
 * other three — true by construction, silent about reality. On 2026-07-28 it read
 * `balanced: true` while the pool held 6,368 units JLC had never had and nine
 * draws were counted twice ($167.95 across 8 runs).
 *
 * The only external check available is JLC's own consigned-stock count, and
 * `parts_stock` has computed that comparison all along — as a column, on a table,
 * that nothing required anyone to look at. Here it is a VERDICT.
 *
 * Two things are deliberately prominent rather than tucked away:
 *
 * - **`pool_only` parts are not failures.** A part bought from DigiKey or TME was
 *   never consigned to JLC, so JLC holding none of it is correct. Counting those
 *   as discrepancies would bury the six real ones in seventy false ones.
 * - **Zero-cost positive adjustments get their own tile.** Quantity with no money
 *   behind it is invisible to every value check in the system, which is precisely
 *   how the 6,368 units survived. It is a legitimate shape for a genuine opening
 *   balance and a fabrication in every other case, so it is counted, never hidden.
 */
export default function StockReconcile() {
  const dialog = useDialog();
  const [stock, setStock] = useState<PartsStock | null>(null);
  const [adjs, setAdjs] = useState<StockAdjustment[] | null>(null);
  const [adjTotals, setAdjTotals] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [showAdjs, setShowAdjs] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    setLoading(true);
    Promise.all([getPartsStock(signal), getAllStockAdjustments("", signal)])
      .then(([s, a]) => {
        setStock(s);
        setAdjs(a.adjustments);
        setAdjTotals(a.totals as unknown as Record<string, unknown>);
        setError("");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  async function removeAdj(a: StockAdjustment) {
    const ok = await dialog.confirm(
      `Delete adjustment ${a.id} (${a.qty_delta > 0 ? "+" : ""}${a.qty_delta} of ` +
        `${a.lcsc || a.mpn || `component ${a.component_id}`}, ${a.reason})? ` +
        `The stock balance moves by ${-a.qty_delta} and every run's cost is replayed ` +
        `from the corrected history.`,
      { title: "Delete adjustment", confirmLabel: "Delete", tone: "danger" },
    );
    if (!ok) return;
    setBusy(a.id);
    try {
      await deleteStockAdjustment(a.id);
      load();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not delete it" });
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Spinner label="reconciling stock against JLCPCB" />;
  if (!stock) return <ErrorBanner message={error || "no stock data"} />;

  const t = stock.totals;
  // Only parts measured on BOTH sides can disagree. A pool_only part was bought
  // somewhere JLC never saw, which is not a discrepancy.
  const comparable = stock.parts.filter((p) => p.state === "both");
  const off = comparable.filter((p) => Math.abs(p.delta_qty ?? 0) > 0.5);
  const reconciles = off.length === 0;
  const zeroCost = Number(adjTotals?.zero_cost_positive ?? 0);
  const shown = showAll ? comparable : off;

  return (
    <div className="card">
      <h2 className="card-title">Does the stock account close?</h2>
      <p className="card-subtitle">
        Every part measured twice — what the platform believes it holds, against what JLCPCB
        actually holds on consignment. The register's own identities cannot answer this: they
        derive on-hand from purchases and draws, so they balance by construction whatever the
        real quantities are.
      </p>
      <ErrorBanner message={error} />

      <div className="toolbar">
        <span className={`pill ${reconciles ? "ok" : "err"}`}>
          {reconciles ? "STOCK RECONCILES" : `${off.length} PARTS DO NOT RECONCILE`}
        </span>
        <span className="pill neutral">{comparable.length} parts measured twice</span>
        {t.pool_only_parts > 0 && (
          <span
            className="pill neutral"
            title="Bought somewhere JLC never held it — DigiKey, TME, Mouser, local. Not a discrepancy."
          >
            {t.pool_only_parts} not consigned to JLC
          </span>
        )}
        {t.missing_invoice_parts > 0 && (
          <span
            className="pill err"
            title="JLC holds these and the platform has no purchase for them — a missing invoice."
          >
            {t.missing_invoice_parts} held with no purchase
          </span>
        )}
        <span className={`pill ${zeroCost ? "warn" : "neutral"}`} title={ZERO_COST_HINT}>
          {zeroCost} zero-cost stock additions
        </span>
      </div>

      <div className="toolbar">
        <span className="muted">
          paid {money(t.spent_usd)} · drawn {money(t.drawn_usd)} · adjusted{" "}
          {money(t.adjusted_usd)} · still here {money(t.remaining_at_cost_usd)}
        </span>
        {stock.last_sync && (
          <span className="muted dim">
            JLC counted {new Date(stock.last_sync).toLocaleString()}
          </span>
        )}
      </div>

      {!reconciles && (
        <div className="banner-warn">
          A positive delta means JLC holds MORE than the platform accounts for — a purchase was
          never entered. A negative delta means the platform still counts parts JLC no longer
          has: boards were built without recording the draw, the stock was lost, or a draw was
          counted twice.
        </div>
      )}

      <div className="btn-row">
        <button className="btn btn-sm" onClick={() => setShowAll((v) => !v)}>
          {showAll ? "only the ones that disagree" : `show all ${comparable.length}`}
        </button>
        <button className="btn btn-sm" onClick={() => setShowAdjs((v) => !v)}>
          {showAdjs ? "hide adjustments" : `adjustments (${adjs?.length ?? 0})`}
        </button>
      </div>

      <div className="table-wrap">
        {shown.length === 0 ? (
          <p className="muted">
            Every part JLC holds agrees with the platform, piece for piece.
          </p>
        ) : (
          <table className="data data-fixed stock-reconcile-table">
            <thead>
              <tr>
                <th>LCSC</th>
                <th>part</th>
                <th className="num">bought</th>
                <th className="num">drawn</th>
                <th className="num">written off</th>
                <th className="num">ours</th>
                <th className="num">JLC has</th>
                <th className="num">delta</th>
                <th className="num">at cost</th>
              </tr>
            </thead>
            <tbody>
              {[...shown]
                .sort((a, b) => Math.abs(b.delta_qty ?? 0) - Math.abs(a.delta_qty ?? 0))
                .map((p) => (
                  <Row key={p.key} p={p} />
                ))}
            </tbody>
          </table>
        )}
      </div>

      {showAdjs && adjs && (
        <>
          <h3 className="card-title">Stock adjustments</h3>
          <p className="card-subtitle">
            The least evidenced write in the system — stock moving with no invoice behind it.
            Including the ones that belong to no project, which the per-project view cannot
            show and which is exactly what a reconciliation pass writes.
          </p>
          <div className="table-wrap">
            <table className="data data-fixed stock-adj-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>part</th>
                  <th className="num">qty</th>
                  <th className="num">unit</th>
                  <th>reason</th>
                  <th>when</th>
                  <th>why</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {adjs.map((a) => {
                  const conjured = a.qty_delta > 0 && !a.unit_cost_usd;
                  return (
                    <tr key={a.id}>
                      <td className="mono">{a.id}</td>
                      <td className="mono" title={a.mpn || ""}>
                        {a.lcsc || a.mpn || `c${a.component_id}`}
                      </td>
                      <td className="num">
                        {a.qty_delta > 0 ? `+${a.qty_delta}` : a.qty_delta}
                      </td>
                      <td className="num">
                        {a.unit_cost_usd == null ? (
                          <span className="dim">avg</span>
                        ) : a.unit_cost_usd === 0 ? (
                          <span className="pill warn" title={ZERO_COST_HINT}>
                            $0
                          </span>
                        ) : (
                          `$${a.unit_cost_usd}`
                        )}
                      </td>
                      <td>
                        <span className={`pill ${conjured ? "warn" : "neutral"}`}>
                          {a.reason}
                        </span>
                      </td>
                      <td className="muted dim">{a.adjusted_at || "—"}</td>
                      <td className="cell-desc" title={a.note}>
                        {a.note || <span className="dim">no reason given</span>}
                      </td>
                      <td>
                        <button
                          className="btn btn-sm btn-danger"
                          disabled={busy === a.id}
                          onClick={() => removeAdj(a)}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

const ZERO_COST_HINT =
  "Positive quantity with no cost attached — stock conjured from nothing. Legitimate for a " +
  "genuine opening balance, and invisible to every value check in the platform, which is how " +
  "6,368 phantom units survived until the quantities were compared against JLC by hand.";

function Row({ p }: { p: PartsStockRow }) {
  const d = p.delta_qty ?? 0;
  // `bought - drawn - written_off` is the honest balance. Where it equals JLC's
  // count but `ours` does not, an adjustment is the difference — which is exactly
  // what the five invented opening balances looked like.
  const honest = p.bought - p.drawn - p.lost;
  const honestAgrees = Math.abs(honest - p.held_qty) < 0.5;
  return (
    <tr>
      <td className="mono">{p.lcsc || "—"}</td>
      <td className="cell-desc" title={p.mpn || p.description}>
        {p.mpn || p.component_name || p.description || "—"}
      </td>
      <td className="num">{p.bought.toLocaleString()}</td>
      <td className="num">{p.drawn.toLocaleString()}</td>
      <td className="num">{p.lost ? p.lost.toLocaleString() : <span className="dim">—</span>}</td>
      <td className="num">{p.remaining_qty.toLocaleString()}</td>
      <td className="num">{p.held_qty.toLocaleString()}</td>
      <td className="num">
        <span className={`pill ${Math.abs(d) < 0.5 ? "ok" : d > 0 ? "err" : "warn"}`}>
          {d > 0 ? `+${d.toLocaleString()}` : d.toLocaleString()}
        </span>
        {honestAgrees && Math.abs(d) > 0.5 && (
          <span
            className="muted dim"
            title={
              "bought - drawn - written off equals JLC's count exactly, so the whole " +
              "difference is an adjustment. Check it below."
            }
          >
            {" "}
            adj
          </span>
        )}
      </td>
      <td className="num">
        {p.delta_value_usd == null ? <span className="dim">—</span> : money(p.delta_value_usd)}
      </td>
    </tr>
  );
}
