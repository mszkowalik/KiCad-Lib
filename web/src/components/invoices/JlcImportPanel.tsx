import { useCallback, useEffect, useState } from "react";
import {
  applyJlcDecision,
  clearJlcDecision,
  errorMessage,
  fetchJlcOrderBom,
  getJlcQueue,
  isAbortError,
  setJlcDecision,
  syncJlcImport,
  voidJlcShopDraws,
  type JlcDecisionApplyResult,
  type JlcQueue,
  type JlcQueueOrder,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";

/**
 * Decide what each JLC ASSEMBLY ORDER means. One row per order, never per
 * invoice: a single JLC batch bills several assembly orders for different
 * boards, so the link has to be per order or it cannot be expressed at all.
 *
 * The evidence is shown rather than summarised. "confidence: high" is not
 * checkable by a human, but "11 caps and 1 ESP32 per device" is — so the
 * per-device breakdown is the primary justification on screen and the panel
 * factor is presented as a derived conclusion, because JLC's own quantity is
 * PANELS when the order was panelised and nothing in their data says so.
 *
 * Choosing "external" removes real stock value from run costing, so that number
 * is always on screen next to the button. It must be a deliberate choice, not a
 * way to make a warning disappear.
 */
export default function JlcImportPanel({ onApplied }: { onApplied?: () => void } = {}) {
  const dialog = useDialog();
  const [queue, setQueue] = useState<JlcQueue | null>(null);
  // Per-order dry-run result: what applying WOULD do, from the real write path.
  const [plan, setPlan] = useState<Record<string, JlcDecisionApplyResult | string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [onlyPending, setOnlyPending] = useState(true);

  const load = useCallback((signal?: AbortSignal) => {
    setLoading(true);
    getJlcQueue(signal)
      .then((q) => {
        setQueue(q);
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

  async function runSync() {
    setSyncing(true);
    setSyncMsg("");
    try {
      const r = await syncJlcImport();
      setSyncMsg(
        `${r.batches_visible} batches visible · ${r.fetched} newly fetched · ` +
          `${r.already_staged} already staged` +
          (r.failed ? ` · ${r.failed} failed` : ""),
      );
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSyncing(false);
    }
  }

  async function decide(
    o: JlcQueueOrder,
    outcome: "link_run" | "external",
    runId?: number | null,
  ) {
    setBusy(o.smt_order_code);
    try {
      await setJlcDecision(o.smt_order_code, {
        outcome,
        run_id: outcome === "link_run" ? runId ?? o.proposed_run_id : null,
        panel_factor: o.panel_factor,
      });
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  /** Cache JLC's own BOM for one order — the only source of who supplied
   *  each part. Evidence, not money; nothing is journalled. */
  async function fetchBom(o: JlcQueueOrder) {
    setBusy(o.smt_order_code);
    try {
      const r = await fetchJlcOrderBom(o.smt_order_code);
      const by = Object.entries(r.by_component_source)
        .map(([k, v]) => `${k}: ${v}`)
        .join(" · ");
      await dialog.alert(
        `Cached JLC's BOM for ${o.smt_order_code}: ${r.rows} row(s) (${by || "no source info"}). ` +
          (r.shop_parts.length
            ? `${r.shop_parts.length} part(s) were supplied by JLC itself — if draws exist for ` +
              `them, "Void shop draws" repairs the double charge.`
            : "Every part came from your consigned stock."),
        { title: "JLC BOM fetched" },
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  /** Void draws for parts JLC supplied itself, so they are not paid twice.
   *  Dry run first; the real write is one reversible batch. */
  async function voidShop(o: JlcQueueOrder) {
    setBusy(o.smt_order_code);
    try {
      const dry = await voidJlcShopDraws(o.smt_order_code, true);
      if (!dry.would_void?.length) {
        await dialog.alert(
          dry.note || "No live draws match JLC-supplied parts on this order.",
          { title: "Nothing to void" },
        );
        return;
      }
      const ok = await dialog.confirm(
        `Void ${dry.would_void.length} draw(s) worth $${dry.value_usd} on run ${dry.run_id} — ` +
          `parts JLC supplied itself (${(dry.shop_parts ?? []).join(", ")})? ` +
          `One reversible batch.`,
        { title: "Void shop draws", confirmLabel: "Void", tone: "danger" },
      );
      if (!ok) return;
      const res = await voidJlcShopDraws(o.smt_order_code, false);
      await dialog.alert(
        `Voided — write batch ${res.batch_id}, undoable in the Write log.`,
        { title: "Shop draws voided" },
      );
      load();
      onApplied?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function undo(o: JlcQueueOrder) {
    setBusy(o.smt_order_code);
    try {
      await clearJlcDecision(o.smt_order_code);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  /** What applying this decision would do — produced by the REAL write path with
   *  `dry_run=true` and rolled back, so the figures shown are the figures a real
   *  apply produces rather than a second implementation that could disagree. */
  async function preview(o: JlcQueueOrder) {
    setBusy(o.smt_order_code);
    try {
      const r = await applyJlcDecision(o.smt_order_code, true);
      setPlan((p) => ({ ...p, [o.smt_order_code]: r }));
    } catch (err) {
      setPlan((p) => ({ ...p, [o.smt_order_code]: errorMessage(err) }));
    } finally {
      setBusy(null);
    }
  }

  async function apply(o: JlcQueueOrder) {
    const p = plan[o.smt_order_code];
    const detail = typeof p === "object" ? describe(p) : "";
    const ok = await dialog.confirm(
      `Apply the ${o.decision?.outcome === "external" ? "external" : "batch link"} decision for ` +
        `${o.smt_order_code}?` +
        (detail ? ` This will ${detail}.` : "") +
        " It runs as one reversible batch and rolls back if the register stops balancing.",
      {
        title: "Move this money",
        confirmLabel: "Apply",
        tone: o.decision?.outcome === "external" ? "danger" : "primary",
      },
    );
    if (!ok) return;
    setBusy(o.smt_order_code);
    try {
      await applyJlcDecision(o.smt_order_code, false);
      setPlan((prev) => {
        const next = { ...prev };
        delete next[o.smt_order_code];
        return next;
      });
      load();
      onApplied?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (loading && !queue) return <Spinner label="Loading JLC import queue…" />;

  const orders = (queue?.orders ?? []).filter((o) =>
    onlyPending ? !o.decision || o.decision.outcome === "pending" : true,
  );
  const c = queue?.counts;

  return (
    <div className="card">
      <div className="card-title">JLC assembly orders</div>
      <div className="card-subtitle">
        One row per assembly order — the unit that maps to a production run. A JLC
        batch bills several, so the link cannot live on the invoice.
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="btn-row">
        <button className="btn btn-primary" onClick={runSync} disabled={syncing}>
          {syncing ? "Syncing…" : "Sync from JLCPCB"}
        </button>
        <label className="muted">
          <input
            type="checkbox"
            checked={onlyPending}
            onChange={(e) => setOnlyPending(e.target.checked)}
          />{" "}
          only undecided
        </label>
        {syncMsg && <span className="muted">{syncMsg}</span>}
      </div>

      {c && (
        <div className="toolbar">
          <span className="pill neutral">{c.total} orders</span>
          <span className={`pill ${c.pending ? "warn" : "ok"}`}>{c.pending} undecided</span>
          <span className="pill ok">{c.decided} decided</span>
          <span className="muted">
            awaiting a decision: ${c.pending_invoiced_usd.toLocaleString()} invoiced ·{" "}
            ${c.pending_stock_value_usd.toLocaleString()} of stock drawn
          </span>
        </div>
      )}

      {orders.length === 0 && (
        <p className="empty">
          {onlyPending ? "Every assembly order has been decided." : "Nothing staged yet — run a sync."}
        </p>
      )}

      {orders.map((o) => {
        const isOpen = open === o.smt_order_code;
        const decided = o.decision && o.decision.outcome !== "pending";
        return (
          <div className="meta-card" key={o.smt_order_code}>
            <div className="btn-row">
              <span className="mono">{o.smt_order_code}</span>
              {o.board_codes.map((b) => (
                <span className="badge" key={b}>
                  {b}
                </span>
              ))}
              <span className="muted">{o.invoice_date}</span>
              <span className="mono num">${(o.money_usd ?? 0).toLocaleString()}</span>
              <ConfidencePill order={o} />
              {decided && (
                <span className="pill ok">
                  {o.decision!.outcome === "external"
                    ? "external project"
                    : `run ${o.decision!.run_id}`}
                </span>
              )}
              <button
                className="btn btn-sm"
                onClick={() => setOpen(isOpen ? null : o.smt_order_code)}
              >
                {isOpen ? "hide" : "evidence"}
              </button>
            </div>

            <div className="muted">
              JLC says {o.jlc_number ?? "?"}{" "}
              {o.panel_factor && o.panel_factor > 1 ? "panels" : "boards"}
              {o.panel_factor ? (
                <>
                  {" "}
                  × {o.panel_factor} per panel ={" "}
                  <strong>{o.implied_devices} devices</strong> (factor derived from the BOM,
                  not stated by JLC)
                </>
              ) : (
                " — no panel factor could be derived"
              )}
              {o.part_count > 0 && (
                <>
                  {" · "}
                  {o.part_count} parts drawn from stock worth $
                  {(o.consumed_value_usd ?? 0).toLocaleString()} across {o.lot_count} lots
                </>
              )}
            </div>

            {o.collision_note && <div className="banner-warn">{o.collision_note}</div>}
            {o.reason && <div className="muted dim">{o.reason}</div>}

            {isOpen && <Evidence order={o} />}

            {!decided && (
              <div className="btn-row">
                {o.proposed_run_id && (
                  <button
                    className="btn btn-ok btn-sm"
                    disabled={busy === o.smt_order_code}
                    onClick={() => decide(o, "link_run")}
                  >
                    Link to {o.proposed_run_label}
                  </button>
                )}
                <button
                  className="btn btn-sm"
                  disabled={busy === o.smt_order_code}
                  onClick={() => decide(o, "external")}
                  title={
                    o.consumed_value_usd
                      ? `Removes $${o.consumed_value_usd} of stock value from batch costing`
                      : "No stock was drawn by this order"
                  }
                >
                  External project
                  {o.consumed_value_usd
                    ? ` (−$${(o.consumed_value_usd ?? 0).toLocaleString()} from batch costs)`
                    : ""}
                </button>
                {o.candidates.length > 1 && (
                  <select
                    className="row-input"
                    defaultValue=""
                    disabled={busy === o.smt_order_code}
                    onChange={(e) =>
                      e.target.value && decide(o, "link_run", Number(e.target.value))
                    }
                  >
                    <option value="">link to another run…</option>
                    {o.candidates.map((k) => (
                      <option key={k.run_id} value={k.run_id}>
                        {k.run_label} — {k.agree}/{k.voted} parts agree, {k.implied_devices} devices
                        {k.date_gap_days != null ? `, ${k.date_gap_days}d away` : ""}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
            {decided && (
              <>
                <div className="btn-row">
                  {o.decision?.applied_at ? (
                    <span className="pill ok" title={`applied ${o.decision.applied_at}`}>
                      applied
                    </span>
                  ) : (
                    <>
                      <span className="pill warn">decided, not applied</span>
                      <button
                        className="btn btn-sm"
                        disabled={busy === o.smt_order_code}
                        onClick={() => preview(o)}
                      >
                        Preview
                      </button>
                      <button
                        className="btn btn-primary btn-sm"
                        disabled={busy === o.smt_order_code}
                        onClick={() => apply(o)}
                      >
                        Apply
                      </button>
                    </>
                  )}
                  <button
                    className="btn btn-sm"
                    disabled={busy === o.smt_order_code}
                    onClick={() => fetchBom(o)}
                    title="Cache JLC's own BOM for this order — the only source of who supplied each part (consigned stock vs JLC's shop)."
                  >
                    Fetch JLC BOM
                  </button>
                  {o.decision?.outcome === "link_run" && (
                    <button
                      className="btn btn-sm"
                      disabled={busy === o.smt_order_code}
                      onClick={() => voidShop(o)}
                      title="Void draws for parts JLC supplied itself, so they are not charged to the pool a second time. Needs the JLC BOM fetched first."
                    >
                      Void shop draws
                    </button>
                  )}
                  <button
                    className="btn btn-sm btn-danger"
                    disabled={busy === o.smt_order_code || !!o.decision?.applied_at}
                    onClick={() => undo(o)}
                    title={
                      o.decision?.applied_at
                        ? "Already applied — undo its write batch in the Write log first"
                        : "Clear this decision"
                    }
                  >
                    Clear
                  </button>
                </div>
                {plan[o.smt_order_code] && (
                  <div className="muted dim">
                    {typeof plan[o.smt_order_code] === "string"
                      ? (plan[o.smt_order_code] as string)
                      : `would ${describe(plan[o.smt_order_code] as JlcDecisionApplyResult) || "change nothing"}`}
                  </div>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * The dry run as one sentence, for the confirmation.
 *
 * `rebucketed` and `reason_only` are kept apart deliberately: filling in an
 * `exclude_reason` moves no money at all, and a single combined figure would
 * announce a movement that never happened. Overstating a change is as misleading
 * as understating one.
 */
function describe(r: JlcDecisionApplyResult): string {
  const parts: string[] = [];
  const L = r.lines;
  if (L?.rebucketed_count)
    parts.push(
      `move $${L.rebucketed_value_usd.toLocaleString()} across ${L.rebucketed_count} line(s)`,
    );
  if (L?.reason_only_count)
    parts.push(`label ${L.reason_only_count} exclusion(s) with a reason (no money moves)`);
  const d = r.draws as { would_make?: number; draws?: number; would_bind?: number } | undefined;
  if (d && (d.would_make ?? d.draws)) parts.push(`write ${d.would_make ?? d.draws} measured draw(s)`);
  const m = r.movements as { would_write_movements?: number; movements?: number } | undefined;
  if (m && (m.would_write_movements ?? m.movements))
    parts.push(
      `book ${m.would_write_movements ?? m.movements} stock movement(s) out of the pool, charged to nobody`,
    );
  return parts.join(", ");
}

function ConfidencePill({ order }: { order: JlcQueueOrder }) {
  const tone =
    order.confidence === "high"
      ? "ok"
      : order.confidence === "none"
        ? "neutral"
        : order.confidence === "ambiguous" ||
            order.confidence === "collision" ||
            order.confidence === "date_conflict"
          ? "err"
          : "warn";
  return <span className={`pill ${tone}`}>{order.confidence}</span>;
}

/**
 * The per-device table is the point: a human can confirm "11 caps per dongle"
 * instantly, which is what makes the derived panel factor trustworthy.
 */
function Evidence({ order }: { order: JlcQueueOrder }) {
  return (
    <div className="table-wrap">
      {order.per_device.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>LCSC</th>
              <th>MPN</th>
              <th className="num">consumed</th>
              <th className="num">per device</th>
              <th className="num">value</th>
            </tr>
          </thead>
          <tbody>
            {order.per_device.map((p) => (
              <tr key={p.lcsc + p.mpn}>
                <td className="mono">{p.lcsc}</td>
                <td>{p.mpn}</td>
                <td className="num">{p.qty.toLocaleString()}</td>
                <td className="num">
                  {p.per_device == null ? <span className="dim">—</span> : p.per_device}
                </td>
                <td className="num">${p.money.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {order.candidates.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>candidate batch</th>
              <th className="num">batch qty</th>
              <th className="num">k</th>
              <th className="num">agree</th>
              <th className="num">implied devices</th>
              <th className="num">days apart</th>
              <th>qty fits</th>
            </tr>
          </thead>
          <tbody>
            {order.candidates.map((k) => (
              <tr key={k.run_id}>
                <td>{k.run_label}</td>
                <td className="num">{k.run_qty ?? "—"}</td>
                <td className="num">{k.panel_factor}</td>
                <td className="num">
                  {k.agree}/{k.voted}
                </td>
                <td className="num">{k.implied_devices}</td>
                <td className="num">{k.date_gap_days ?? "—"}</td>
                <td>
                  <span className={`pill ${k.qty_matches ? "ok" : "neutral"}`}>
                    {k.qty_matches ? "yes" : `off by ${k.qty_delta ?? "?"}`}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
