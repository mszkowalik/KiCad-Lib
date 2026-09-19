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
import { CheckField } from "../components/Field";
import {
  deleteRunAttachment,
  errorMessage,
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
                    cost / device{actuals?.qty_good ? ` (over ${actuals.qty_good} produced)` : ""}
                  </div>
                </div>
              </div>
              {actuals && actuals.unknown_rates.length > 0 && (
                <div className="banner-warn">
                  No stored FX rate for {actuals.unknown_rates.join(", ")} — those amounts are
                  converted 1:1. Fix it under <Link to="/admin">Admin → Exchange rates</Link>.
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

