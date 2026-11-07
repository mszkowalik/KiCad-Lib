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
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  errorMessage,
  getProjectDevices,
  isAbortError,
  projectMosquittoPath,
  type ProjectDeviceRow,
  type ProjectDevicesPayload,
  type ProjectInfo,
} from "../../api";
import { since, localWhen } from "../../format";
import DataTable, { type Column } from "../DataTable";
import { CONDITION_WORD } from "../FinishedProductsCard";
import { NarrowChip } from "../FoldSection";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";

interface Props {
  project: ProjectInfo;
  /** Scope to one BATCH. The run page draws the same rows rather than keeping a
   *  second device list of its own — the batch a device belongs to is
   *  `DeviceUnit.production_run_id`, and that is the only copy of it that gets
   *  corrected (decision 0029). */
  runId?: number;
}

/** How a `?state=` / `?condition=` in the URL reads on screen. The server
 *  already filtered on both (`getProjectDevices` has taken them since it was
 *  written); this tab simply never passed them, so a link could not say
 *  "these devices" — only "this project". */
const STATE_WORD: Record<string, string> = {
  in_stock: "on the shelf",
  allocated: "allocated to an order",
  shipped: "shipped",
  disposed: "disposed of",
  missing: "missing — not found at a stock count",
};

export default function DevicesTab({ project, runId }: Props) {
  const [data, setData] = useState<ProjectDevicesPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [presence, setPresence] = useState("");
  const navigate = useNavigate();
  // THE URL CARRIES THE NARROWING, so the view is linkable and the browser's
  // back button undoes it. A filter held only in component state would make
  // "show me the 30 faulty Aquas" impossible to send to anybody.
  const [searchParams, setSearchParams] = useSearchParams();
  const state = searchParams.get("state") ?? "";
  const condition = searchParams.get("condition") ?? "";
  const clearScope = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("state");
    next.delete("condition");
    setSearchParams(next, { replace: true });
  };

  useEffect(() => {
    const ac = new AbortController();
    setData(null);
    getProjectDevices(project.id, { presence, runId, state, condition }, ac.signal)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [project.id, presence, runId, state, condition]);

  const rows = useMemo(() => data?.items ?? [], [data]);

  const cols: Column<ProjectDeviceRow>[] = [
    {
      key: "serial",
      label: "Device",
      width: "126px",
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
        <StatusPill status={r.presence === null ? "never seen" : r.presence.online ? "online" : "offline"} />,
    },
    {
      key: "last_seen",
      label: "Last heard",
      width: 9,
      className: "mono",
      get: (r) => r.presence?.last_seen_at ?? "",
      sortValue: (r) => (r.presence?.last_seen_at ? Date.parse(r.presence.last_seen_at) : 0),
      render: (r) => <>{since(r.presence?.last_seen_at) ?? "—"}</>,
      title: (r) => localWhen(r.presence?.last_seen_at ?? null),
    },
    {
      key: "state",
      label: "Stock state",
      width: 10,
      get: (r) => r.state || "—",
    },
    {
      // WHERE it is and WHAT it is are two axes. A unit reading `in_stock` +
      // `faulty` is on the shelf and unsellable, which is a different fact from
      // `disposed` — and filing the first as the second is what hid 32 units.
      key: "condition",
      label: "Condition",
      width: 10,
      get: (r) => r.condition || "ok",
      render: (r) =>
        r.condition && r.condition !== "ok" ? (
          <span className={`pill ${r.condition === "faulty" ? "err" : "warn"}`}>{r.condition}</span>
        ) : (
          <span className="muted">ok</span>
        ),
    },
    {
      key: "attempts",
      label: "Attempts",
      width: 9,
      numeric: true,
      get: (r) => Object.values(r.attempts ?? {}).reduce((a, b) => a + b, 0),
      render: (r) => {
        const total = Object.values(r.attempts ?? {}).reduce((a, b) => a + b, 0);
        if (!total) return <span className="muted">—</span>;
        const failed = total - (r.attempts.pass ?? 0);
        return (
          <span title={Object.entries(r.attempts).map(([k, v]) => `${k}: ${v}`).join(" · ")}>
            {total}
            {failed > 0 ? <span className="warn-text"> ({failed} not passed)</span> : null}
          </span>
        );
      },
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
      width: 13,
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
      width: 8,
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
  /** The main list of this tab: a click on a chip narrows it, a second click undoes that. */
  return (
    <div>
      {error ? <ErrorBanner message={error} /> : null}

      <div className="card pad">
        <div className="toolbar">
          <h2 className="card-title">Devices built for {project.name}</h2>
          <span className="toolbar-total">
            {s ? `${s.total.toLocaleString()} device(s)` : ""}
          </span>
          {/* Not on a batch's view of this tab: the batch offers its own file on Settings. */}
          {runId === undefined ? (
            <a
              className="btn btn-sm"
              href={projectMosquittoPath(project.id)}
              download
              title="Plaintext user:password file for every device of this project, with every name a device was ever programmed under. Hash it with mosquitto_passwd -U before you deploy it."
            >
              MQTT accounts
            </a>
          ) : null}
        </div>
        {s ? (
          <div className="stat-row">
            <NarrowChip n={s.online.toLocaleString()} tone="acc" value="online" current={presence} onNarrow={setPresence}>online</NarrowChip>
            <NarrowChip n={s.offline.toLocaleString()} value="offline" current={presence} onNarrow={setPresence}>offline</NarrowChip>
            <NarrowChip n={s.unknown.toLocaleString()} value="unknown" current={presence} onNarrow={setPresence}>never seen</NarrowChip>
          </div>
        ) : null}
        {state || condition ? (
          // Named, and removable. A list that is quietly showing a tenth of the
          // devices reads as a list of every device — which is how somebody
          // concludes the other nine tenths do not exist.
          <div className="toolbar">
            <span className="pill neutral">
              Showing only{" "}
              {[CONDITION_WORD[condition] ?? condition, STATE_WORD[state] ?? state]
                .filter(Boolean)
                .join(" · ")}
            </span>
            <button type="button" className="btn btn-sm" onClick={clearScope}>
              Show every device
            </button>
          </div>
        ) : null}
        <p className="muted dim">
          Live from the MQTT broker, read-only. &ldquo;Never seen&rdquo; means the broker has
          never mentioned the device — it may never have been deployed, or the watcher may be
          off. It does not mean the device is faulty.
        </p>
      </div>

      <div className="card pad">
        {data === null ? (
          <Spinner label="Loading devices…" />
        ) : (
          <>
            {data.truncated ? (
              <p className="muted dim">
                Showing the newest {rows.length.toLocaleString()} devices only. Narrow the view
                with the chips above.
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
