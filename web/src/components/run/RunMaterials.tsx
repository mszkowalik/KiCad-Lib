/** Materials — planned BOM usage and really used components, ONE table.
 *
 *  Before this table the planned lines (priced at the run date) and the pool
 *  draws lived on two panels that never met, so "did we use what we planned"
 *  had no answer on any screen. Here every component is one row: planned qty
 *  and price on the left, the real draws on the right, and the source of
 *  every actual figure named — a draw written by the JLC invoice import is
 *  evidence, a manual draw is a claim.
 *
 *  Money on both sides is USD: draws are USD-denominated by construction, and
 *  the planned side carries `unit_usd`, converted server-side at the run date
 *  (never a silent 1:1 — an unknown rate renders as an em dash).
 *
 *  Row states keep the gaps visible instead of burying them in two tables:
 *  planned-and-used rows compare, planned-but-not-drawn rows warn, drawn-but-
 *  not-planned rows flag rework or an extra, and write-offs render as
 *  attrition rows.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  addRunConsumption,
  addStockAdjustment,
  consumeFromBom,
  deleteConsumption,
  deleteStockAdjustment,
  errorMessage,
  getAllStockAdjustments,
  getRunConsumption,
  isAbortError,
  updateRun,
  type ConsumptionRow,
  type RunEffectiveLine,
  type RunInfo,
  type StockAdjustment,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";
import { plain, price } from "../../format";

interface MatRow {
  key: string;
  /** display: MPN / component name, falling back to refs or the label */
  part: string;
  refs: string;
  lcsc: string;
  eff: RunEffectiveLine | null;
  cons: ConsumptionRow[];
  adjs: StockAdjustment[];
  plannedQty: number | null;
  plannedUnitUsd: number | null;
  plannedTotalUsd: number | null;
  usedQty: number | null;
  usedUnitUsd: number | null;
  usedTotalUsd: number | null;
  writtenOff: number;
}

function norm(s: string | null | undefined): string {
  return (s ?? "").trim().toUpperCase();
}

