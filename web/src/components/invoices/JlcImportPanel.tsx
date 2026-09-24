import { useCallback, useEffect, useState } from "react";
import {
  applyJlcDecision,
  clearJlcDecision,
  errorMessage,
  fetchJlcOrderBom,
  getAllRuns,
  getJlcQueue,
  isAbortError,
  setJlcDecision,
  syncJlcImport,
  voidJlcShopDraws,
  type JlcDecisionApplyResult,
  type JlcQueue,
  type JlcQueueOrder,
  type RunInfo,
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
  // EVERY batch, not only the matcher's shortlist. The matcher scores runs on
  // quantity and date; when it finds none — "JLC says 75 devices; no run has a
  // matching quantity" — the operator still knows which batch this order built
  // and must be able to say so. Without this, a real order was linkable only to
  // "External project", which removes its stock value from batch costing
  // (reported 2026-09-22, order SMT026092263197 against batch 2164).
  const [runs, setRuns] = useState<RunInfo[]>([]);

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
    getAllRuns(ac.signal)
      .then(setRuns)
      .catch(() => {});
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
          (r.boms_fetched ? ` · ${r.boms_fetched} BOMs cached` : "") +
          (r.panels_refreshed ? ` · ${r.panels_refreshed} device counts re-read` : "") +
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
    // Why this batch, or why external — the one thing the numbers on the row
    // cannot say (SMT026092263197 was linked to a 50-piece batch that JLC had
    // built 60 of). Optional; cancelling the prompt cancels the decision.
    const note = await dialog.prompt(
      outcome === "link_run"
        ? "Note for this link (optional) — e.g. why this batch, or what the counts do not show."
        : "Note (optional) — which project this order was for.",
      { title: outcome === "link_run" ? "Link to batch" : "External project",
        confirmLabel: "Save decision", maxLength: 500 },
    );
    if (note === null) return;
    setBusy(o.smt_order_code);
    try {
      await setJlcDecision(o.smt_order_code, {
        outcome,
        run_id: outcome === "link_run" ? runId ?? o.proposed_run_id : null,
        panel_factor: o.panel_factor,
        note: note.trim(),
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

  // "Unfinished" is undecided OR decided-and-never-applied. The second half
  // matters: a decision writes nothing by itself, so filtering on "has a
  // decision" hides orders whose stock has not moved and whose run is still
  // uncharged — exactly how SMT026080463762 vanished for three weeks.
  const orders = (queue?.orders ?? []).filter((o) =>
    onlyPending ? !o.decision || o.decision.outcome === "pending" || !o.applied : true,
  );
  const c = queue?.counts;

  return (
    <div className="card pad">
      <div className="card-title">JLC assembly orders</div>
      {/* `.card-subtitle` is 11px uppercase mono — a LABEL, not a paragraph.
          Two sentences in it rendered as two lines of shouting across the whole
          card (user report 2026-09-22); the rule is in components/CLAUDE.md and
          this was one of the places breaking it. */}
      <div className="card-subtitle">One row per assembly order</div>
      <p className="muted dim">
        The assembly order, not the invoice, is the unit that maps to a production
        batch: one JLC invoice bills several, so the link cannot live on it.
      </p>

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
          only unfinished
        </label>
        {syncMsg && <span className="muted">{syncMsg}</span>}
      </div>

      {c && (
        <div className="toolbar">
          <span className="pill neutral">{c.total} orders</span>
          <span className={`pill ${c.pending ? "warn" : "ok"}`}>{c.pending} undecided</span>
          <span className="pill ok">{c.decided - c.stranded} applied</span>
          {c.stranded > 0 && (
            <span
              className="pill err"
              title="Decided, but never applied — no stock moved and no run was charged."
            >
              {c.stranded} decided, not applied
            </span>
          )}
          {c.no_bom > 0 && (
            <span
              className="pill warn"
              title="JLC's own BOM was never fetched, so which parts JLC supplied itself is unknown."
            >
              {c.no_bom} without a BOM
            </span>
          )}
          <span className="muted">
            awaiting a decision: ${c.pending_invoiced_usd.toLocaleString()} invoiced ·{" "}
            ${c.pending_stock_value_usd.toLocaleString()} of stock drawn
            {c.stranded > 0
              ? ` · decided but unwritten: $${c.stranded_stock_value_usd.toLocaleString()} of stock`
              : ""}
          </span>
        </div>
      )}

      {orders.length === 0 && (
        <p className="empty">
          {onlyPending
            ? "Every assembly order has been decided and applied."
            : "Nothing staged yet — run a sync."}
        </p>
      )}

      {orders.map((o) => {
        const isOpen = open === o.smt_order_code;
        const decided = o.decision && o.decision.outcome !== "pending";
        return (
          <div className="card pad meta-card" key={o.smt_order_code}>
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

            {/* THE FACTS, each labelled, one chip each — not a sentence.
                This was a paragraph that asserted arithmetic: "JLC says 60
                boards × 1 per panel = 75 devices", which multiplied the BILLED
                quantity by the panel factor and printed a total derived from
                `pasteNumber`. Three different numbers read as one calculation,
                and the reader could not see which was which (user report
                2026-09-22). Each figure now says what it is and where it came
                from, and the reason the matcher gave sits under them. */}
            <div className="toolbar">
              {o.panels_assembled != null && (
                <span
                  className="pill neutral"
                  title={o.panels_source === "pasteNumber"
                    ? "JLC's pasteNumber (boards fabricated), cached before 2026-09-24. "
                      + "Sync again to re-read the assembled count."
                    : "JLC's allPatchNum: boards that went through the assembly line."}
                >
                  {o.panels_assembled} assembled
                  {o.panels_source === "pasteNumber" ? " (old reading)" : ""}
                </span>
              )}
              {o.panels_fabricated != null && o.panels_fabricated !== o.panels_assembled && (
                <span
                  className="pill neutral"
                  title="JLC's pasteNumber: bare boards fabricated. Only part of them was populated."
                >
                  {o.panels_fabricated} fabricated
                </span>
              )}
              {o.jlc_number != null && (
                <span className="pill neutral" title="What the invoice bills for">
                  {o.jlc_number} billed
                </span>
              )}
              {o.panel_factor ? (
                <span
                  className="pill neutral"
                  title={
                    o.panel_source === "jlc_panelisation"
                      ? "Panel factor stated by JLC"
                      : o.panel_source === "decision"
                        ? "Panel factor set by hand on this order"
                        : "Panel factor derived from the BOM — JLC did not state it"
                  }
                >
                  {o.panel_factor}-up panel
                  {o.panel_source === "jlc_panelisation"
                    ? ""
                    : o.panel_source === "decision"
                      ? " (by hand)"
                      : " (from the BOM)"}
                </span>
              ) : (
                <span className="pill warn" title="Nothing said how many boards a panel holds">
                  no panel factor
                </span>
              )}
              {o.implied_devices != null && (
                <span className="pill ok" title="What the platform will treat as the device count">
                  {o.implied_devices} devices
                </span>
              )}
              {o.part_count > 0 && (
                <span className="muted">
                  {o.part_count} parts from stock · $
                  {(o.consumed_value_usd ?? 0).toLocaleString()} · {o.lot_count} lots
                </span>
              )}
            </div>

            {/* `allPatchNum` equalled the billed figure on all 46 orders checked
                on 2026-09-24, so a difference here is new and worth a look. */}
            {o.panels_assembled != null && o.jlc_number != null
              && o.panels_assembled !== o.jlc_number && (
              <div className="banner-warn">
                JLC states {o.panels_assembled} boards assembled but bills {o.jlc_number}. The
                device count above follows the first. Open <strong>evidence</strong> and check a
                part fitted once per board to see which is right.
              </div>
            )}

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
                <RunPicker
                  order={o}
                  runs={runs}
                  disabled={busy === o.smt_order_code}
                  onPick={(runId) => decide(o, "link_run", runId)}
                />
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

/**
 * WHICH BATCH this assembly order built — the matcher's shortlist first, then
 * every batch in the platform.
 *
 * The matcher only ever scores a run whose recorded quantity is within the
 * yield tolerance of what JLC says it built, so an order for a batch that was
 * deliberately over-built (50 devices ordered, 75 boards assembled) scores
 * nothing and used to leave "External project" as the only button on screen.
 * That answer is not a smaller version of the right one — it takes the order's
 * consigned stock value out of batch costing altogether.
 *
 * The suggestions keep their evidence in the option text, so picking one off
 * the shortlist still reads as a judgement rather than a guess; the full list
 * carries each batch's project, recorded quantity and date so an operator can
 * recognise the one they mean. `PUT /decision` accepts any existing run — this
 * control was the only thing narrowing it.
 */
function RunPicker({
  order,
  runs,
  disabled,
  onPick,
}: {
  order: JlcQueueOrder;
  runs: RunInfo[];
  disabled: boolean;
  onPick: (runId: number) => void;
}) {
  const suggested = new Set(order.candidates.map((k) => k.run_id));
  const rest = runs.filter((r) => !suggested.has(r.id));
  return (
    <select
      className="row-input"
      value=""
      disabled={disabled}
      title="Link this assembly order to a batch — any batch, not only the suggested ones"
      onChange={(e) => e.target.value && onPick(Number(e.target.value))}
    >
      <option value="">link to a batch…</option>
      {order.candidates.length > 0 && (
        <optgroup label="Suggested by the quantity match">
          {order.candidates.map((k) => (
            <option key={k.run_id} value={k.run_id}>
              {k.run_label} — {k.agree}/{k.voted} parts agree, {k.implied_devices} devices
              {k.date_gap_days != null ? `, ${k.date_gap_days}d away` : ""}
            </option>
          ))}
        </optgroup>
      )}
      <optgroup label={order.candidates.length > 0 ? "Every other batch" : "Every batch"}>
        {rest.map((r) => {
          // The recorded quantity is the number an operator compares against
          // "JLC says N devices", so it is on every option — except where the
          // label already says it, which most of them do ("Batch 1 — 50 pcs").
          const qty = `${r.qty} pcs`;
          return (
            <option key={r.id} value={r.id}>
              {r.project ? `${r.project} · ` : ""}
              {r.label.includes(qty) ? r.label : `${r.label} — ${qty}`}
              {r.run_date ? ` · ${r.run_date}` : ""}
            </option>
          );
        })}
      </optgroup>
    </select>
  );
}

function ConfidencePill({ order }: { order: JlcQueueOrder }) {
  const tone =
    order.confidence === "high" || order.confidence === "decided"
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
