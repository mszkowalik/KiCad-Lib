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
  addRunSubstitution,
  addStockAdjustment,
  consumeFromBom,
  deleteConsumption,
  deleteRunSubstitution,
  deleteStockAdjustment,
  errorMessage,
  getAllStockAdjustments,
  getBatchSupply,
  getDetectedSubstitutions,
  getRunConsumption,
  getRunSubstitutions,
  isAbortError,
  setUsedQty,
  updateRun,
  updateRunSubstitution,
  type ConsumptionRow,
  type RunEffectiveLine,
  type RunInfo,
  type BatchSupplyRow,
  type RunSubstitution,
  type StockAdjustment,
  type UnusedPosition,
  type SubstitutionCandidate,
} from "../../api";
import ComponentPickDialog from "../ComponentPickDialog";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";
import SupplyCoverage from "./SupplyCoverage";
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
  /** recorded substitutions covering any of this row's positions */
  subs: RunSubstitution[];
  /** bought straight for this batch, outside the pool — cost is known */
  supplied?: BatchSupplyRow;
  /** this position's part was replaced; the row beneath carries what went on */
  substitutedTo?: string;
  /** this row IS the replacement, standing in for that part */
  standsInFor?: string;
  /** the substitution that put this row here */
  sub?: RunSubstitution;
  /** changes the supplier's BOM reports here that nobody has recorded */
  cands: SubstitutionCandidate[];
  /** the part the USED side of this row is really made of, when a substitution
   *  put a different one on the board */
  usedAs: string;
  /** the supplier's BOM for this batch does not carry it and nothing drew it */
  unused: boolean;
}

/** A BOM line names several positions: "C14, C15, C16". */
function splitRefs(refs: string | null | undefined): string[] {
  return (refs ?? "").replace(/;/g, ",").split(",").map((x) => x.trim()).filter(Boolean);
}

/** What to call the two sides of a substitution.
 *
 *  The backend resolves `*_name` to the library's manufacturer part number when
 *  the part is in the library, and otherwise to the string that was entered.
 *  An LCSC code names nothing to a reader (user 2026-09-19).
 *
 *  `supply` is the last resort and the best one when it hits: a substitution's
 *  `fitted_mpn` is the supplier's own comment on its BOM line and is often the
 *  VALUE — batch 8's reads "100uF" — while the invoice line carries the real
 *  part number.
 */
