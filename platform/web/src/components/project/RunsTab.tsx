/** Production runs: create (freezes the priced BOM at current prices),
 *  override final prices per line, attach files, register serial numbers. */
import { useEffect, useState } from "react";
import {
  addRunDevices,
  createRun,
  deleteRun,
  deleteRunAttachment,
  deleteRunDevice,
  errorMessage,
  getRun,
  getRuns,
  isAbortError,
  refreezeRun,
  runAttachmentUrl,
  updateRun,
  uploadRunAttachment,
  type ProjectInfo,
  type RunEffectiveLine,
  type RunInfo,
  type SnapshotInfo,
} from "../../api";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import ProductionPanel from "./ProductionPanel";

function money(v: number | null | undefined, currency: string | null): string {
  if (v == null) return "—";
  return `${v.toLocaleString(undefined, { maximumFractionDigits: v < 1 ? 4 : 2 })} ${currency ?? ""}`;
}

interface Props {
  project: ProjectInfo;
  snapshots: SnapshotInfo[];
  snapshot: SnapshotInfo | null;
  board: string;
  variant: string;
}

export default function RunsTab({ project, snapshots, snapshot, board, variant }: Props) {
  const [runs, setRuns] = useState<RunInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<RunInfo | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [label, setLabel] = useState("");
  const [qty, setQty] = useState(10);
  const [runDate, setRunDate] = useState("");
  const [creating, setCreating] = useState(false);
  const [serialsDraft, setSerialsDraft] = useState("");
  const [overrideDrafts, setOverrideDrafts] = useState<Record<string, string>>({});

  const load = (signal?: AbortSignal) => {
    getRuns(project.id, signal)
      .then((rows) => {
        setRuns(rows);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  };

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id]);

  const openDetail = (id: number) => {
    setOverrideDrafts({});
    getRun(id)
      .then(setOpenRun)
      .catch((err) => setError(errorMessage(err)));
  };

  const create = () => {
    setCreating(true);
    createRun(project.id, {
      label: label.trim(),
      snapshot_id: snapshot?.id ?? null,
      board: snapshot ? board : "",
      variant: snapshot ? variant : "",
      qty,
      run_date: runDate,
    })
      .then((r) => {
        setCreating(false);
        setShowNew(false);
        setLabel("");
        load();
        setOpenRun(r);
      })
      .catch((err) => {
        setError(errorMessage(err));
        setCreating(false);
      });
  };

  const patchRun = (body: Parameters<typeof updateRun>[1]) => {
    if (!openRun) return;
    updateRun(openRun.id, body)
      .then((r) => {
        setOpenRun(r);
        load();
      })
      .catch((err) => setError(errorMessage(err)));
  };

  const applyOverride = (line: RunEffectiveLine) => {
    if (!openRun) return;
    const raw = overrideDrafts[line.key];
    const overrides = { ...(openRun.overrides ?? {}) } as Record<string, unknown>;
    if (raw === "" || raw == null) {
      delete overrides[line.key];
    } else {
      const isCost = line.key.startsWith("c");
      overrides[line.key] = isCost
        ? { price: Number(raw) }
        : { unit_price: Number(raw) };
    }
    patchRun({ overrides });
  };

  const eff = openRun?.effective;

  return (
    <div>
      {error ? <ErrorBanner message={error} /> : null}
      <div className="toolbar">
        <span className="toolbar-total">{runs ? `${runs.length} run(s)` : ""}</span>
        <button className="btn btn-primary btn-sm" onClick={() => setShowNew((v) => !v)}>
          {showNew ? "Cancel" : "New production run"}
        </button>
      </div>

      {showNew ? (
        <div className="card pad edit-card">
          <div className="edit-grid">
            <label>
              Label
              <input className="text" value={label} placeholder="Run #1 — prototypes"
                onChange={(e) => setLabel(e.target.value)} />
            </label>
            <label>
              Quantity (devices)
              <input className="text" type="number" min="1" value={qty}
                onChange={(e) => setQty(Math.max(1, Number(e.target.value)))} />
            </label>
            <label>
              Date
              <input className="text" type="date" value={runDate}
                onChange={(e) => setRunDate(e.target.value)} />
            </label>
          </div>
          <p className="muted">
            {snapshot
              ? `Freezes the priced BOM of ${snapshot.ref_name} / ${board}${variant ? ` (variant ${variant})` : ""} at today's prices.`
              : "No snapshot selected — the run will freeze only extra items and cost items."}
          </p>
          <button className="btn btn-primary" disabled={creating || !label.trim()} onClick={create}>
            {creating ? "Freezing prices…" : "Create + freeze"}
          </button>
        </div>
      ) : null}

      {runs === null && !error ? <Spinner label="Loading runs" /> : null}
      {runs && runs.length > 0 ? (
        <div className="card table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Run</th>
                <th className="num">Qty</th>
                <th>Status</th>
                <th>Date</th>
                <th>Snapshot</th>
                <th className="num">Files</th>
                <th className="num">Serials</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className={openRun?.id === r.id ? "row-selected" : ""}>
                  <td>{r.label}</td>
                  <td className="num">{r.qty}</td>
                  <td><StatusPill status={r.status} /></td>
                  <td className="muted">{r.run_date || "—"}</td>
                  <td className="mono">
                    {snapshots.find((s) => s.id === r.snapshot_id)?.ref_name ?? "—"}
                    {r.board ? ` / ${r.board}` : ""}
                  </td>
                  <td className="num">{r.attachment_count}</td>
                  <td className="num">{r.device_count}</td>
                  <td className="nowrap">
                    <button className="btn btn-sm" onClick={() => openDetail(r.id)}>Open</button>{" "}
                    <button className="btn btn-sm btn-danger"
                      onClick={() => {
                        if (window.confirm(`Delete run "${r.label}" and its attachments?`)) {
                          deleteRun(r.id).then(() => {
                            if (openRun?.id === r.id) setOpenRun(null);
                            load();
                          });
                        }
                      }}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {runs && runs.length === 0 && !showNew ? (
        <p className="muted">No production runs yet.</p>
      ) : null}

      {openRun ? (
        <div className="card pad">
          <div className="panel-head">
            <h3 className="card-title">
              {openRun.label} — {openRun.qty} device(s)
            </h3>
            <div className="btn-row">
              <select className="text" value={openRun.status}
                onChange={(e) => patchRun({ status: e.target.value })}>
                {["planned", "ordered", "in production", "completed", "cancelled"].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <button className="btn btn-sm" title="Recompute frozen prices at current ladder/FX"
                onClick={() => refreezeRun(openRun.id).then((r) => setOpenRun(r))}>
                Re-freeze prices
              </button>
              <button className="btn btn-sm" onClick={() => setOpenRun(null)}>Close</button>
            </div>
          </div>

          {eff ? (
            <>
              <div className="counts counts-sm">
                <div className="count-tile">
                  <div className="v">{money(eff.totals.run_total, eff.currency)}</div>
                  <div className="muted">run total (with overrides)</div>
                </div>
                <div className="count-tile">
                  <div className="v">{money(eff.totals.per_device, eff.currency)}</div>
                  <div className="muted">per device</div>
                </div>
                <div className="count-tile">
                  <div className="v">{money(eff.totals.parts_total, eff.currency)}</div>
                  <div className="muted">parts</div>
                </div>
                <div className="count-tile">
                  <div className="v">{money(eff.totals.costs_total, eff.currency)}</div>
                  <div className="muted">manufacturing costs</div>
                </div>
              </div>
              <p className="muted">
                Prices frozen {eff.frozen_at ? new Date(eff.frozen_at).toLocaleString() : "—"}.
                Type a final price and press Apply to override a line; blank + Apply clears it.
              </p>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Line</th>
                      <th className="num">Qty</th>
                      <th className="num">Frozen unit</th>
                      <th className="num">Line total</th>
                      <th className="num">Final price override</th>
                    </tr>
                  </thead>
                  <tbody>
                    {eff.lines.filter((l) => !l.excluded).map((l) => (
                      <tr key={l.key} className={l.dropped ? "row-dim" : ""}>
                        <td className="cell-desc">
                          {l.refs || l.label || l.value}
                          {l.overridden ? <span className="pill warn">override</span> : null}
                        </td>
                        <td className="num">{l.qty_total.toLocaleString()}</td>
                        <td className="num">{money(l.unit_price, eff.currency)}</td>
                        <td className="num">{money(l.line_total, eff.currency)}</td>
                        <td className="num nowrap">
                          <input className="text num-input" placeholder="unit price"
                            value={overrideDrafts[l.key] ?? ""}
                            onChange={(e) =>
                              setOverrideDrafts({ ...overrideDrafts, [l.key]: e.target.value })
                            } />{" "}
                          <button className="btn btn-sm" onClick={() => applyOverride(l)}>
                            Apply
                          </button>
                        </td>
                      </tr>
                    ))}
                    {eff.costs.map((c) => (
                      <tr key={c.key}>
                        <td className="cell-desc">
                          {c.label} <span className="muted">({c.basis === "per_run" ? "per run" : "per device"})</span>
                          {c.overridden ? <span className="pill warn">override</span> : null}
                        </td>
                        <td className="num">—</td>
                        <td className="num">{money(c.price, eff.currency)}</td>
                        <td className="num">{money(c.run_cost ?? null, eff.currency)}</td>
                        <td className="num nowrap">
                          <input className="text num-input" placeholder="price"
                            value={overrideDrafts[c.key] ?? ""}
                            onChange={(e) =>
                              setOverrideDrafts({ ...overrideDrafts, [c.key]: e.target.value })
                            } />{" "}
                          <button className="btn btn-sm"
                            onClick={() => applyOverride(c as unknown as RunEffectiveLine)}>
                            Apply
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="muted">This run has no frozen snapshot.</p>
          )}

          <div className="edit-grid">
            <label>
              Notes
              <textarea className="note-textarea" value={openRun.notes}
                onChange={(e) => setOpenRun({ ...openRun, notes: e.target.value })}
                onBlur={(e) => patchRun({ notes: e.target.value })} />
            </label>
            <label>
              Serial numbers <span className="muted">(one per line, saved on Add)</span>
              <textarea className="note-textarea" value={serialsDraft}
                placeholder={"SN-0001\nSN-0002"}
                onChange={(e) => setSerialsDraft(e.target.value)} />
              <span>
                <button className="btn btn-sm" disabled={!serialsDraft.trim()}
                  onClick={() =>
                    addRunDevices(openRun.id, serialsDraft).then(() => {
                      setSerialsDraft("");
                      openDetail(openRun.id);
                    })
                  }>
                  Add serials
                </button>
              </span>
            </label>
          </div>

          <ProductionPanel runId={openRun.id} />

          <div className="card-subtitle">Attachments</div>
          <div className="btn-row">
            <input type="file"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  uploadRunAttachment(openRun.id, f)
                    .then(() => openDetail(openRun.id))
                    .catch((err) => setError(errorMessage(err)));
                  e.target.value = "";
                }
              }} />
          </div>
          {openRun.attachments && openRun.attachments.length > 0 ? (
            <ul className="model-files">
              {openRun.attachments.map((a) => (
                <li key={a.id}>
                  <a href={runAttachmentUrl(a.id)}>{a.filename}</a>{" "}
                  <span className="muted">
                    {(a.size_bytes / 1024).toFixed(1)} kB · {new Date(a.uploaded_at).toLocaleDateString()}
                  </span>{" "}
                  <button className="btn btn-sm btn-danger"
                    onClick={() => deleteRunAttachment(a.id).then(() => openDetail(openRun.id))}>
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No files attached.</p>
          )}

          {openRun.devices && openRun.devices.length > 0 ? (
            <>
              <div className="card-subtitle">Devices ({openRun.devices.length})</div>
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
                    {openRun.devices.map((d) => (
                      <tr key={d.id}>
                        <td className="mono">{d.serial}</td>
                        <td className="muted">{d.note || ""}</td>
                        <td className="muted">{new Date(d.created_at).toLocaleDateString()}</td>
                        <td>
                          <button className="btn btn-sm btn-danger"
                            onClick={() => deleteRunDevice(d.id).then(() => openDetail(openRun.id))}>
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
