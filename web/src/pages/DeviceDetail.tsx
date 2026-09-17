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
import { BackLink, ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import DeviceHistoryCard from "../components/DeviceHistoryCard";
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

  // Is it programmed: the server decides (`checks.verdict`) — the config run,
  // then an ACTIVE test after it, then no erase since. The page only prints it,
  // so the device list and any later reader cannot drift from this answer.
  const v = device.verdict;
  const ACT_WORD: Record<string, string> = {
    flash: "programming run", test: "test", mark: "marking job", erase: "erase",
  };

  const runLink = (r: NonNullable<typeof v.config_run>) => (
    <Link className="val-link" to={`/production/flash-runs/${r.id}`}>
      #{r.id}
    </Link>
  );

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <BackLink to="/production/devices">← Devices</BackLink>
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
              {/* The verdict is a sentence the server wrote, plus the runs it
                  rests on. Marking never appears here: it changes nothing. */}
              <p className="card-subtitle">
                <span className={`pill ${v.programmed ? "ok" : "err"}`}>
                  {v.programmed ? "programmed" : "not programmed"}
                </span>{" "}
                {v.reason}
                {v.requires_test ? " — this project's test must pass after every programming run." : ""}
              </p>
              <p className="muted dim">
                {v.config_run ? (
                  <>
                    config {runLink(v.config_run)} ({v.config_run.status}) {fmtWhen(v.config_run.at)}
                  </>
                ) : (
                  <>no programming run</>
                )}
                {v.test_run ? (
                  <> · test {runLink(v.test_run)} ({v.test_run.status}) {fmtWhen(v.test_run.at)}</>
                ) : null}
                {v.erased_after ? (
                  <> · erased {runLink(v.erased_after)} {fmtWhen(v.erased_after.at)}</>
                ) : null}
              </p>
              {device.checks_run ? (
                <p className="muted dim">
                  Checks below are from the newest run that measured anything —{" "}
                  {ACT_WORD[device.checks_run.act] ?? device.checks_run.act}{" "}
                  <Link className="val-link" to={`/production/flash-runs/${device.checks_run.id}`}>
                    #{device.checks_run.id}
                  </Link>{" "}
                  ({device.checks_run.status}). Hover a cell for what earlier runs measured.
                </p>
              ) : null}
              <CheckGrid checks={device.checks} showRun />
            </div>

            <div className="card pad">
              <h2 className="card-title">Identity</h2>
              <table className="data data-fixed identity-table">
                <tbody>
                  {/* Whatever the server sent, in its order. Which rows a
                      product has is a server decision, not a page's. */}
                  {device.identity.map((row) => (
                    <tr key={row.key}>
                      <td className="muted">{row.label}</td>
                      <td className="mono" title={row.value}>{row.value || "—"}</td>
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
              {device.config_run_id ? (
                <p className="muted dim">
                  What is on the device now — written by run{" "}
                  <Link className="val-link" to={`/production/flash-runs/${device.config_run_id}`}>
                    #{device.config_run_id}
                  </Link>
                  {device.config_superseded > 0
                    ? `, the last one to configure it. ${device.config_superseded} earlier value(s) are kept but not shown.`
                    : "."}
                </p>
              ) : null}
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
                          {/* `current` can still be false when a LATER run
                              changed one key only — then that key's live value
                              came from a different run and this one is stale. */}
                          <td className="mono">{c.key}{c.current ? "" : " (superseded)"}</td>
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

          {/* `-fit`: the history card is short, so it sizes to its content and
              the programming history gets the rest of the column. */}
          <div className="detail-right detail-right-fit">
            <DeviceHistoryCard deviceId={deviceId} serial={device.serial || device.mac} />
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
                        {/* "By", not "Operator": the header was the widest
                            thing in a column that prints a name or a dash. */}
                        <th>By</th>
                        <th className="num">Took</th>
                        <th>Started</th>
                      </tr>
                    </thead>
                    <tbody>
                      {device.runs.map((r) => (
                        <tr key={r.id}>
                          {/* The card sits in the narrow column: "#6345
                              (attempt 3)" clipped to "#6345 …", which hid the
                              attempt it was spelling out. */}
                          <td title={`attempt ${r.attempt_no}`}>
                            <Link className="comp-link" to={`/production/flash-runs/${r.id}`}>
                              #{r.id}
                            </Link>
                            {r.attempt_no > 1 ? <span className="muted dim"> ·{r.attempt_no}</span> : null}
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
                          <td title={r.operator}>{r.operator || "—"}</td>
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
