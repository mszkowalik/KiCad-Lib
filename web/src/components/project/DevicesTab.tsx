/** Every device built for this project, and what the MQTT broker says about
 *  each one right now.
 *
 *  The supply-side twin of the Orders tab: Orders shows what was asked for,
 *  this shows what was made and where it ended up.
 *
 *  THREE PRESENCE STATES, and the tab refuses to collapse them into two.
 *  `online` and `offline` are the broker speaking. `unknown` is the platform
 *  admitting it has never heard the device — never deployed, or the watcher is
 *  off. Counting "unknown" as "offline" would paint every shelf unit red.
 *
 *  Read-only. Nothing here commands a device: the watcher subscribes and never
 *  publishes (api/app/services/mqtt_monitor.py).
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  errorMessage,
  getProjectDevices,
  isAbortError,
  type ProjectDeviceRow,
  type ProjectDevicesPayload,
  type ProjectInfo,
} from "../../api";
import DataTable, { type Column } from "../DataTable";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { fmtWhen } from "../flasher/common";

interface Props {
  project: ProjectInfo;
}

const PRESENCE_FILTERS = [
  { key: "", label: "All" },
  { key: "online", label: "Online" },
  { key: "offline", label: "Offline" },
  { key: "unknown", label: "Never seen" },
] as const;

function ago(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 90) return `${secs}s`;
  const mins = Math.round(secs / 60);
  if (mins < 90) return `${mins} min`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} d`;
}

export default function DevicesTab({ project }: Props) {
  const [data, setData] = useState<ProjectDevicesPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [presence, setPresence] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    const ac = new AbortController();
    setData(null);
    getProjectDevices(project.id, { presence }, ac.signal)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [project.id, presence]);

  const rows = useMemo(() => data?.items ?? [], [data]);

  const cols: Column<ProjectDeviceRow>[] = [
    {
      key: "serial",
      label: "Device",
      width: "13ch",
      className: "mono",
      get: (r) => r.serial || r.tasmota_id,
    },
    {
      key: "presence",
      label: "Broker",
      width: 10,
      // Sorted online -> offline -> never, because the question this column
      // answers is "what is alive", not "what sorts first alphabetically".
      get: (r) => (r.presence === null ? "never seen" : r.presence.online ? "online" : "offline"),
      sortValue: (r) => (r.presence === null ? 2 : r.presence.online ? 0 : 1),
      render: (r) =>
        r.presence === null ? (
          <span className="pill">never seen</span>
        ) : (
          <span className={`pill ${r.presence.online ? "ok" : "err"}`}>
            {r.presence.online ? "online" : "offline"}
          </span>
        ),
    },
    {
      key: "last_seen",
      label: "Last heard",
      width: 9,
      className: "mono",
      get: (r) => r.presence?.last_seen_at ?? "",
      sortValue: (r) => (r.presence?.last_seen_at ? Date.parse(r.presence.last_seen_at) : 0),
      render: (r) => <>{ago(r.presence?.last_seen_at ?? null)}</>,
      title: (r) => fmtWhen(r.presence?.last_seen_at ?? null),
    },
    {
      key: "state",
      label: "Stock state",
      width: 10,
      get: (r) => r.state || "—",
    },
    {
      key: "inverter",
      label: "Inverter",
      width: 11,
      get: (r) => r.presence?.inverter || "—",
    },
    {
      key: "inverter_sn",
      label: "Inverter serial",
      width: 14,
      className: "mono",
      get: (r) => r.presence?.inverter_sn || "—",
    },
    {
      key: "fw",
      label: "Firmware",
      width: 9,
      className: "mono",
      get: (r) => r.presence?.dongle_version || "—",
    },
    {
      key: "temp",
      label: "Temp",
      width: 7,
      numeric: true,
      get: (r) => r.presence?.temperature_c ?? null,
      render: (r) =>
        r.presence?.temperature_c != null ? <>{r.presence.temperature_c.toFixed(1)} °C</> : <>—</>,
    },
    {
      key: "built",
      label: "Built",
      width: 8,
      get: (r) => r.last_status || "—",
      render: (r) => (r.last_status ? <StatusPill status={r.last_status} /> : <>—</>),
    },
  ];

  const s = data?.summary;

  return (
    <div>
      {error ? <ErrorBanner message={error} /> : null}

      <div className="card pad">
        <div className="toolbar">
          <h2 className="card-title">Devices built for {project.name}</h2>
          <span className="toolbar-total">
            {s ? `${s.total.toLocaleString()} device(s)` : ""}
          </span>
        </div>
        {s ? (
          <p className="card-subtitle">
            <span className="pill ok">{s.online.toLocaleString()} online</span>{" "}
            <span className="pill err">{s.offline.toLocaleString()} offline</span>{" "}
            <span className="pill">{s.unknown.toLocaleString()} never seen</span>
          </p>
        ) : null}
        <p className="muted dim">
          Live from the MQTT broker, read-only. &ldquo;Never seen&rdquo; means the broker has
          never mentioned the device — it may never have been deployed, or the watcher may be
          off. It does not mean the device is faulty.
        </p>
        <div className="btn-row">
          {PRESENCE_FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={`btn btn-sm${presence === f.key ? " btn-primary" : ""}`}
              onClick={() => setPresence(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="card pad">
        {data === null ? (
          <Spinner label="Loading devices…" />
        ) : (
          <>
            {data.truncated ? (
              <p className="muted dim">
                Showing the newest {rows.length.toLocaleString()} devices only. Narrow the view
                with the filters above.
              </p>
            ) : null}
            <DataTable
              columns={cols}
              rows={rows}
              rowKey={(r) => r.id}
              persistKey="project-devices"
              defaultSort={{ key: "presence", dir: "asc" }}
              onRowClick={(r) => navigate(`/production/devices/${r.id}`)}
              empty="No devices recorded for this project yet."
            />
          </>
        )}
      </div>
    </div>
  );
}
