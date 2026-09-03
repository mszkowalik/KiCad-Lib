/** One production run, one page — the center of the UI overhaul.
 *
 *  Before this page a run was edited from two places with disjoint field
 *  sets: status, notes and price overrides under Projects → Runs, while the
 *  sale (price per device, customer, units billed, qty_good) hid in a dialog
 *  on the Invoices page. Neither surface showed the other's fields, and
 *  `qty_good` — set only in that dialog — was the denominator the run costs
 *  panel complained about. Here every `PATCH /api/runs/{id}` field is visible
 *  and editable in one place.
 *
 *  Tabs: Overview (economics + sale + notes) · Materials (planned BOM vs real
 *  draws, ONE table) · Costs (documents + plan-vs-billed per step) · Files
 *  (production sets + attachments) · Devices (serials). The active tab lives
 *  in the URL (?tab=) so any view is linkable.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  addRunDevices,
  deleteRunAttachment,
  deleteRunDevice,
  errorMessage,
  getFxAt,
  getProject,
  getRun,
  getRunActuals,
  getSnapshots,
  isAbortError,
  runAttachmentUrl,
  updateRun,
  uploadRunAttachment,
  type ProjectInfo,
  type RunActuals,
  type RunInfo,
  type SnapshotInfo,
} from "../api";
import { BackLink, ErrorBanner, Spinner } from "../components/Ui";
import ProductionPanel from "../components/project/ProductionPanel";
import RunCosts from "../components/run/RunCosts";
import RunMaterials from "../components/run/RunMaterials";
import { amount as money, plain } from "../format";

const TABS = ["overview", "materials", "costs", "files", "devices"] as const;
type Tab = (typeof TABS)[number];

export default function RunDetail() {
  const params = useParams();
  const runId = Number(params.id);
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab") ?? "overview";
  const tab: Tab = (TABS as readonly string[]).includes(rawTab) ? (rawTab as Tab) : "overview";
  const setTab = (t: Tab) =>
    setSearchParams(t === "overview" ? {} : { tab: t }, { replace: true });

  const [run, setRun] = useState<RunInfo | null>(null);
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [snapshots, setSnapshots] = useState<SnapshotInfo[] | null>(null);
  const [actuals, setActuals] = useState<RunActuals | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [serialsDraft, setSerialsDraft] = useState("");
  const [notesDraft, setNotesDraft] = useState<string | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    getRun(runId, signal)
      .then((r) => {
        setRun(r);
        setError(null);
        getProject(r.project_id, signal).then(setProject).catch(() => {});
        // a snapshot-less run stays snapshot-less on purpose (turnkey batches),
        // so the re-point selector — and this fetch — only exist for the rest
        if (r.snapshot_id !== null) {
          getSnapshots(r.project_id, signal).then(setSnapshots).catch(() => {});
        }
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getRunActuals(runId, signal)
      .then(setActuals)
      .catch(() => setActuals(null));
  }, [runId]);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  const patchRun = (body: Parameters<typeof updateRun>[1]) =>
    updateRun(runId, body)
      .then((r) => setRun(r))
      .catch((err) => setError(errorMessage(err)));

  if (error && !run) {
    return (
      <div className="main-solo">
        <div className="page">
          <ErrorBanner message={error} />
          <p className="muted">
            <Link to="/projects">← All projects</Link>
          </p>
        </div>
      </div>
    );
  }
  if (!run) {
    return (
      <div className="main-solo">
        <div className="page">
          <Spinner label="Loading batch" />
        </div>
      </div>
    );
  }

  const eff = run.effective;

  return (
    <div className="main-solo">
      <div className="page">
        <div className="detail-top">
          <div>
            <BackLink to={`/projects/${run.project_id}`} className="backlink">
              ← {project?.name ?? "project"}
            </BackLink>
            <h1>{run.label}</h1>
            <span className="muted">
              {run.qty} device(s) · {run.run_date || "no date"}
            </span>
          </div>
          <div className="btn-row">
            {/* Re-point the planned BOM at another design commit. The server
                409s while `b<id>` overrides are keyed to the old snapshot's
                lines — the error banner carries that instruction, and the
                select snaps back because only a successful patch sets state. */}
            {run.snapshot_id !== null && snapshots && (
              <select
                className="text"
                title="Design commit — the snapshot this batch's planned BOM comes from"
                value={String(run.snapshot_id)}
                onChange={(e) => {
                  const id = Number(e.target.value);
                  if (id === run.snapshot_id) return;
                  updateRun(runId, { snapshot_id: id })
                    .then(() => load())
                    .catch((err) => setError(errorMessage(err)));
                }}
              >
                {snapshots
                  .filter((s) => s.status === "ready" || s.id === run.snapshot_id)
                  .map((s) => {
                    const noBoard =
                      run.board !== "" && !(s.boards ?? []).some((b) => b.name === run.board);
                    return (
                      <option
                        key={s.id}
                        value={String(s.id)}
                        disabled={noBoard && s.id !== run.snapshot_id}
                      >
                        {s.ref_name} · {s.sha.slice(0, 8)}
                        {noBoard ? ` — no board ${run.board}` : ""}
                      </option>
                    );
                  })}
              </select>
            )}
            <select
              className="text"
              value={run.status}
              onChange={(e) => void patchRun({ status: e.target.value })}
            >
              {["planned", "ordered", "in production", "completed", "cancelled"].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>

        {error ? <ErrorBanner message={error} /> : null}

        <div className="seg proj-tabs" role="tablist" aria-label="Run sections">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              className={tab === t ? "on" : ""}
              onClick={() => setTab(t)}
            >
              {t === "overview"
                ? "Overview"
                : t === "materials"
                  ? "Materials"
                  : t === "costs"
                    ? "Costs"
                    : t === "files"
                      ? "Files"
                      : `Devices (${run.device_count})`}
            </button>
          ))}
        </div>

        {tab === "overview" && (
          <>
            <div className="card pad">
              <h2 className="card-title">Economics</h2>
              <p className="card-subtitle">
                Planned figures price the BOM from history at the run date
                {eff?.priced_at ? ` (${new Date(eff.priced_at).toLocaleDateString()})` : ""}.
                Actuals come from settled invoices and pool draws. This strip is the ONE place
                these numbers render — the Materials and Costs tabs break them down.
              </p>
              <div className="counts counts-sm">
                <div className="count-tile">
                  <div className="v">{eff ? money(eff.totals.run_total, eff.currency) : "—"}</div>
                  <div className="muted">planned total</div>
                </div>
                <div className="count-tile">
                  <div className="v">{actuals ? money(actuals.total, actuals.currency) : "—"}</div>
                  <div className="muted">actual total</div>
                </div>
                <div className="count-tile">
                  <div className="v">
                    {actuals?.delta == null ? (
                      <span className="muted">—</span>
                    ) : (
                      <span className={`pill ${actuals.delta > 0 ? "warn" : "ok"}`}>
                        {actuals.delta > 0 ? "+" : ""}
                        {plain(actuals.delta)}
                        {actuals.delta_pct !== null && ` (${actuals.delta_pct.toFixed(1)}%)`}
                      </span>
                    )}
                  </div>
                  <div className="muted">actual vs plan</div>
                </div>
                <div className="count-tile">
                  <div className="v">
                    {actuals ? money(actuals.per_device, actuals.currency) : "—"}
                  </div>
                  <div className="muted">
                    per device{actuals?.qty_good == null ? ` (over planned ${run.qty})` : ""}
                  </div>
                </div>
                {/* the server converts revenue into the display currency
                    (order-date FX), so these tiles label it as such — the
                    sale currency would misstate a converted figure */}
                <div className="count-tile">
                  <div className="v">
                    {actuals?.revenue != null ? money(actuals.revenue, actuals.currency) : "—"}
                  </div>
                  <div className="muted">revenue</div>
                </div>
                <div className="count-tile">
                  <div className="v">
                    {actuals?.revenue != null
                      ? money(
                          actuals.revenue /
                            Math.max(actuals.qty_sold ?? actuals.qty_good ?? actuals.qty_planned, 1),
                          actuals.currency,
                        )
                      : "—"}
                  </div>
                  <div className="muted">revenue / device</div>
                </div>
                <div className="count-tile">
                  <div
                    className={
                      "v" + (actuals?.margin != null && actuals.margin < 0 ? " err-text" : "")
                    }
                  >
                    {actuals?.margin != null
                      ? `${money(actuals.margin, actuals.currency)}${
                          actuals.margin_pct != null
                            ? ` (${actuals.margin_pct.toFixed(1)}%)`
                            : ""
                        }`
                      : "—"}
                  </div>
                  <div className="muted">gross margin</div>
                </div>
              </div>
              {actuals && actuals.unknown_rates.length > 0 && (
                <div className="banner-warn">
                  No stored FX rate for {actuals.unknown_rates.join(", ")} — those amounts are
                  converted 1:1. Fix it under <Link to="/setup">Setup → Exchange rates</Link>.
                </div>
              )}
            </div>

            <SaleCard run={run} actuals={actuals} onSaved={() => load()} />

            <div className="card pad">
              <h2 className="card-title">Notes</h2>
              <textarea
                className="note-textarea"
                value={notesDraft ?? run.notes}
                onChange={(e) => setNotesDraft(e.target.value)}
                onBlur={(e) => {
                  if (e.target.value !== run.notes) void patchRun({ notes: e.target.value });
                  setNotesDraft(null);
                }}
              />
            </div>
          </>
        )}

        {tab === "materials" && (
          <RunMaterials run={run} onChanged={() => load()} />
        )}

        {tab === "costs" && (
          <RunCosts
            projectId={run.project_id}
            runId={run.id}
            qty={run.qty}
            runDate={run.run_date}
            effective={eff ?? null}
            overrides={run.overrides}
            onOverride={(overrides) => void patchRun({ overrides })}
            onChanged={() => load()}
          />
        )}

        {tab === "files" && (
          <div className="card pad">
            <ProductionPanel runId={run.id} />

            <div className="card-subtitle">Attachments</div>
            <div className="btn-row">
              <input
                type="file"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    uploadRunAttachment(run.id, f)
                      .then(() => load())
                      .catch((err) => setError(errorMessage(err)));
                    e.target.value = "";
                  }
                }}
              />
            </div>
            {run.attachments && run.attachments.length > 0 ? (
              <ul className="model-files">
                {run.attachments.map((a) => (
                  <li key={a.id}>
                    <a href={runAttachmentUrl(a.id)}>{a.filename}</a>{" "}
                    <span className="muted">
                      {(a.size_bytes / 1024).toFixed(1)} kB ·{" "}
                      {new Date(a.uploaded_at).toLocaleDateString()}
                    </span>{" "}
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() => deleteRunAttachment(a.id).then(() => load())}
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No files attached.</p>
            )}
          </div>
        )}

        {tab === "devices" && (
          <div className="card pad">
            <div className="edit-grid">
              <label>
                Serial numbers <span className="muted">(one per line, saved on Add)</span>
                <textarea
                  className="note-textarea"
                  value={serialsDraft}
                  placeholder={"SN-0001\nSN-0002"}
                  onChange={(e) => setSerialsDraft(e.target.value)}
                />
                <span>
                  <button
                    className="btn btn-sm"
                    disabled={!serialsDraft.trim()}
                    onClick={() =>
                      addRunDevices(run.id, serialsDraft).then(() => {
                        setSerialsDraft("");
                        load();
                      })
                    }
                  >
                    Add serials
                  </button>
                </span>
              </label>
            </div>
            {run.devices && run.devices.length > 0 ? (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Serial</th>
                      <th>Note</th>
                      <th>Added</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {run.devices.map((d) => (
                      <tr key={d.id}>
                        <td className="mono">{d.serial}</td>
                        <td className="muted">{d.note || ""}</td>
                        <td className="muted">{new Date(d.created_at).toLocaleDateString()}</td>
                        <td>
                          <button
                            className="btn btn-sm btn-danger"
                            onClick={() => deleteRunDevice(d.id).then(() => load())}
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
              <p className="muted">No serials registered yet.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** The sale side, inline — previously OrderDialog on the Invoices page.
 *  A price PER DEVICE, never a batch total: the total is derived, and a
 *  per-device figure survives a later quantity correction. Revenue is charged
 *  on the units billed (`qty_sold`), which is routinely neither the planned
 *  quantity nor the number that passed test. */
function SaleCard({
  run,
  actuals,
  onSaved,
}: {
  run: RunInfo;
  actuals: RunActuals | null;
  onSaved: () => void;
}) {
  const [price, setPrice] = useState(
    run.sale_unit_price != null ? String(run.sale_unit_price) : "",
  );
  const [currency, setCurrency] = useState(run.sale_currency || "");
  const [qtySold, setQtySold] = useState(run.qty_sold != null ? String(run.qty_sold) : "");
  const [qtyGood, setQtyGood] = useState(run.qty_good != null ? String(run.qty_good) : "");
  const [customer, setCustomer] = useState(run.customer || "");
  const [orderRef, setOrderRef] = useState(run.order_ref || "");
  const [orderDate, setOrderDate] = useState(run.order_date || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [fxRates, setFxRates] = useState<Record<string, number> | null>(null);

  const num = (s: string): number | null => {
    const t = s.trim();
    if (t === "") return null;
    const v = Number(t);
    return Number.isFinite(v) ? v : null;
  };

  const costCur = actuals?.currency || "USD";
  const saleCur = (currency || costCur).toUpperCase();
  const comparable = saleCur === costCur.toUpperCase();
  // FX for the preview at the ORDER date (else run date, else creation) —
  // the same instants run_actuals resolves at, so the preview matches the
  // saved figures instead of leaving the margin blank on a currency mismatch.
  // The run-date fallback is END-of-day (run_pricing_date), the order date is
  // start-of-day (_as_dt) — pass the exact instant, not just the date.
  const fxDate =
    orderDate.trim() ||
    (run.run_date ? `${run.run_date}T23:59:59` : run.created_at);
  useEffect(() => {
    if (comparable) return;
    const ac = new AbortController();
    getFxAt(fxDate, ac.signal)
      .then((r) => setFxRates(r.rates))
      .catch(() => setFxRates(null));
    return () => ac.abort();
  }, [comparable, fxDate]);

  const unit = num(price);
  // mirrors the server: billed units, else good, else planned
  const units = num(qtySold) ?? num(qtyGood) ?? run.qty;
  const revenue = unit != null ? unit * units : null;
  const cost = actuals?.total ?? null;
  const srcRate = fxRates?.[saleCur];
  const tgtRate = fxRates?.[costCur.toUpperCase()];
  const fxFactor = !comparable && srcRate && tgtRate ? srcRate / tgtRate : null;
  // revenue in the cost currency: as entered when the currencies match,
  // else converted at the order-date rate; null when no rate is stored
  const revenueCost =
    revenue == null ? null : comparable ? revenue : fxFactor != null ? revenue * fxFactor : null;
  const margin = revenueCost != null && cost != null ? revenueCost - cost : null;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await updateRun(run.id, {
        sale_unit_price: unit,
        sale_currency: currency.trim().toUpperCase(),
        qty_sold: num(qtySold),
        qty_good: num(qtyGood),
        customer: customer.trim(),
        order_ref: orderRef.trim(),
        order_date: orderDate.trim(),
      });
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card pad">
      <h2 className="card-title">Order &amp; sale</h2>
      <p className="card-subtitle">
        Price per device, not a batch total. Revenue is charged on the units billed, so a
        batch that shipped short still reads correctly. Units good is the yield denominator
        for the per-device cost.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      {saved ? <div className="banner-ok">Saved.</div> : null}

      <div className="edit-grid">
        <label>
          Price per device
          <input
            className="text num"
            inputMode="decimal"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
        </label>
        <label>
          Sale currency
          <input
            className="text"
            value={currency}
            placeholder={costCur}
            maxLength={3}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
          />
        </label>
        <label>
          Units billed
          <input
            className="text num"
            inputMode="numeric"
            value={qtySold}
            placeholder={String(run.qty_good ?? run.qty)}
            onChange={(e) => setQtySold(e.target.value)}
          />
        </label>
        <label>
          Units good
          <input
            className="text num"
            inputMode="numeric"
            value={qtyGood}
            placeholder={String(run.qty)}
            onChange={(e) => setQtyGood(e.target.value)}
          />
        </label>
        <label>
          Customer
          <input
            className="text"
            value={customer}
            onChange={(e) => setCustomer(e.target.value)}
          />
        </label>
        <label>
          Order reference
          <input
            className="text"
            value={orderRef}
            placeholder="their PO number"
            onChange={(e) => setOrderRef(e.target.value)}
          />
        </label>
        <label>
          Order date
          <input
            className="text"
            value={orderDate}
            placeholder="2025-09-20"
            onChange={(e) => setOrderDate(e.target.value)}
          />
        </label>
      </div>

      <div className="table-wrap">
        <table className="data data-fixed order-preview-table">
          <thead>
            <tr>
              <th className="num">Units billed</th>
              <th className="num">Revenue</th>
              <th className="num">Cost (actual)</th>
              <th className="num">Margin</th>
              <th className="num">Margin %</th>
              <th className="num">Per device</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="num">{units.toLocaleString()}</td>
              <td
                className="num"
                title={
                  !comparable && revenueCost != null && revenue != null
                    ? `${money(revenue, saleCur)} as entered`
                    : undefined
                }
              >
                {revenueCost != null ? money(revenueCost, costCur) : money(revenue, saleCur)}
              </td>
              <td className="num">{money(cost, costCur)}</td>
              <td className={"num" + (margin != null && margin < 0 ? " err-text" : "")}>
                {money(margin, costCur)}
              </td>
              <td className={"num" + (margin != null && margin < 0 ? " err-text" : "")}>
                {margin != null && revenueCost
                  ? `${((margin / revenueCost) * 100).toFixed(1)}%`
                  : "—"}
              </td>
              <td className={"num" + (margin != null && margin < 0 ? " err-text" : "")}>
                {margin != null ? money(margin / Math.max(units, 1), costCur) : "—"}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {!comparable && unit != null && fxFactor != null ? (
        <p className="muted">
          The sale is in {saleCur}. Revenue and margin above are converted to {costCur} at 1{" "}
          {saleCur} = {fxFactor.toFixed(4)} {costCur}, the stored rate at{" "}
          {orderDate.trim() ? `the order date (${orderDate.trim()})` : "the run date"}.
        </p>
      ) : null}
      {!comparable && unit != null && fxFactor == null ? (
        <div className="banner-warn">
          The sale is in {saleCur} and the cost in {costCur}, and no rate for {saleCur} is
          stored — the margin is left blank rather than converted 1:1. Add the rate under{" "}
          <Link to="/setup">Setup → Exchange rates</Link>.
        </div>
      ) : null}
      {cost == null && unit != null ? (
        <div className="banner-warn">
          This run has no actual cost yet, so there is nothing to compare the price against.
        </div>
      ) : null}

      <div className="btn-row">
        <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save sale"}
        </button>
      </div>
      {run.sales ? (
        <p className="muted">
          From shipments: {run.sales.qty_sold_derived.toLocaleString()} units of this batch went to{" "}
          {run.sales.orders.length === 0 ? (
            "no order yet"
          ) : (
            run.sales.orders.map((o, i) => (
              <span key={o.order_line_id}>
                {i ? ", " : ""}
                <Link className="val-link" to={`/production/orders/${o.order_id}`}>
                  {o.customer}
                  {o.order_ref ? ` · ${o.order_ref}` : ""}
                </Link>{" "}
                ({o.qty_from_run.toLocaleString()})
              </span>
            ))
          )}
          {run.sales.stock ? (
            <>
              {" "}· {run.sales.stock.stock.toLocaleString()} still on the shelf
              {run.sales.stock.overdrawn ? ` · ${run.sales.stock.overdrawn} more shipped than built` : ""}
            </>
          ) : null}
          . Orders are managed on <Link className="val-link" to="/production/orders">Production → Orders</Link>;
          the fields above stay until the register reads the orders.
        </p>
      ) : null}
    </div>
  );
}