function subName(
  x: RunSubstitution, side: "fitted" | "specified", supply: BatchSupplyRow[] = [],
): string {
  const lcsc = side === "fitted" ? x.fitted_lcsc : x.specified_lcsc;
  const mpn = side === "fitted" ? x.fitted_mpn : x.specified_mpn;
  const named = side === "fitted" ? x.fitted_name : x.specified_name;
  const inLib = side === "fitted" ? x.fitted_in_library : x.specified_in_library;
  // The library wins outright. Only when the part is NOT in it may a better
  // string be preferred over the one that was entered.
  if (inLib && named) return named;
  const bought = supply.find((b) =>
    (b.lcsc && lcsc && b.lcsc.toUpperCase() === lcsc.toUpperCase())
    || (b.mpn && mpn && b.mpn.toUpperCase() === mpn.toUpperCase()));
  return bought?.mpn || named || mpn || lcsc || "";
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
  const [subs, setSubs] = useState<RunSubstitution[]>([]);
  const [cands, setCands] = useState<SubstitutionCandidate[]>([]);
  const [unused, setUnused] = useState<UnusedPosition[]>([]);
  // Parts bought straight for this batch. They never enter the pool, so no draw
  // reports them and nothing else on this tab can see them.
  const [supply, setSupply] = useState<BatchSupplyRow[]>([]);
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
    getRunSubstitutions(run.id, signal)
      .then((r) => { setSubs(r.substitutions); setUnused(r.unused); })
      .catch(() => { setSubs([]); setUnused([]); });
    getBatchSupply(run.id, signal)
      .then((r) => setSupply(r.rows))
      .catch(() => setSupply([]));
    getDetectedSubstitutions(signal)
      .then((d) => setCands(d.candidates.filter((c) => c.run_id === run.id)))
      .catch(() => setCands([]));
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
    let out: MatRow[] = [];
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
        subs: [],
        supplied: undefined,
        cands: [],
        usedAs: "",
        unused: false,
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
          subs: [],
        supplied: undefined,
          cands: [],
          usedAs: "",
          unused: false,
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
          subs: [],
        supplied: undefined,
          cands: [],
          usedAs: "",
          unused: false,
        });
      }
    }

    // A substitution is matched to the row it REPLACES: by any of the
    // positions it names, or by the part the design specifies there. Both are
    // needed — a drawn-but-not-planned row has no refs at all, and a planned
    // row whose part was swapped no longer carries the fitted code.
    const hits = (refs: string, lcsc: string, subRefs: string, subLcsc: string) => {
      const mine = splitRefs(refs);
      if (mine.length && splitRefs(subRefs).some((x) => mine.includes(x))) return true;
      // BOTH sides must be named. A row with no LCSC matched every
      // substitution that named no fitted part, which put "not fitted" on nine
      // rows at once.
      return !!subLcsc && !!lcsc && norm(subLcsc) === norm(lcsc);
    };
    for (const r of out) {
      r.subs = subs.filter(
        (x) => hits(r.refs, r.lcsc, x.designator, x.specified_lcsc)
               || (!!x.fitted_lcsc && !!r.lcsc && norm(x.fitted_lcsc) === norm(r.lcsc)));
      r.cands = cands.filter((c) => hits(r.refs, r.lcsc, c.designator, c.specified_lcsc));
      r.unused = r.subs.length === 0
        && unused.some((u) => (!!r.lcsc && norm(u.lcsc) === norm(r.lcsc))
                              || (!!r.refs && norm(u.refs) === norm(r.refs)));
    }

    // A FULLY substituted position is TWO rows, the design's and the one really
    // fitted, and the substitute sits directly under it (user 2026-09-19).
    //
    // They used to be merged into one. The reason was sound — left apart, the
    // design's part read "not drawn" and the fitted part read "not planned", so
    // a batch built correctly showed two faults. Stating the zero fixes that
    // without hiding anything: the design's row says plainly that NOTHING was
    // used against it, and the row beneath says what went there instead. Merged,
    // the two parts' quantities and prices were added together and neither
    // could be read on its own.
    //
    // Only when the substitution covers EVERY position on the line. Replacing
    // one LED of six means both parts were genuinely used.
    const standIns: { after: string; row: MatRow }[] = [];
    for (const r of out) {
      if (r.subs.length === 0 || !r.lcsc) continue;
      const sub = r.subs.find((x) => norm(x.specified_lcsc) === norm(r.lcsc));
      if (!sub || (!sub.fitted_lcsc && !sub.fitted_mpn)) continue;
      const mine = splitRefs(r.refs);
      const covered = splitRefs(sub.designator);
      if (mine.length > 0 && !mine.every((x) => covered.includes(x))) continue;

      // Nothing was used against the DESIGN's part. Say so, rather than leaving
      // it blank for someone to fill in — a typed quantity here would write a
      // draw for a part that never left our pool.
      r.usedQty = 0;
      r.usedTotalUsd = 0;
      r.usedUnitUsd = null;
      r.substitutedTo = sub.fitted_lcsc || sub.fitted_mpn;

      const fitted = out.find(
        (o) => o !== r && !!o.lcsc && norm(o.lcsc) === norm(sub.fitted_lcsc));
      if (fitted) {
        fitted.standsInFor = r.part;
        fitted.sub = sub;
        standIns.push({ after: r.key, row: fitted });
        continue;
      }
      // No row of its own: the fitted part is not in the design's BOM and has
      // no draw, because the batch bought it outright. That is batch 8's C7223
      // — the row has to be made, or the position it filled is invisible.
      // Name it after what was BOUGHT. A substitution's `fitted_mpn` is the
      // supplier's own comment on the BOM line and is often the value, not the
      // part — batch 8's reads "100uF", which names nothing.
      const boughtAs = supply.find((bs) =>
        (bs.lcsc && sub.fitted_lcsc && bs.lcsc.toUpperCase() === sub.fitted_lcsc.toUpperCase())
        || (bs.mpn && sub.fitted_mpn && bs.mpn.toUpperCase() === sub.fitted_mpn.toUpperCase()));
      standIns.push({
        after: r.key,
        row: {
          key: `standin:${r.key}:${sub.fitted_lcsc || sub.fitted_mpn}`,
          part: boughtAs?.mpn || sub.fitted_lcsc || sub.fitted_mpn,
          refs: sub.designator || r.refs,
          lcsc: sub.fitted_lcsc || "",
          eff: null, cons: [], adjs: [],
          plannedQty: null, plannedUnitUsd: null, plannedTotalUsd: null,
          usedQty: null, usedUnitUsd: null, usedTotalUsd: null,
          writtenOff: 0, subs: [sub], supplied: undefined, cands: [],
          usedAs: "", unused: false,
          standsInFor: r.part, sub,
        },
      });
    }
    // Put each stand-in directly under the position it filled.
    const moved = new Set(standIns.map((x) => x.row.key));
    const ordered: MatRow[] = [];
    for (const r of out) {
      if (moved.has(r.key)) continue;
      ordered.push(r);
      for (const x of standIns) if (x.after === r.key) ordered.push(x.row);
    }
    out = ordered;

    for (const r of out) {
      if (r.cons.length) {
        r.usedQty = r.cons.reduce((s, c) => s + c.qty, 0);
        r.usedTotalUsd = r.cons.reduce((s, c) => s + c.total_usd, 0);
        r.usedUnitUsd = r.usedQty ? r.usedTotalUsd / r.usedQty : null;
      }
      // The design's part was replaced. Its zero is the answer; the supply and
      // the draws belong to the row standing in for it, below.
      if (r.substitutedTo) continue;

      // Match through the SUBSTITUTION. The row is keyed by what the design
      // specifies; the batch bought what was actually fitted, which is a
      // different part number by definition — C110548 on the row, C7223 on the
      // invoice. Keying on the row alone finds nothing precisely when a
      // substitution is what made the batch buy the part.
      const ids = new Set(
        [r.lcsc, r.part,
         ...r.subs.flatMap((x) => [x.fitted_lcsc, x.fitted_mpn])]
          .filter(Boolean).map((v) => (v as string).toUpperCase()),
      );
      const bought = supply.find((b) =>
        (b.lcsc && ids.has(b.lcsc.toUpperCase()))
        || (b.mpn && ids.has(b.mpn.toUpperCase())));
      if (bought) {
        r.supplied = bought;
        if (r.usedQty == null) r.usedQty = bought.qty;
        if (r.usedTotalUsd == null) {
          r.usedTotalUsd = bought.amount_usd;
          r.usedUnitUsd = bought.unit_usd;
        }
      }

      // A substituted position with no draw still has a known used quantity —
      // the substitution says so — and leaving it blank invited someone to
      // type one, which would write a draw for a part that never left our
      // pool. Two cases, and they differ:
      if (r.cons.length > 0 || r.subs.length === 0) continue;
      const empty = r.subs.find(
        (x) => !x.fitted_lcsc && !x.fitted_mpn && x.qty_per_device === 0);
      if (empty) {
        // Nothing went there. Nothing is planned for it either, exactly as a
        // dropped line reads — otherwise the batch shows a shortfall it chose.
        r.plannedQty = 0;
        r.plannedUnitUsd = null;
        r.plannedTotalUsd = null;
        r.usedQty = 0;
        continue;
      }
      const theirs = r.subs.find((x) => x.supplied_by && x.supplied_by !== "pool");
      if (theirs) {
        // The position WAS populated, with the supplier's own part. A stand-in
        // row has no plan of its own — it is not in the design — so its
        // quantity comes from what was bought, filled just above.
        if (!r.standsInFor) r.usedQty = r.plannedQty;
        r.usedAs = theirs.fitted_lcsc || theirs.fitted_mpn;
      }
      // The money used to stay blank here, because a supplier's parts were one
      // lump inside the assembly fee and could not be split out. Itemising that
      // lump splits it exactly (decision 0041), so when the batch bought this
      // part directly the cost is known and belongs in the row.
    }
    return out;
  }, [run.effective, consumption, adjs, subs, cands, unused, supply]);

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

      {/* The reconciliation sits ABOVE the list, because it is the thing that
          says whether the list below can be trusted — a position the supplier
          met and we ALSO drew reads as an ordinary row down there. */}
      <div className="card pad">
        <h3 className="card-title">Supply coverage</h3>
        <SupplyCoverage runId={run.id} />
      </div>

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
                  supply={supply}
                  open={open === r.key}
                  busy={busy}
                  onSetUsed={(qty) =>
                    act(async () => {
                      const c = r.cons[0];
                      await setUsedQty(run.id, {
                        component_id: c?.component_id ?? null,
                        mpn: c?.mpn || r.part,
                        lcsc: c?.lcsc || r.lcsc || "",
                        qty,
                      });
                    })
                  }
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
                        supply={supply}
                        overrideDraft={overrideDraft}
                        setOverrideDraft={setOverrideDraft}
                        onOverride={(raw) => r.eff && applyOverride(r.eff, raw)}
                        onRecordSub={(designator, fittedPart, specified, note, source,
                                      evidence, supplierRef, qtyPerDevice, suppliedBy,
                                      fittedComponentId) =>
                          void act(() =>
                            addRunSubstitution(run.id, {
                              designator,
                              supplier_designator: supplierRef,
                              specified_lcsc: specified,
                              fitted_lcsc: /^C\d+$/i.test(fittedPart) ? fittedPart : "",
                              fitted_mpn: /^C\d+$/i.test(fittedPart) ? "" : fittedPart,
                              fitted_component_id: fittedComponentId,
                              qty_per_device: qtyPerDevice,
                              source,
                              supplied_by: suppliedBy,
                              evidence,
                              note,
                            }),
                          )
                        }
                        onDeleteSub={(x) => void act(() => deleteRunSubstitution(x.id))}
                        onDesignUpdated={(x, v) =>
                          void act(() => updateRunSubstitution(x.id, { design_updated: v }))
                        }
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
        <div className="field-grid">
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

