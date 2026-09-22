/** One production run, one page — the center of the UI overhaul.
 *
 *  Before this page a run was edited from two places with disjoint field
 *  sets: status, notes and price overrides under Projects → Runs, while the
 *  sale (price per device, customer, units billed, qty_good) hid in a dialog
 *  on the Invoices page. Neither surface showed the other's fields, and
 *  `qty_good` — set only in that dialog — was the denominator the run costs
 *  panel complained about.
 *
 *  This page is now the ONE place a batch is edited, and that claim has to stay
 *  literally true. It read "every `PATCH /api/runs/{id}` field is visible and
 *  editable here" while `label`, `qty`, `run_date` and `qty_good` had no control
 *  anywhere in the app — a batch opened for 50 could not be corrected to the 60
 *  actually built (reported 2026-09-22). The Batch card holds those four, behind
 *  Edit… / Save / Cancel: two of them are denominators of a per-device cost that
 *  has already gone out on orders, so they are not edited by tabbing through a
 *  row of live boxes. The SALE fields (`sale_unit_price`, `qty_sold`,
 *  `customer`, `order_ref`, `order_date`) are the deliberate exception and are
 *  absent: a batch shows costs, the ORDER carries revenue (decision
 *  2026-09-19). Adding a field to `RunPatch` means adding it to the Batch card,
 *  or writing here why not.
 *
 *  Tabs: Overview (batch + economics + notes) · Materials (planned BOM vs real
 *  draws, ONE table) · Costs (documents + plan-vs-billed per step) · Files
 *  (production sets + attachments) · Devices (serials). The active tab lives
 *  in the URL (?tab=) so any view is linkable.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import Field, { CheckField, FieldGrid } from "../components/Field";
import NumberInput from "../components/NumberInput";
import { useDialog } from "../components/Dialog";
import {
  closeRun,
  deleteRunAttachment,
  errorMessage,
  getProject,
  getRun,
  getRunActuals,
  getSnapshots,
  isAbortError,
  reopenRun,
  runAttachmentUrl,
  updateRun,
  uploadRunAttachment,
  type ProjectInfo,
  type RunActuals,
  type RunInfo,
  type SnapshotInfo,
} from "../api";
import { BackLink, ErrorBanner, Spinner } from "../components/Ui";
import DevicesTab from "../components/project/DevicesTab";
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
  const [notesDraft, setNotesDraft] = useState<string | null>(null);
  /** The Batch card's unsaved edits. It is a DRAFT and not a set of live
   *  controls on purpose: `qty` and `qty_good` are the denominators every
   *  per-device cost is divided by, `NumberInput.onChange` fires per keystroke,
   *  and a box wired straight to `patchRun` would write qty 6 on the way to
   *  typing 60 — each an audit row against money already carried onto orders.
   *  `qtyGood: null` is a real value (count from programming runs), so the
   *  field is `number | null` and ABSENT means the card is not open. */
  const [draft, setDraft] = useState<{
    label?: string;
    qty?: number | null;
    qtyGood?: number | null;
    runDate?: string;
  }>({});
  /** The card reads as facts until this is on — see the comment on the card. */
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [closing, setClosing] = useState(false);
  const dialog = useDialog();

  const load = useCallback((signal?: AbortSignal) => {
    getRun(runId, signal)
      .then((r) => {
        setRun(r);
        setError(null);
        getProject(r.project_id, signal).then(setProject).catch(() => {});
        // Every batch gets the selector, INCLUDING a snapshot-less one. Gating
        // this fetch on `snapshot_id !== null` assumed a batch with no design
        // commit had chosen to have none — but a batch is routinely opened
        // before its design is committed, and then nothing on any screen could
        // attach one (batch 2164, reported 2026-09-22).
        getSnapshots(r.project_id, signal).then(setSnapshots).catch(() => {});
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

  /** What the Batch card would send — only the fields that actually differ, so
   *  Save is dead until something changed and the audit row names the real
   *  edit rather than every field on the form. */
  const batchPatch = (): Parameters<typeof updateRun>[1] => {
    if (!run) return {};
    const body: Parameters<typeof updateRun>[1] = {};
    const label = (draft.label ?? run.label).trim();
    if (label && label !== run.label) body.label = label;
    if (draft.runDate !== undefined && draft.runDate !== run.run_date) {
      body.run_date = draft.runDate;
    }
    // The two quantities are frozen on a closed batch (decision 0044) — the API
    // refuses them, so the form must not offer them either.
    if (!run.closed_at) {
      if (draft.qty != null && draft.qty !== run.qty) body.qty = draft.qty;
      const good = draft.qtyGood ?? null;
      if (draft.qtyGood !== undefined && good !== (run.qty_good ?? null)) {
        body.qty_good = good;
      }
    }
    return body;
  };
  const batchChanges = Object.keys(batchPatch()).length;

  const saveBatch = async () => {
    const body = batchPatch();
    if (!Object.keys(body).length) return;
    setSaving(true);
    try {
      setRun(await updateRun(runId, body));
      setError(null);
      setDraft({});
      setEditing(false);
    } catch (err) {
      // Stay in the form with the draft intact: the server refuses a closed
      // batch and a stale `b<id>` override, and both are worth another try.
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  /** Close the books on this batch, or reopen them (decision 0044).
   *
   *  Closing makes every supplier document that charges the batch read-only and
   *  records what it cost, so a later correction shows as a variance rather than
   *  as the figure it always was.
   */
  const toggleClosed = async () => {
    if (!run) return;
    const open = !run.closed_at;
    const ok = await dialog.confirm(
      open
        ? "Closing the books records what this batch cost right now and makes every "
          + "supplier document charging it read-only. A batch's costs are recomputed "
          + "from those documents on every read, so editing one silently moves the "
          + "per-device cost that has already gone out on orders. After this, the way "
          + "to change the figure is a correction document, dated when you make it.\n\n"
          + "You can reopen the batch at any time."
        : "Reopening makes this batch's documents editable in place again, and clears "
          + "the cost that was recorded when it closed. The audit log keeps both.",
      { title: open ? "Close the books" : "Reopen the batch",
        confirmLabel: open ? "Close the books" : "Reopen" },
    );
    if (!ok) return;
    setClosing(true);
    try {
      setRun(open ? await closeRun(runId) : await reopenRun(runId));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setClosing(false);
    }
  };

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
            {/* Attach, re-point or detach the planned BOM's design commit. The
                server 409s while `b<id>` overrides are keyed to the old
                snapshot's lines — the error banner carries that instruction,
                and the select snaps back because only a successful patch sets
                state. "no snapshot" is a real option, not a placeholder: a
                turnkey batch prices only its extra items and cost items. */}
            {snapshots && (
              <select
                className="text"
                title="Design commit — the snapshot this batch's planned BOM comes from"
                value={run.snapshot_id === null ? "" : String(run.snapshot_id)}
                onChange={(e) => {
                  const id = e.target.value === "" ? null : Number(e.target.value);
                  if (id === run.snapshot_id) return;
                  updateRun(runId, { snapshot_id: id })
                    .then(() => load())
                    .catch((err) => setError(errorMessage(err)));
                }}
              >
                <option value="">— no snapshot (costs only) —</option>
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
            {/* WHAT THE BATCH IS — and a deliberately STIFF way to change it.
                These four fields had no control anywhere in the app, so a batch
                opened for 50 could not be corrected to the 60 actually built
                (reported 2026-09-22). But `qty` and `qty_good` are the
                denominators every per-device cost is divided by, and that cost
                has already gone out on orders — so this is not a card you edit
                by tabbing through it. It reads as facts until you open Edit,
                and nothing is sent until you press Save (user request
                2026-09-22).

                The sale fields stay absent: a batch shows costs, the ORDER
                carries revenue (decision 2026-09-19). */}
            <div className="card pad">
              <h2 className="card-title">Batch</h2>
              <p className="card-subtitle">
                {run.closed_at
                  ? "Books closed — quantities are read-only"
                  : "What this batch is, and how many it is for"}
              </p>
              {!editing ? (
                <>
                  <dl className="kv">
                    <dt>Label</dt>
                    <dd>{run.label}</dd>
                    <dt>Quantity planned</dt>
                    <dd>{run.qty}</dd>
                    <dt>Devices produced</dt>
                    <dd>
                      {run.qty_good ?? (
                        <span className="muted">counted from programming runs</span>
                      )}
                    </dd>
                    <dt>Run date</dt>
                    <dd>{run.run_date || <span className="muted">none</span>}</dd>
                  </dl>
                  <div className="btn-row">
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => {
                        setDraft({
                          label: run.label,
                          qty: run.qty,
                          qtyGood: run.qty_good ?? null,
                          runDate: run.run_date,
                        });
                        setEditing(true);
                      }}
                    >
                      Edit…
                    </button>
                    {run.closed_at && (
                      <span className="muted dim">
                        The books are closed, so quantity and devices produced cannot
                        change. Reopen the batch if one of them really is wrong.
                      </span>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <p className="muted dim">
                    A per-device cost is charged on both quantities, so changing one moves
                    the cost that has already gone out on every order shipped from this
                    batch. Nothing is written until you press Save.
                  </p>
                  <FieldGrid>
                    <Field label="Label">
                      <input
                        className="text"
                        value={draft.label ?? ""}
                        onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))}
                      />
                    </Field>
                    <Field
                      label="Quantity planned"
                      hint="Devices this batch is for. Must be 1 or more."
                      error={
                        draft.qty != null && draft.qty < 1 ? "must be 1 or more" : ""
                      }
                    >
                      <NumberInput
                        className="text"
                        value={draft.qty ?? null}
                        min={1}
                        step={1}
                        disabled={!!run.closed_at}
                        onChange={(v) => setDraft((d) => ({ ...d, qty: v }))}
                      />
                    </Field>
                    <Field
                      label="Devices produced"
                      hint="Units that passed. Leave empty to count them from programming runs."
                    >
                      <NumberInput
                        className="text"
                        value={draft.qtyGood ?? null}
                        min={0}
                        step={1}
                        disabled={!!run.closed_at}
                        onChange={(v) => setDraft((d) => ({ ...d, qtyGood: v }))}
                        onEmpty={() => setDraft((d) => ({ ...d, qtyGood: null }))}
                      />
                    </Field>
                    <Field label="Run date" hint="The date the planned BOM is priced at.">
                      <input
                        className="text"
                        type="date"
                        value={draft.runDate ?? ""}
                        onChange={(e) => setDraft((d) => ({ ...d, runDate: e.target.value }))}
                      />
                    </Field>
                  </FieldGrid>
                  <div className="btn-row">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={saving || !batchChanges || (draft.qty ?? 1) < 1}
                      onClick={() => void saveBatch()}
                    >
                      {saving ? "Saving…" : "Save"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={saving}
                      onClick={() => {
                        setDraft({});
                        setEditing(false);
                      }}
                    >
                      Cancel
                    </button>
                    <span className="muted dim">
                      {batchChanges
                        ? `${batchChanges} unsaved change(s)`
                        : "nothing changed yet"}
                    </span>
                  </div>
                </>
              )}
            </div>

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
                {/* A BATCH SHOWS COSTS. Revenue and margin belong to the
                    ORDER, and the two meet per UNIT: a device carries this
                    figure onto whatever order ships it (user decision
                    2026-09-19). Three tiles here priced the run's own sale,
                    which is how the same revenue came to exist in two places
                    and disagree. */}
                <div className="count-tile">
                  <div className="v">
                    {actuals?.per_device_cost != null
                      ? money(actuals.per_device_cost, actuals.currency)
                      : "—"}
                  </div>
                  <div className="muted"
                       title={actuals?.per_device_cost == null
                         ? "No devices are recorded as produced on this batch yet. A cost "
                           + "divided by a planned quantity would be an estimate, and this "
                           + "figure is carried onto real orders."
                         : "Cost of one device of this batch, over the devices recorded as "
                           + "produced. This is what a shipped unit carries onto its order."}>
                    {/* Only name the denominator when there IS one. `qty_good`
                        falls back to a typed figure, so this read "over 800
                        produced" beside a blank value on a batch with no device
                        records at all. */}
                    cost / device{actuals?.per_device_cost != null && actuals.qty_good
                      ? ` (over ${actuals.qty_good} produced)`
                      : ""}
                  </div>
                </div>
              </div>
              {/* THE BOOKS (decision 0044). It sits under the cost tiles because
                  that is what closing protects: the figure above it, which a
                  shipped unit carries onto its order. */}
              <div className="btn-row">
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={closing}
                  onClick={() => void toggleClosed()}
                >
                  {closing ? "…" : run.closed_at ? "Reopen the batch" : "Close the books"}
                </button>
                {run.closed_at ? (
                  <span className="muted">
                    Closed {run.closed_at.slice(0, 10)}
                    {run.closed_by ? ` by ${run.closed_by}` : ""} at{" "}
                    {money(run.closed_cost_usd, "USD")}
                    {run.closed_units ? ` over ${run.closed_units} produced` : ""}. Its
                    documents are read-only — change one with a correction on the{" "}
                    <Link to="/invoices">Invoices</Link> page.
                  </span>
                ) : (
                  <span className="muted">
                    Open: this batch&apos;s supplier documents can still be edited in place,
                    and every edit moves the cost above.
                  </span>
                )}
              </div>
              {/* A number that MOVED after it was quoted is the whole point of
                  closing, so it gets its own line rather than a tooltip. */}
              {run.closed_at && run.closed_cost_usd != null
                && actuals?.total_usd != null
                && Math.abs(actuals.total_usd - run.closed_cost_usd) > 0.005 ? (
                <div className="banner-warn">
                  This batch has cost {money(actuals.total_usd - run.closed_cost_usd, "USD")}{" "}
                  more than when its books closed ({money(run.closed_cost_usd, "USD")} →{" "}
                  {money(actuals.total_usd, "USD")}). Corrections posted since the close
                  account for the difference.
                </div>
              ) : null}
              {actuals && actuals.unknown_rates.length > 0 && (
                <div className="banner-warn">
                  No stored FX rate for {actuals.unknown_rates.join(", ")} — those amounts are
                  converted 1:1. Fix it under <Link to="/admin?tab=rates">Admin → Exchange rates</Link>.
                </div>
              )}
            </div>


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
          <>
            <div className="card pad">
              {/* The test requirement belongs to the BATCH, and each programming
                  run copies it when it starts — so this decides what is still to
                  be made, never what is already on the shelf. */}
              <CheckField
                checked={!!run.requires_test}
                onChange={(v) => void patchRun({ requires_test: v })}
                title="Units of this batch count as programmed only after they pass the project's test, run after their last programming run. A test that runs and fails always counts, batch or no batch. Changing this affects runs made from now on — every earlier run keeps the rule it was made under."
              >
                Units of this batch must pass the test
              </CheckField>
            </div>
            {/* The devices this batch actually made, which is what the flasher
                recorded — not the hand-typed `run_devices` registry this tab
                used to draw. That table has never held a row in any database,
                while the batch's real units sit on `DeviceUnit`. */}
            {project ? (
              <DevicesTab project={project} runId={run.id} />
            ) : (
              <div className="card pad">
                <p className="muted">Loading the project…</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

