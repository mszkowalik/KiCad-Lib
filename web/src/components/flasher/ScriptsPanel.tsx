/** Deployment scripts — the versioned config/test scenario. Each version pins
 *  one release version (the flash) and exact device file versions (the
 *  downloads); steps are the ordered op list the engine executes. */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createDeploymentScript,
  createScriptVersion,
  errorMessage,
  isAbortError,
  listDeploymentScripts,
  listDeviceFiles,
  listParamSets,
  listReleases,
  publishScriptVersion,
  rejectScriptVersion,
  type DeploymentScriptRow,
  type DeviceFileRow,
  type FlasherMeta,
  type ParamSetRow,
  type ReleaseRow,
  type ScriptVersionRow,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { fmtWhen } from "./common";

interface Composer {
  scriptId: number;
  releaseVersionId: number | "";
  transport: string;
  monitorBaud: number;
  stepsText: string;
  paramSetId: number | "";
  paramDefaultsText: string;
  fileVersionIds: number[];
  comment: string;
}

export default function ScriptsPanel({ projectId, meta }: { projectId: number; meta: FlasherMeta | null }) {
  const dialog = useDialog();
  const [scripts, setScripts] = useState<DeploymentScriptRow[] | null>(null);
  const [releases, setReleases] = useState<ReleaseRow[]>([]);
  const [files, setFiles] = useState<DeviceFileRow[]>([]);
  const [paramSets, setParamSets] = useState<ParamSetRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [composer, setComposer] = useState<Composer | null>(null);
  const [openVersion, setOpenVersion] = useState<number | null>(null);

  const reload = useCallback(() => {
    const ac = new AbortController();
    Promise.all([
      listDeploymentScripts(projectId, ac.signal),
      listReleases(projectId, ac.signal),
      listDeviceFiles(projectId, ac.signal),
      listParamSets(projectId, ac.signal),
    ])
      .then(([s, r, f, p]) => {
        setScripts(s);
        setReleases(r);
        setFiles(f);
        setParamSets(p);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [projectId]);

  useEffect(() => {
    setScripts(null);
    return reload();
  }, [reload]);

  const releaseVersions = useMemo(
    () =>
      releases.flatMap((r) =>
        r.versions.map((v) => ({
          id: v.id,
          label: `${r.name} v${v.version_no} (${v.status})`,
          published: v.status === "published",
        })),
      ),
    [releases],
  );

  const addScript = async () => {
    const name = await dialog.prompt("Deployment script name (e.g. Dongle_V3 blank device):", {
      title: "New deployment script",
    });
    if (!name) return;
    try {
      await createDeploymentScript(projectId, { name });
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const openComposer = (script: DeploymentScriptRow) => {
    // Prefill from the newest version so an edit is a copy, not a retype.
    const latest = script.versions[script.versions.length - 1];
    setComposer({
      scriptId: script.id,
      releaseVersionId: latest?.release?.release_version_id ?? "",
      transport: latest?.transport_profile ?? "uart_bridge",
      monitorBaud: latest?.monitor_baud ?? 115200,
      stepsText: JSON.stringify(latest?.steps ?? [], null, 2),
      paramSetId: latest?.param_set_id ?? "",
      paramDefaultsText: JSON.stringify(latest?.param_defaults ?? {}, null, 2),
      fileVersionIds: latest?.files.map((f) => f.device_file_version_id) ?? [],
      comment: "",
    });
  };

  const saveVersion = async () => {
    if (!composer) return;
    let steps: Record<string, unknown>[];
    let paramDefaults: Record<string, unknown> | null;
    try {
      steps = JSON.parse(composer.stepsText);
      if (!Array.isArray(steps)) throw new Error("steps must be a JSON array");
    } catch (e) {
      setError(`Steps JSON: ${(e as Error).message}`);
      return;
    }
    try {
      paramDefaults = composer.paramDefaultsText.trim()
        ? JSON.parse(composer.paramDefaultsText)
        : null;
    } catch (e) {
      setError(`Param defaults JSON: ${(e as Error).message}`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createScriptVersion(composer.scriptId, {
        comment: composer.comment,
        release_version_id: composer.releaseVersionId === "" ? null : Number(composer.releaseVersionId),
        transport_profile: composer.transport,
        monitor_baud: composer.monitorBaud,
        steps,
        param_set_id: composer.paramSetId === "" ? null : Number(composer.paramSetId),
        param_defaults: paramDefaults,
        file_version_ids: composer.fileVersionIds,
      });
      setComposer(null);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const publish = async (v: ScriptVersionRow, name: string) => {
    if (!(await dialog.confirm(
      `Publish ${name} v${v.version_no}? Batches can then be programmed with it.`,
      { title: "Publish script version", tone: "ok", confirmLabel: "Publish" },
    ))) return;
    try {
      await publishScriptVersion(v.id);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const reject = async (v: ScriptVersionRow, name: string) => {
    if (!(await dialog.confirm(`Reject ${name} v${v.version_no}?`, {
      title: "Reject draft", tone: "danger", confirmLabel: "Reject",
    }))) return;
    try {
      await rejectScriptVersion(v.id);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const toggleFileVersion = (versionId: number, fileId: number) => {
    if (!composer) return;
    const file = files.find((f) => f.id === fileId);
    const siblings = new Set(file?.versions.map((v) => v.id) ?? []);
    setComposer({
      ...composer,
      fileVersionIds: composer.fileVersionIds.includes(versionId)
        ? composer.fileVersionIds.filter((id) => id !== versionId)
        : [...composer.fileVersionIds.filter((id) => !siblings.has(id)), versionId],
    });
  };

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Deployment scripts</h2>
        <button type="button" className="btn btn-sm" onClick={addScript}>New script</button>
      </div>
      <p className="card-subtitle">
        What the programmer does and checks after the flash. A version pins one release version and
        exact device file versions — a run records exactly what it executed.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      {scripts === null ? (
        <Spinner label="Loading scripts…" />
      ) : scripts.length === 0 ? (
        <p className="muted">No deployment scripts yet.</p>
      ) : (
        scripts.map((s) => (
          <div key={s.id} className="meta-card">
            <div className="toolbar">
              <strong>{s.name}</strong>
              {s.description ? <span className="muted">{s.description}</span> : null}
              <button type="button" className="btn btn-sm" onClick={() => openComposer(s)}>
                New version
              </button>
            </div>
            {s.versions.length === 0 ? (
              <p className="muted">No versions.</p>
            ) : (
              <div className="table-wrap">
                <table className="data data-fixed script-versions-table">
                  <thead>
                    <tr>
                      <th>v</th>
                      <th>Status</th>
                      <th>Release</th>
                      <th>Transport</th>
                      <th className="num">Steps</th>
                      <th>Files</th>
                      <th>Created</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {s.versions.map((v) => (
                      <tr
                        key={v.id}
                        className="ledger-row"
                        onClick={() => setOpenVersion(openVersion === v.id ? null : v.id)}
                      >
                        <td className="mono">
                          v{v.version_no}
                          {s.current_version_id === v.id ? " ●" : ""}
                        </td>
                        <td><StatusPill status={v.status} /></td>
                        <td title={v.release ? `${v.release.name} v${v.release.version_no}` : ""}>
                          {v.release ? `${v.release.name} v${v.release.version_no}` : "— none (monitor/test only)"}
                        </td>
                        <td className="mono dim">{v.transport_profile}</td>
                        <td className="num">{v.steps.length}</td>
                        <td
                          className="dim"
                          title={v.files.map((f) => `${f.filename} v${f.version_no}`).join("\n")}
                        >
                          {v.files.length ? `${v.files.length} pinned` : "—"}
                        </td>
                        <td className="muted">{fmtWhen(v.created_at)}</td>
                        <td className="ctr">
                          {v.status === "draft" ? (
                            <span className="btn-row">
                              <button
                                type="button"
                                className="btn btn-ok btn-sm"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  void publish(v, s.name);
                                }}
                              >
                                Publish
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  void reject(v, s.name);
                                }}
                              >
                                Reject
                              </button>
                            </span>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {s.versions
              .filter((v) => v.id === openVersion)
              .map((v) => (
                <pre key={v.id} className="mono steps-json">{JSON.stringify(v.steps, null, 2)}</pre>
              ))}
          </div>
        ))
      )}

      {composer ? (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setComposer(null)}>
          <div className="card pad modal-card modal-card-wide" onMouseDown={(e) => e.stopPropagation()}>
            <h2 className="card-title">New draft script version</h2>
            <div className="btn-row">
              <select
                className="row-input"
                value={composer.releaseVersionId}
                onChange={(e) =>
                  setComposer({
                    ...composer,
                    releaseVersionId: e.target.value === "" ? "" : Number(e.target.value),
                  })
                }
              >
                <option value="">— no release (monitor/test only) —</option>
                {releaseVersions.map((rv) => (
                  <option key={rv.id} value={rv.id}>{rv.label}</option>
                ))}
              </select>
              <select
                className="row-input"
                value={composer.transport}
                title="uart_bridge = external USB-UART; usb_serial_jtag = ESP32-C6 native USB (never touches DTR/RTS in monitor mode)"
                onChange={(e) => setComposer({ ...composer, transport: e.target.value })}
              >
                {(meta?.transport_profiles ?? ["uart_bridge", "usb_serial_jtag"]).map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <input
                className="row-input num"
                value={composer.monitorBaud}
                title="monitor baud"
                onChange={(e) => setComposer({ ...composer, monitorBaud: Number(e.target.value) || 115200 })}
              />
              <select
                className="row-input"
                value={composer.paramSetId}
                title="param set (encrypted shared values: WiFi, MQTT host, creds salt, default SIM PIN)"
                onChange={(e) =>
                  setComposer({ ...composer, paramSetId: e.target.value === "" ? "" : Number(e.target.value) })
                }
              >
                <option value="">— no param set —</option>
                {paramSets.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            <h3 className="card-subtitle">Pinned device files (one version per file)</h3>
            <div className="pin-file-list">
              {files.map((f) => (
                <div key={f.id} className="btn-row">
                  <span className="mono">{f.filename}</span>
                  {f.versions.map((v) => (
                    <label key={v.id} className="muted">
                      <input
                        type="checkbox"
                        checked={composer.fileVersionIds.includes(v.id)}
                        onChange={() => toggleFileVersion(v.id, f.id)}
                      />{" "}
                      v{v.version_no} ({v.status})
                    </label>
                  ))}
                </div>
              ))}
              {files.length === 0 ? <p className="muted">No device files in this project.</p> : null}
            </div>

            <h3 className="card-subtitle">Steps (ordered op list — the engine executes exactly this)</h3>
            <textarea
              className="note-textarea mono file-editor"
              spellCheck={false}
              value={composer.stepsText}
              onChange={(e) => setComposer({ ...composer, stepsText: e.target.value })}
            />
            <p className="muted dim">
              Ops: {(meta?.ops ?? []).join(", ")}
            </p>
            <h3 className="card-subtitle">Non-secret param defaults (JSON object)</h3>
            <textarea
              className="note-textarea mono params-editor"
              spellCheck={false}
              value={composer.paramDefaultsText}
              onChange={(e) => setComposer({ ...composer, paramDefaultsText: e.target.value })}
            />
            <div className="btn-row modal-actions">
              <input
                className="row-input"
                placeholder="comment (what changed)"
                value={composer.comment}
                onChange={(e) => setComposer({ ...composer, comment: e.target.value })}
              />
              <button type="button" className="btn" onClick={() => setComposer(null)} disabled={busy}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={saveVersion} disabled={busy}>
                {busy ? "Saving…" : "Save draft"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