function MatTr({
  r,
  open,
  busy,
  supply,
  onToggle,
  onSetUsed,
}: {
  r: MatRow;
  open: boolean;
  busy: boolean;
  /** so a substitution pill can name the part the batch really bought */
  supply: BatchSupplyRow[];
  onToggle: () => void;
  onSetUsed: (qty: number) => void;
}) {
  // A position whose part was replaced is NOT short. Its used side is zero
  // because everything went to the row beneath it, and printing -800 there
  // reads as a shortfall on a batch that was built correctly — which is the
  // objection that kept the two rows merged in the first place.
  const dq =
    r.substitutedTo || (r.plannedQty == null || r.usedQty == null)
      ? null
      : r.usedQty - r.plannedQty;
  const dv =
    !r.substitutedTo && r.plannedTotalUsd != null && r.usedTotalUsd != null
      ? r.usedTotalUsd - r.plannedTotalUsd
      : null;
  return (
    <tr className="ledger-row" onClick={onToggle} title="Click for draws, lots and the override editor">
      <td title={`${r.part}${r.refs ? ` — ${r.refs}` : ""}${r.lcsc ? ` — ${r.lcsc}` : ""}`}>
        <span className="ledger-caret">{open ? "▾" : "▸"}</span>
        <span className="mono">{r.part}</span>
        {r.eff?.dropped ? <span className="pill neutral">dropped</span> : null}
        {r.eff?.overridden ? <span className="pill warn">override</span> : null}
        {r.subs.map((x) => {
          // The same substitution touches two rows: the part the design asks
          // for, and the part that actually went on. Saying "→ C7223" on the
          // C7223 row reads as though it were replaced by itself.
          const isFitted = norm(x.fitted_lcsc) === norm(r.lcsc) && !!r.lcsc;
          // Quantity zero with nothing named is "left empty", not an arrow
          // pointing at no part.
          if (!x.fitted_lcsc && !x.fitted_mpn && x.qty_per_device === 0)
            return (
              <span key={x.id} className="pill neutral"
                    title={`${x.designator} was left empty on this batch`
                           + (x.note ? ` — ${x.note}` : "")}>
                not fitted
              </span>
            );
          return (
            <span key={x.id} className="pill warn"
                  title={`${x.designator}: ${subName(x, "specified", supply)} was specified, `
                         + `${subName(x, "fitted", supply)} was fitted`
                         + (x.fitted_lcsc ? ` (${x.fitted_lcsc})` : "")
                         + (x.design_updated ? "" : " — the design still says otherwise")}>
              {/* ONE GLYPH, not a word. This cell already holds a part number,
                  a pill cannot be ellipsised, and the column is a percentage —
                  so a worded marker is not shortened, it is cut off, and the
                  reader cannot see the row was substituted at all (user report
                  2026-09-19). Same reasoning as `actorMark` in Ui.tsx. The two
                  rows sit together and both print their part number; the glyph
                  only has to say which of them this row is, and the hover says
                  the rest. */}
              {isFitted ? "↳" : "⇄"}
            </span>
          );
        })}
        {r.cands.length > 0 && r.subs.length === 0 ? (
          <span className="pill err"
                title="the supplier's own BOM says this position changed, and nobody has recorded it">
            supplier changed it
          </span>
        ) : null}
      </td>
      <td className="num">{r.plannedQty == null ? "—" : r.plannedQty.toLocaleString()}</td>
      <td className="num" onClick={(e) => e.stopPropagation()}
          title={r.usedAs ? `${r.usedAs} was fitted here` : undefined}>
        <UsedCell r={r} busy={busy} onSet={onSetUsed} />
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
      <td className="num"
          title={r.usedAs ? `the used side is ${r.usedAs}, fitted in place of ${r.part}` : undefined}>
        {r.usedUnitUsd == null ? "—" : price(r.usedUnitUsd)}
      </td>
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
        {r.unused ? (
          <span
            className="pill err unused-flag"
            title={`JLCPCB's own BOM for this batch does not carry ${r.lcsc || r.part}, and `
                   + "nothing drew it — so it did not go on the board. Record what was "
                   + "fitted instead, or record that nothing was."}
          >
            ⚠ not on the board
          </span>
        ) : null}
      </td>
    </tr>
  );
}

