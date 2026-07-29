/** Produced devices — physical reality, keyed by the ESP MAC. Every unit the
 *  flasher ever touched, with batch, identity and programming history. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getProjects,
  isAbortError,
  listDevices,
  type DeviceListRow,
  type ProjectInfo,
} from "../api";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { fmtWhen } from "../components/flasher/common";
import { useStickyState } from "../useStickyState";

export default function Devices() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [rows, setRows] = useState<DeviceListRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("devices.project", null);
  const [status, setStatus] = useStickyState<string>("devices.status", "");
  const [q, setQ] = useState("");

  useEffect(() => {
    const ac = new AbortController();
    getProjects(ac.signal)
      .then(setProjects)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    const t = setTimeout(() => {
      listDevices(
        {
          project_id: projectId ?? undefined,
          status: status || undefined,
          q: q || undefined,
        },
        ac.signal,
      )
        .then(setRows)
        .catch((err) => {
          if (!isAbortError(err)) setError(errorMessage(err));
        });
    }, q ? 250 : 0);
    return () => {
      clearTimeout(t);
      ac.abort();
    };
  }, [projectId, status, q]);

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Devices</h1>
          <select
            className="row-input"
            value={projectId ?? ""}
            onChange={(e) => setProjectId(e.target.value === "" ? null : Number(e.target.value))}
          >
            <option value="">all projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <select className="row-input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">any result</option>
            <option value="pass">pass</option>
            <option value="fail">fail</option>
            <option value="aborted">aborted</option>
          </select>
          <input
            className="search"
            placeholder="MAC / serial / name / IMEI / ICCID…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <span className="toolbar-total">{rows ? `${rows.length} devices` : ""}</span>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {rows === null ? (
          <Spinner label="Loading devices…" />
        ) : rows.length === 0 ? (
          <p className="muted">No devices recorded yet — they appear the moment a programming run reads a MAC.</p>
        ) : (
          <div className="card">
            <div className="table-wrap">
              <table className="data data-fixed devices-table">
                <thead>
                  <tr>
                    <th>Serial</th>
                    <th>Name</th>
                    <th>MAC</th>
                    <th>Chip</th>
                    <th>Project</th>
                    <th>Batch</th>
                    <th>IMEI</th>
                    <th className="num">Runs</th>
                    <th>Last result</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((d) => (
                    <tr key={d.id}>
                      <td className="mono">
                        <Link className="comp-link" to={`/production/devices/${d.id}`}>
                          {d.serial || d.mac}
                        </Link>
                      </td>
                      <td className="mono dim" title={d.tasmota_id}>{d.tasmota_id || "—"}</td>
                      <td className="mono dim">{d.mac}</td>
                      <td title={d.chip}>{d.chip || "—"}</td>
                      <td title={d.project.name}>{d.project.name}</td>
                      <td title={d.batch?.label ?? ""}>{d.batch?.label ?? "—"}</td>
                      <td className="mono dim" title={d.imei}>{d.imei || "—"}</td>
                      <td className="num">{d.runs}</td>
                      <td>{d.last_status ? <StatusPill status={d.last_status} /> : "—"}</td>
                      <td className="muted">{fmtWhen(d.last_seen)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