export default function RunMaterials({
  run,
  onChanged,
}: {
  run: RunInfo;
  onChanged: () => void;
}) {
  const dialog = useDialog();
  const [consumption, setConsumption] = useState<ConsumptionRow[] | null>(null);
  const [adjs, setAdjs] = useState<StockAdjustment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [overrideDraft, setOverrideDraft] = useState("");
  // manual draw + write-off drafts
  const [consMpn, setConsMpn] = useState("");
  const [consQty, setConsQty] = useState("");
  const [lossMpn, setLossMpn] = useState("");
  const [lossQty, setLossQty] = useState("");

  const reload = useCallback((signal?: AbortSignal) => {
    getRunConsumption(run.id, signal)
      .then((c) => {
        setConsumption(c);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getAllStockAdjustments("", signal)
      .then((a) => setAdjs(a.adjustments.filter((x) => x.charge_run_id === run.id)))
      .catch(() => setAdjs([]));
  }, [run.id]);

  useEffect(() => {
    const ac = new AbortController();
    reload(ac.signal);
    return () => ac.abort();
  }, [reload]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      reload();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const rows = useMemo<MatRow[]>(() => {
    const out: MatRow[] = [];
    const byKey = new Map<string, MatRow>();
    const claimKeys = (r: MatRow, keys: (string | null | undefined)[]) => {
      for (const k of keys.map(norm)) if (k && !byKey.has(k)) byKey.set(k, r);
    };

    const eff = run.effective;
    for (const l of eff?.lines ?? []) {
      if (l.excluded) continue;
      const r: MatRow = {
        key: `p:${l.key}`,
        part: l.component_name || l.label || l.value || l.refs || l.key,
        refs: l.refs || "",
        lcsc: l.lcsc || "",
        eff: l,
        cons: [],
        adjs: [],
        plannedQty: l.dropped ? 0 : l.qty_total,
        plannedUnitUsd: l.dropped ? null : (l.unit_usd ?? null),
        plannedTotalUsd:
          l.dropped || l.unit_usd == null ? null : l.unit_usd * l.qty_total,
        usedQty: null,
        usedUnitUsd: null,
        usedTotalUsd: null,
        writtenOff: 0,
      };
      out.push(r);
      claimKeys(r, [l.lcsc, l.component_name, l.value]);
    }

    for (const c of consumption ?? []) {
      const r =
        byKey.get(norm(c.lcsc)) ??
        byKey.get(norm(c.mpn)) ??
        null;
      if (r) {
        r.cons.push(c);
      } else {
        const nr: MatRow = {
          key: `u:${c.id}`,
          part: c.mpn || c.lcsc || `#${c.component_id ?? "?"}`,
          refs: "",
          lcsc: c.lcsc,
          eff: null,
          cons: [c],
          adjs: [],
          plannedQty: null,
          plannedUnitUsd: null,
          plannedTotalUsd: null,
          usedQty: null,
          usedUnitUsd: null,
          usedTotalUsd: null,
          writtenOff: 0,
        };
        out.push(nr);
        claimKeys(nr, [c.lcsc, c.mpn]);
      }
    }

    for (const a of adjs) {
      const r = byKey.get(norm(a.lcsc)) ?? byKey.get(norm(a.mpn)) ?? null;
      if (r) {
        r.adjs.push(a);
        r.writtenOff += -a.qty_delta;
      } else {
        out.push({
          key: `a:${a.id}`,
          part: a.mpn || a.lcsc || `c${a.component_id}`,
          refs: "",
          lcsc: a.lcsc,
          eff: null,
          cons: [],
          adjs: [a],
          plannedQty: null,
          plannedUnitUsd: null,
          plannedTotalUsd: null,
          usedQty: null,
          usedUnitUsd: null,
          usedTotalUsd: null,
          writtenOff: -a.qty_delta,
        });
      }
    }

    for (const r of out) {
      if (r.cons.length) {
        r.usedQty = r.cons.reduce((s, c) => s + c.qty, 0);
        r.usedTotalUsd = r.cons.reduce((s, c) => s + c.total_usd, 0);
        r.usedUnitUsd = r.usedQty ? r.usedTotalUsd / r.usedQty : null;
      }
    }
    return out;
  }, [run.effective, consumption, adjs]);

  const totals = useMemo(() => {
    const planned = rows.reduce((s, r) => s + (r.plannedTotalUsd ?? 0), 0);
    const used = rows.reduce((s, r) => s + (r.usedTotalUsd ?? 0), 0);
    const unpricedPlanned = rows.filter(
      (r) => r.plannedQty != null && r.plannedQty > 0 && r.plannedTotalUsd == null,
    ).length;
    return { planned, used, delta: used - planned, unpricedPlanned };
  }, [rows]);

  const applyOverride = (line: RunEffectiveLine, raw: string) => {
    const overrides = { ...(run.overrides ?? {}) } as Record<string, unknown>;
    if (raw.trim() === "") delete overrides[line.key];
    else overrides[line.key] = { unit_price: Number(raw) };
    return act(() => updateRun(run.id, { overrides }));
  };

  if (consumption === null && !error) return <Spinner label="Loading materials" />;

  const cur = run.effective?.currency || "USD";

  return (
    <>
      {error ? <ErrorBanner message={error} /> : null}

      <div className="card table-wrap">
        <table className="data data-fixed run-materials-table">
          <thead>
            <tr>
              <th>Part</th>
              <th className="num">Plan qty</th>
              <th className="num">Used</th>
              <th className="num">Δ qty</th>
              <th className="num">Plan unit $</th>
              <th className="num">Used unit $</th>
              <th className="num">Plan $</th>
              <th className="num">Used $</th>
              <th className="num">Δ $</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <Fragment key={r.key}>
                <MatTr
                  r={r}
                  open={open === r.key}
                  onToggle={() => {
                    setOpen(open === r.key ? null : r.key);
                    setOverrideDraft("");
                  }}
                />
                {open === r.key && (
                  <tr>
                    <td colSpan={10} className="ledger-cell">
                      <MatDetail
                        r={r}
                        cur={cur}
                        busy={busy}
                        overrideDraft={overrideDraft}
                        setOverrideDraft={setOverrideDraft}
                        onOverride={(raw) => r.eff && applyOverride(r.eff, raw)}
                        onRemoveDraw={(id) =>
                          void act(() => deleteConsumption(id))
                        }
                        onRemoveAdj={async (a) => {
                          const ok = await dialog.confirm(
                            `Delete write-off ${a.id} (${a.qty_delta} of ${a.lcsc || a.mpn})?`,
                            { title: "Delete write-off", confirmLabel: "Delete", tone: "danger" },
                          );
                          if (ok) void act(() => deleteStockAdjustment(a.id));
                        }}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={10} className="empty">
                  Nothing planned and nothing drawn — this batch has no snapshot and no draws.
                </td>
              </tr>
            )}
          </tbody>
          {rows.length > 0 && (
            <tfoot>
              <tr>
                <td>
                  <b>Total (USD)</b>
                  {totals.unpricedPlanned > 0 && (
                    <span
                      className="muted dim"
                      title={`${totals.unpricedPlanned} planned line(s) have no USD price (no ladder price or unknown FX rate) and count as 0 here.`}
                    >
                      {" "}
                      {totals.unpricedPlanned} unpriced
                    </span>
                  )}
                </td>
                <td />
                <td />
                <td />
                <td />
                <td />
                <td className="num">
                  <b>{plain(totals.planned)}</b>
                </td>
                <td className="num">
                  <b>{plain(totals.used)}</b>
                </td>
                <td className="num">
                  <span
                    className={`pill ${
                      Math.abs(totals.delta) < 0.01 ? "ok" : totals.delta > 0 ? "warn" : "neutral"
                    }`}
                  >
                    {totals.delta > 0 ? "+" : ""}
                    {plain(totals.delta)}
                  </span>
                </td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <div className="card pad">
        <div className="btn-row">
          {run.snapshot_id !== null && (
            <button
              className="btn btn-sm btn-primary"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  const r = await consumeFromBom(run.id);
                  if (r.unpriced.length) {
                    await dialog.alert(
                      `${r.created} lines drawn for ${r.volume} units. ` +
                        `${r.unpriced.length} part(s) had nothing in the pool and were costed at 0: ` +
                        r.unpriced.slice(0, 12).join(", "),
                      { title: "Drawn from pool, with gaps" },
                    );
                  }
                })
              }
            >
              Draw BOM from pool
            </button>
          )}
        </div>
        <div className="edit-grid">
          <label>
            Draw part (MPN)
            <input className="text" value={consMpn} onChange={(e) => setConsMpn(e.target.value)} />
          </label>
          <label>
            Quantity
            <input className="text" value={consQty} onChange={(e) => setConsQty(e.target.value)} />
          </label>
          <label>
            Lost part (MPN)
            <input className="text" value={lossMpn} onChange={(e) => setLossMpn(e.target.value)} />
          </label>
          <label>
            Quantity lost
            <input className="text" value={lossQty} onChange={(e) => setLossQty(e.target.value)} />
          </label>
        </div>
        <div className="btn-row">
          <button
            className="btn btn-sm"
            disabled={busy || !consMpn.trim() || !consQty.trim()}
            onClick={() =>
              void act(async () => {
                await addRunConsumption(run.id, {
                  mpn: consMpn.trim(),
                  qty: Number(consQty) || 0,
                  basis: "manual",
                });
                setConsMpn("");
                setConsQty("");
              })
            }
          >
            Draw from pool
          </button>
          <button
            className="btn btn-sm btn-danger"
            disabled={busy || !lossMpn.trim() || !lossQty.trim()}
            onClick={() =>
              void act(async () => {
                await addStockAdjustment(run.project_id, {
                  mpn: lossMpn.trim(),
                  qty_delta: -Math.abs(Number(lossQty) || 0),
                  reason: "attrition",
                  charge_run_id: run.id,
                  adjusted_at: run.run_date,
                  note: "lost in production",
                });
                setLossMpn("");
                setLossQty("");
              })
            }
          >
            Write off as attrition
          </button>
        </div>
        <p className="muted">
          Attrition is charged to this batch, so its per-device cost carries the real loss. Pool
          quantities must <strong>agree</strong> with JLCPCB&apos;s own count: whatever went in
          either went out through a batch, was written off here, or is still on the shelf.
          Production → Stock reconciles the two part by part.
        </p>
      </div>
    </>
  );
}

function MatTr({ r, open, onToggle }: { r: MatRow; open: boolean; onToggle: () => void }) {
  const dq =
    r.plannedQty != null && r.usedQty != null
      ? r.usedQty - r.plannedQty
      : null;
  const dv =
    r.plannedTotalUsd != null && r.usedTotalUsd != null
      ? r.usedTotalUsd - r.plannedTotalUsd
      : null;
  return (
    <tr className="ledger-row" onClick={onToggle} title="Click for draws, lots and the override editor">
      <td title={`${r.part}${r.refs ? ` — ${r.refs}` : ""}${r.lcsc ? ` — ${r.lcsc}` : ""}`}>
        <span className="ledger-caret">{open ? "▾" : "▸"}</span>
        <span className="mono">{r.part}</span>
        {r.eff?.dropped ? <span className="pill neutral">dropped</span> : null}
        {r.eff?.overridden ? <span className="pill warn">override</span> : null}
      </td>
      <td className="num">{r.plannedQty == null ? "—" : r.plannedQty.toLocaleString()}</td>
      <td className="num">
        {r.usedQty == null ? "—" : r.usedQty.toLocaleString()}
        {r.writtenOff > 0 ? (
          <span className="muted dim" title="written off as attrition on top of the draws">
            {" "}
            +{r.writtenOff}
          </span>
        ) : null}
      </td>
      <td className="num">
        {dq == null ? (
          <span className="dim">—</span>
        ) : (
          <span className={`pill ${Math.abs(dq) < 0.5 ? "ok" : dq > 0 ? "err" : "warn"}`}>
            {dq > 0 ? `+${dq.toLocaleString()}` : dq.toLocaleString()}
          </span>
        )}
      </td>
      <td className="num">{r.plannedUnitUsd == null ? "—" : price(r.plannedUnitUsd)}</td>
      <td className="num">{r.usedUnitUsd == null ? "—" : price(r.usedUnitUsd)}</td>
      <td className="num">{r.plannedTotalUsd == null ? "—" : plain(r.plannedTotalUsd)}</td>
      <td className="num">{r.usedTotalUsd == null ? "—" : plain(r.usedTotalUsd)}</td>
      <td className="num">
        {dv == null ? (
          <span className="dim">—</span>
        ) : (
          <span
            className={`pill ${Math.abs(dv) < 0.01 ? "ok" : dv > 0 ? "warn" : "neutral"}`}
          >
            {dv > 0 ? "+" : ""}
            {plain(dv)}
          </span>
        )}
      </td>
      <td>
        <SourceCell r={r} />
      </td>
    </tr>
  );
}

/** Where the actual figures came from — evidence vs claim, named per row. */
function SourceCell({ r }: { r: MatRow }) {
  const pills: { text: string; tone: string; title: string }[] = [];
  const anyReported = r.cons.some((c) => c.lots.some((l) => l.source === "reported"));
  const bases = new Set(r.cons.map((c) => c.basis));
  if (anyReported)
    pills.push({
      text: "JLC invoice",
      tone: "ok",
      title: "Measured consumption reported by JLCPCB's own invoice, bound to purchase lots.",
    });
  else if (bases.has("measured"))
    pills.push({ text: "measured", tone: "ok", title: "A measured draw." });
  if (bases.has("manual"))
    pills.push({ text: "manual draw", tone: "neutral", title: "Entered by hand." });
  if (bases.has("allocated") || bases.has("bom"))
    pills.push({
      text: "BOM average",
      tone: "warn",
      title: "Drawn from the whole BOM at the pool's moving average — allocated, not measured.",
    });
  if (r.writtenOff > 0)
    pills.push({ text: "write-off", tone: "warn", title: "Attrition charged to this batch." });
  if (r.cons.length === 0 && r.plannedQty != null && !r.eff?.dropped)
    pills.push({
      text: "not drawn",
      tone: "warn",
      title: "Planned, but no pool draw recorded yet — batch not drawn, or a miss.",
    });
  if (r.eff == null && r.cons.length > 0)
    pills.push({
      text: "not planned",
      tone: "err",
      title: "Drawn without appearing in the batch's BOM — rework or an extra.",
    });
  return (
    <>
      {pills.map((p) => (
        <span key={p.text} className={`pill ${p.tone}`} title={p.title}>
          {p.text}
        </span>
      ))}
    </>
  );
}

function MatDetail({
  r,
  cur,
  busy,
  overrideDraft,
  setOverrideDraft,
  onOverride,
  onRemoveDraw,
  onRemoveAdj,
}: {
  r: MatRow;
  cur: string;
  busy: boolean;
  overrideDraft: string;
  setOverrideDraft: (s: string) => void;
  onOverride: (raw: string) => void;
  onRemoveDraw: (id: number) => void;
  onRemoveAdj: (a: StockAdjustment) => void;
}) {
  return (
    <div className="ledger-panel">
      {r.eff && !r.eff.dropped && (
        <div className="btn-row">
          <span className="muted">
            Planned unit at run date: {price(r.eff.unit_price, cur)}
            {r.eff.override_note ? ` — ${r.eff.override_note}` : ""}. Final price override (in{" "}
            {cur}; blank + Apply clears it):
          </span>
          <input
            className="text num-input"
            placeholder="unit price"
            value={overrideDraft}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setOverrideDraft(e.target.value)}
          />
          <button
            className="btn btn-sm"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              onOverride(overrideDraft);
            }}
          >
            Apply
          </button>
        </div>
      )}
      {r.cons.length > 0 ? (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Drawn</th>
                <th className="num">Qty</th>
                <th className="num">Unit (USD)</th>
                <th className="num">Total (USD)</th>
                <th>Basis / lot</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {r.cons.flatMap((c) => {
                const head = (
                  <tr key={`c${c.id}`}>
                    <td className="muted">{c.consumed_at?.slice(0, 10) || "—"}</td>
                    <td className="num">{c.qty}</td>
                    <td className="num">{c.unit_cost_usd.toFixed(6)}</td>
                    <td className="num">{c.total_usd.toFixed(4)}</td>
                    <td>
                      <span
                        className={`pill ${
                          c.basis === "measured" ? "ok" : c.basis === "allocated" ? "warn" : "neutral"
                        }`}
                      >
                        {c.basis}
                      </span>
                    </td>
                    <td className="ctr">
                      <button
                        className="btn btn-sm btn-danger"
                        disabled={busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          onRemoveDraw(c.id);
                        }}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                );
                const lots =
                  c.lots.length >= 2
                    ? c.lots.map((lot) => (
                        <tr key={`c${c.id}-l${lot.id}`}>
                          <td className="dim">lot {lot.purchase_order || lot.ext_ref}</td>
                          <td className="num dim">{lot.qty}</td>
                          <td className="num dim">{lot.unit_cost_usd.toFixed(6)}</td>
                          <td className="num dim">{lot.total_usd.toFixed(4)}</td>
                          <td>
                            <span className={`pill ${lot.source === "reported" ? "ok" : "warn"}`}>
                              {lot.source}
                            </span>
                          </td>
                          <td />
                        </tr>
                      ))
                    : [];
                return [head, ...lots];
              })}
              {r.adjs.map((a) => (
                <tr key={`a${a.id}`}>
                  <td className="muted">{a.adjusted_at?.slice(0, 10) || "—"}</td>
                  <td className="num">{a.qty_delta}</td>
                  <td className="num dim">{a.unit_cost_usd ?? "avg"}</td>
                  <td className="num dim">—</td>
                  <td>
                    <span className="pill warn" title={a.note}>
                      {a.reason}
                    </span>
                  </td>
                  <td className="ctr">
                    <button
                      className="btn btn-sm btn-danger"
                      disabled={busy}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveAdj(a);
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No draws recorded for this part.</p>
      )}
    </div>
  );
}