/**
 * How much of this part the batch used — typed in, not derived.
 *
 * A part JLC reported on its own invoice is READ-ONLY here: that figure is the
 * supplier's measurement of its own consigned stock, and retyping it would put
 * a guess where an observation is. Everything else — enclosures, antennas,
 * cartons — is precisely what no supplier reports, so the number can only come
 * from somebody counting it at the end of production.
 *
 * The field is absolute and idempotent, so correcting it later is the same
 * action as entering it, and no compensating adjustment is ever needed.
 */
function UsedCell({ r, busy, onSet }: { r: MatRow; busy: boolean; onSet: (q: number) => void }) {
  const measured = r.cons.some((c) => c.basis === "measured");
  const [draft, setDraft] = useState<string | null>(null);
  if (measured) {
    return (
      <span title="Reported by JLCPCB's own invoice — a measurement, not ours to retype">
        {r.usedQty == null ? "—" : r.usedQty.toLocaleString()}
      </span>
    );
  }
  // A substituted position's used quantity follows from the substitution. Typed
  // here it would write a draw against the part the design names — the one that
  // did NOT go on the board — and take it out of stock.
  if (r.subs.length > 0) {
    return (
      <span title={r.usedAs
        ? `${r.usedAs} was fitted here. Correct it by editing the substitution.`
        : "Nothing was fitted at this position on this batch."}>
        {r.usedQty == null ? "—" : r.usedQty.toLocaleString()}
      </span>
    );
  }
  const shown = draft ?? (r.usedQty == null ? "" : String(r.usedQty));
  const commit = () => {
    if (draft === null) return;
    const next = draft.trim() === "" ? 0 : Number(draft);
    setDraft(null);
    if (!Number.isFinite(next) || next < 0) return;
    if (next === (r.usedQty ?? 0)) return;
    onSet(next);
  };
  return (
    <input
      className="text qty-cell"
      inputMode="decimal"
      disabled={busy}
      value={shown}
      placeholder="—"
      title="What this batch actually used. Type the counted quantity; blank or 0 removes the draw."
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") setDraft(null);
      }}
    />
  );
}

