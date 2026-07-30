/** One physical device: full identity (ESP + LTE module + SIM), the config
 *  values applied to it, and every programming attempt ever made. */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  errorMessage,
  getDevice,
  isAbortError,
  patchDevice,
  type DeviceDetailPayload,
} from "../api";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import CheckGrid from "../components/flasher/CheckGrid";
import { fmtDuration, fmtWhen } from "../components/flasher/common";

export default function DeviceDetail() {
  const { id } = useParams();
  const deviceId = Number(id);
  const [device, setDevice] = useState<DeviceDetailPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reveal, setReveal] = useState(false);
  const [notes, setNotes] = useState("");
  const [notesDirty, setNotesDirty] = useState(false);

  const reload = useCallback(() => {
    const ac = new AbortController();
    getDevice(deviceId, reveal, ac.signal)
      .then((d) => {
        setDevice(d);
        setNotes(d.notes);
        setNotesDirty(false);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [deviceId, reveal]);

  useEffect(() => reload(), [reload]);

  const saveNotes = async () => {
    try {
      await patchDevice(deviceId, notes);
      setNotesDirty(false);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (error) {
    return (
      <div className="main-solo"><div className="page"><ErrorBanner message={error} /></div></div>
    );
  }
  if (!device) {
    return (
      <div className="main-solo"><div className="page"><Spinner label="Loading device…" /></div></div>
    );
  }

  const identity: [string, string][] = [
    ["MAC", device.mac],
    ["Serial", device.serial],
    ["Chip", device.chip],
    ["Tasmota name", device.tasmota_id],
    ["IMEI", device.imei],
    ["ICCID (SIM)", device.iccid],
    ["IMSI", device.imsi],
    ["Modem", device.modem_model],
    ["Modem firmware", device.modem_fw],
  ];

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <Link className="backlink" to="/production/devices">← Devices</Link>
          <h1 className="mono">{device.serial || device.mac}</h1>
          {device.last_status ? <StatusPill status={device.last_status} /> : null}
          <span className="toolbar-total">
            {device.project.name} · first seen {fmtWhen(device.first_seen)} · last seen {fmtWhen(device.last_seen)}
          </span>
        </div>

        <div className="detail-page">
          <div className="detail-left">
            <div className="card pad">
              <h2 className="card-title">What this device is proven to do</h2>
              <CheckGrid checks={device.checks} showRun />
            </div>

            <div className="card pad">
              <h2 className="card-title">Identity</h2>
              <table className="data data-fixed identity-table">
                <tbody>
                  {identity.map(([k, v]) => (
                    <tr key={k}>
                      <td className="muted">{k}</td>
                      <td className="mono" title={v}>{v || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="card pad">
              <div className="toolbar">
                <h2 className="card-title">Configuration</h2>
                <label className="muted">
                  <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} />{" "}
                  reveal secrets
                </label>
              </div>
              {device.configs.length === 0 ? (
                <p className="muted">Nothing applied yet.</p>
              ) : (
                <div className="table-wrap">
                  <table className="data data-fixed device-config-table">
                    <thead>
                      <tr>
                        <th>Key</th>
                        <th>Value</th>
                        <th>Set by</th>
                        <th>When</th>
                      </tr>
                    </thead>
                    <tbody>
                      {device.configs.map((c, i) => (
                        <tr key={i} className={c.current ? "" : "dim"}>
                          <td className="mono">{c.key}{c.current ? "" : " (old)"}</td>
                          <td className="mono" title={c.value}>{c.value}</td>
                          <td>
                            {c.set_by_run_id ? (
                              <Link className="val-link" to={`/production/flash-runs/${c.set_by_run_id}`}>
                                run #{c.set_by_run_id}
                              </Link>
                            ) : "—"}
                          </td>
                          <td className="muted">{fmtWhen(c.set_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="card pad">
              <h2 className="card-title">Notes</h2>
              <textarea
                className="note-textarea"
                value={notes}
                onChange={(e) => {
                  setNotes(e.target.value);
                  setNotesDirty(true);
                }}
              />
              {notesDirty ? (
                <div className="btn-row">
                  <button type="button" className="btn btn-primary btn-sm" onClick={saveNotes}>
                    Save notes
                  </button>
                </div>
              ) : null}
            </div>
          </div>

          <div className="detail-right">
            <div className="card pad">
              <h2 className="card-title">Programming history</h2>
              <p className="card-subtitle">
                Every attempt, pass or fail — click through for the step timeline and the full
                serial log.
              </p>
              {device.runs.length === 0 ? (
                <p className="muted">No runs.</p>
              ) : (
                <div className="table-wrap">
                  <table className="data data-fixed device-runs-table">
                    <thead>
                      <tr>
                        <th>Run</th>
                        <th>Result</th>
                        <th>Batch</th>
                        <th>Deployment</th>
                        <th>Operator</th>
                        <th className="num">Took</th>
                        <th>Started</th>
                      </tr>
                    </thead>
                    <tbody>
                      {device.runs.map((r) => (
                        <tr key={r.id}>
                          <td>
                            <Link className="comp-link" to={`/production/flash-runs/${r.id}`}>
                              #{r.id} (attempt {r.attempt_no})
                            </Link>
                          </td>
                          <td><StatusPill status={r.status} /></td>
                          <td title={r.production_run?.label ?? ""}>
                            {r.production_run ? (
                              <Link className="val-link" to={`/runs/${r.production_run.id}`}>
                                {r.production_run.label}
                              </Link>
                            ) : "—"}
                          </td>
                          <td title={r.deployment ? `${r.deployment.name} v${r.deployment.version_no}` : ""}>
                            {r.deployment ? `${r.deployment.name} v${r.deployment.version_no}` : "—"}
                          </td>
                          <td>{r.operator || "—"}</td>
                          <td className="num">{fmtDuration(r.duration_ms)}</td>
                          <td className="muted">{fmtWhen(r.started_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