/** Where the actual figures came from — evidence vs claim, named per row. */
function SourceCell({ r }: { r: MatRow }) {
  const pills: { text: string; tone: string; title: string }[] = [];
  const anyReported = r.cons.some((c) => c.lots.some((l) => l.source === "reported"));
  const bases = new Set(r.cons.map((c) => c.basis));
  if (anyReported)
    pills.push({
      // Short: this cell can hold an evidence pill AND a supply pill, and a
      // pill cannot be ellipsised. The title carries the sentence.
      text: "JLC",
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
  // Who provided a substituted part, from the substitution itself. It used to
  // be inferred from the absence of a draw, which is wrong in both directions:
  // a part WE supplied and never drew is a missing draw, and reading that as
  // supplier-supplied would hide it.
  // ONE supply pill. `batch-supplied` and `supplier-supplied` were both true on
  // an itemised factory position — the same fact twice — in a cell that cannot
  // shorten a pill, so the second was simply cut off (user report 2026-09-19).
  const supplied = r.subs.find((x) => x.supplied_by && x.supplied_by !== "pool");
  if (r.supplied || supplied) {
    // A pool DRAW plus batch supply on the same row is the mixed case, whether
    // or not a substitution recorded it: some came out of our stock and the
    // factory topped up the rest.
    const partly = supplied?.supplied_by === "both" || (!!r.supplied && r.cons.length > 0);
    pills.push({
      // SHORT. This cell holds several pills and a pill cannot be ellipsised,
      // so a long label is not truncated — it is cut off.
      text: partly ? "ours + factory's"
        : supplied ? "factory's parts"
        : "batch's own",
      tone: "neutral",
      title: (supplied
          ? `${subName(supplied, "fitted")} came off the factory's own shelf`
            + (supplied.supplier_source ? ` (JLC: ${supplied.supplier_source})` : "")
            + (partly
               ? ". Part of the position came from our pool and the factory topped up the rest."
               : ". Its cost is charged to this batch, so no draw comes out of our pool.")
          : "Bought straight for this batch, so it never entered the shared pool.")
        + (r.supplied
           ? ` ${r.supplied.qty} on ${r.supplied.suppliers.join(", ") || "an invoice"}`
             + `, ${r.supplied.amount_usd.toFixed(2)} USD.`
           : ""),
    });
  }
  // "not fitted" already answers why nothing was drawn; saying both makes a
  // recorded decision look like an open question.
  const notFitted = r.subs.some(
    (x) => !x.fitted_lcsc && !x.fitted_mpn && x.qty_per_device === 0);
  if (r.cons.length === 0 && r.plannedQty != null && !r.eff?.dropped && !supplied
      && !notFitted)
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

/** Substituting a part, from the row it belongs to.
 *
 *  Scope is the only real choice: ONE position, or every position this part
 *  sits at. A BOM row already groups the part's designators, so "all of them"
 *  is just the row's whole `refs` string — `RunSubstitution` splits it, and
 *  either answer is one row rather than a row per reference.
 *
 *  What the supplier already reported is offered first. JLC changing a line is
 *  evidence, not a decision, so it is proposed and recorded with a click, never
 *  written on its own.
 */
function SubstitutePanel({
  r, busy, supply, onRecord, onDelete, onDesignUpdated,
}: {
  r: MatRow;
  busy: boolean;
  /** so a part can be named by what the batch really bought */
  supply: BatchSupplyRow[];
  onRecord: (designator: string, fitted: string, specified: string, note: string,
             source: string, evidence: string, supplierRef: string, qty: number,
             suppliedBy: string, fittedComponentId: number | null) => void;
  onDelete: (s: RunSubstitution) => void;
  onDesignUpdated: (s: RunSubstitution, v: boolean) => void;
}) {
  const refs = splitRefs(r.refs);
  const [openForm, setOpenForm] = useState(false);
  const [picking, setPicking] = useState(false);
  // Which positions the substitution covers. Checkboxes rather than a
  // dropdown: the common answer is "all of them", the next most common is "all
  // but one", and neither is expressible in a single-choice control.
  const [scope, setScope] = useState<Set<string>>(new Set());
  const [fitted, setFitted] = useState<{ id: number | null; name: string }>(
    { id: null, name: "" });
  // Who provided the part. NOT inferred from the absence of a draw: a part we
  // supplied and never drew is a missing draw, and reading that as
  // supplier-supplied would hide it.
  const [suppliedBy, setSuppliedBy] = useState("pool");
  // A free-text part stops being allowed the moment the answer changes to "our
  // stock", so the choice it produced must go with it.
  const changeSupply = (v: string) => {
    setSuppliedBy(v);
    if (v === "pool" && fitted.id === null) setFitted({ id: null, name: "" });
  };
  const [note, setNote] = useState("");

  // Every position unless the reader says otherwise: substituting a part
  // usually means substituting it everywhere it sits.
  const picked = refs.filter((x) => !scope.has(x));
  const covers = refs.length ? picked : [];
  // The button names the scope, but never by listing six designators — it grew
  // wider than the form on the LED row.
  const scopeLabel =
    refs.length === 0
      ? (r.refs || r.part)
      : covers.length === refs.length
        ? (refs.length > 1 ? `all ${refs.length} positions` : refs[0])
        : covers.join(", ");
  const toggle = (ref: string) =>
    setScope((prev) => {
      const next = new Set(prev);
      if (next.has(ref)) next.delete(ref);
      else next.add(ref);
      return next;
    });
  return (
    <div className="sub-panel">
      <div className="btn-row">
        <b>Substitution</b>
        <span className="muted">
          What went on the board here, when it is not what the design specifies. Recorded on
          this batch only — the schematic is never changed from here.
        </span>
      </div>

      {r.unused ? (
        <div className="btn-row">
          <span className="pill err">⚠ not on the board</span>
          <span className="muted">
            JLCPCB&rsquo;s BOM for this batch does not carry{" "}
            <span className="mono">{r.lcsc || r.part}</span> and nothing drew it. Say what
            went there instead, or that nothing did.
          </span>
          <button className="btn btn-sm" disabled={busy}
                  title="Record that this position was left empty on this batch — history,
                         not an error. The early batches shipped without cartons."
                  onClick={(e) => {
                    e.stopPropagation();
                    onRecord(r.refs || r.part, "", r.lcsc, "Not fitted on this batch.",
                             "us", "", "", 0, "", null);
                  }}>
            Nothing was fitted
          </button>
        </div>
      ) : null}

      {r.subs.length > 0 ? (
        <>
        {/* One line, because the two pills answer two questions that read as
            one. Without it the reader has to infer both what "factory decided"
            is about and why a second pill follows it. */}
        <p className="muted">
          What went on this position instead. The first tag says <b>where the change was
          defined</b> — on the supplier's order or here — and the second says <b>whose
          parts</b> were used. They are independent: a part chosen on the order can still
          come out of our own stock.
        </p>
        <ul className="tight">
          {r.subs.map((x) => (
            <li key={x.id}>
              <span className="mono">{x.designator}</span>:{" "}
              <span className="mono">{subName(x, "specified", supply) || "—"}</span> →{" "}
              <span className="mono">
                {subName(x, "fitted", supply) || "nothing — left empty"}
              </span>{" "}
              {/* Two pills, two different questions: who DECIDED the change and
                  who PROVIDED the part. They were "their change" and "they
                  supplied it", which asked the reader to work out both the
                  antecedent and which question was being answered (user
                  2026-09-19). */}
              <span className={"pill " + (x.source === "supplier" ? "warn" : "neutral")}
                    title={x.source === "supplier"
                      ? "This part was chosen on the supplier's order, not in the schematic — "
                        + "usually by us, while selecting parts when placing it. The platform "
                        + "read it from their BOM, which is why the design never caught up."
                        + (x.evidence ? ` Evidence: ${x.evidence}` : "")
                      : "Recorded here by hand, rather than read from the supplier's BOM."}>
                {x.source === "supplier" ? "chosen in the order" : "recorded here"}
              </span>{" "}
              <span className="pill neutral"
                    title={(x.supplied_by === "supplier"
                        ? "The factory used its own stock. The cost is on the assembly invoice, "
                          + "so no draw comes out of our pool."
                        : x.supplied_by === "both"
                        ? "Part of this position came out of our pool and the factory topped up "
                          + "the rest from its own stock. Both are charged, each for its share."
                        : x.supplied_by === "pool"
                        ? "The parts came out of our own stock, so a draw should exist for them."
                        : "Nobody has recorded where these parts came from.")
                      + (x.supplier_source ? ` JLC calls it "${x.supplier_source}".` : "")}>
                {x.supplied_by === "supplier" ? "factory's parts"
                  : x.supplied_by === "both" ? "part ours, part factory's"
                  : x.supplied_by === "pool" ? "our parts"
                  : "parts: source unrecorded"}
              </span>{" "}
              <label className="check-inline"
                     title={x.design_updated
                       ? "the schematic specifies the fitted part"
                       : "the schematic still specifies the superseded part — this stays a finding on the Stock page"}>
                <input type="checkbox" checked={x.design_updated} disabled={busy}
                       onClick={(e) => e.stopPropagation()}
                       onChange={(e) => onDesignUpdated(x, e.target.checked)} />
                design updated
              </label>{" "}
              <button className="btn btn-sm btn-danger" disabled={busy}
                      onClick={(e) => { e.stopPropagation(); onDelete(x); }}>Remove</button>
              {x.note ? <div className="muted dim">{x.note}</div> : null}
            </li>
          ))}
        </ul>
        </>
      ) : null}

      {r.cands.length > 0 ? (
        <ul className="tight">
          {r.cands.map((c) => (
            <li key={`${c.order}:${c.supplier_designator}`}>
              <span className="pill err">supplier changed it</span>{" "}
              <span className="mono">{c.designator}</span>:{" "}
              <span className="mono">{c.specified_lcsc}</span> →{" "}
              <span className="mono">{c.fitted_lcsc}</span>{" "}
              <span className={"pill " + (c.match_type === "update" ? "warn" : "neutral")}
                    title={c.match_type === "update"
                      ? "JLC says the line was changed by hand, not auto-matched"
                      : "JLC's matcher resolved this from the code we uploaded"}>
                {c.match_type}
              </span>{" "}
              {c.supplied_by ? (
                <span className="pill neutral"
                      title={(c.supplied_by === "supplier"
                          ? "The factory would use its own stock; the cost lands on the assembly "
                            + "invoice and no draw comes out of our pool."
                          : c.supplied_by === "both"
                          ? "Part from our pool, the rest topped up from the factory's own stock."
                          : "From our own stock, so a draw should exist for it.")
                        + ` JLC calls it "${c.supplier_source}".`}>
                  {c.supplied_by === "supplier" ? "factory's parts"
                    : c.supplied_by === "both" ? "part ours, part factory's" : "our parts"}
                </span>
              ) : null}{" "}
              <span className="muted">{c.fitted_describe}</span>{" "}
              <button className="btn btn-sm" disabled={busy}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRecord(c.designator, c.fitted_lcsc, c.specified_lcsc, "",
                                 "supplier", c.evidence, c.supplier_designator,
                                 c.qty_per_device, c.supplied_by, null);
                      }}>Record</button>
            </li>
          ))}
        </ul>
      ) : null}

      {openForm ? (
        <div className="btn-row sub-add" onClick={(e) => e.stopPropagation()}>
          {refs.length > 0 ? (
            <span className="ref-picks" title="Which positions were substituted">
              {refs.map((x) => (
                <label key={x} className="check-inline">
                  <input type="checkbox" checked={!scope.has(x)} onChange={() => toggle(x)} />
                  <span className="mono">{x}</span>
                </label>
              ))}
            </span>
          ) : null}
          <button className="btn btn-sm" onClick={() => setPicking(true)}>
            {fitted.name ? `Fitted: ${fitted.name}` : "Choose the part fitted…"}
          </button>
          <select className="text" value={suppliedBy}
                  onChange={(e) => changeSupply(e.target.value)}
                  title="Whose shelf it came off. A part the supplier provided is billed
                         inside the assembly fee, so no pool draw exists for it.">
            <option value="pool">from our stock</option>
            <option value="supplier">supplied by the supplier</option>
            <option value="both">partly each</option>
          </select>
          <input className="text" placeholder="Why" value={note}
                 onChange={(e) => setNote(e.target.value)} />
          <button className="btn btn-sm btn-primary"
                  disabled={busy || !fitted.name.trim() || (refs.length > 0 && covers.length === 0)}
                  onClick={() => {
                    onRecord(refs.length ? covers.join(", ") : (r.refs || r.part),
                             fitted.name.trim(),
                             r.lcsc, note.trim(), "us", "", "", 1, suppliedBy, fitted.id);
                    setFitted({ id: null, name: "" }); setNote(""); setOpenForm(false);
                  }}>
            Substitute at {scopeLabel}
          </button>
          <button className="btn btn-sm" onClick={() => setOpenForm(false)}>Cancel</button>
          {picking ? (
            <ComponentPickDialog
              // Seeded with the MPN alone. Anything else — "T491… at C2" —
              // goes straight into the search box and matches nothing.
              line={{ label: r.part, mpn: r.part, component_id: null }}
              title="Which part was fitted?"
              confirmLabel="Use this part"
              // A part off OUR shelf must be in the library: we bought it, so
              // it has an invoice line and a pool entry, and naming it by
              // string alone would split that part in two. One the supplier
              // provided we never bought, so there is nothing to link it to.
              allowFreeText={suppliedBy !== "pool"}
              onPick={(id, mpn) => setFitted({ id, name: mpn })}
              onClose={() => setPicking(false)}
            />
          ) : null}
        </div>
      ) : (
        <div className="btn-row">
          <button className="btn btn-sm" disabled={busy}
                  onClick={(e) => { e.stopPropagation(); setOpenForm(true); }}>
            Substitute this part
          </button>
        </div>
      )}
    </div>
  );
}

function MatDetail({
  r,
  cur,
  busy,
  supply,
  overrideDraft,
  setOverrideDraft,
  onOverride,
  onRemoveDraw,
  onRemoveAdj,
  onRecordSub,
  onDeleteSub,
  onDesignUpdated,
}: {
  r: MatRow;
  cur: string;
  supply: BatchSupplyRow[];
  busy: boolean;
  overrideDraft: string;
  setOverrideDraft: (s: string) => void;
  onOverride: (raw: string) => void;
  onRemoveDraw: (id: number) => void;
  onRemoveAdj: (a: StockAdjustment) => void;
  onRecordSub: (designator: string, fitted: string, specified: string, note: string,
                source: string, evidence: string, supplierRef: string, qty: number,
                suppliedBy: string, fittedComponentId: number | null) => void;
  onDeleteSub: (s: RunSubstitution) => void;
  onDesignUpdated: (s: RunSubstitution, v: boolean) => void;
}) {
  return (
    <div className="ledger-panel">
      <SubstitutePanel r={r} busy={busy} supply={supply} onRecord={onRecordSub}
                       onDelete={onDeleteSub} onDesignUpdated={onDesignUpdated} />
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
