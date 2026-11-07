/** One physical device: full identity (ESP + LTE module + SIM), the config
 *  values applied to it, and every programming attempt ever made. */
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  errorMessage,
  getDevice,
  patchDevice,
  type DeviceDetailPayload,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import AutoTextarea from "../components/AutoTextarea";
import Field, { CheckField } from "../components/Field";
import FoldSection, { StatChip } from "../components/FoldSection";
import { BackLink, StatusPill } from "../components/Ui";
import DeviceHistoryCard from "../components/DeviceHistoryCard";
import TwinCard from "../components/TwinCard";
import DevicePresenceCard from "../components/DevicePresenceCard";
import CheckGrid from "../components/flasher/CheckGrid";
import { fmtDuration } from "../components/flasher/common";
import { localWhen } from "../format";
import { useLoad } from "../components/useLoad";
import PageShell, { PageLoading } from "../components/PageShell";

const ACT_WORD: Record<string, string> = {
  flash: "programming run", test: "test", mark: "marking job", erase: "erase",
};

const CONFIG_COLS: Column<DeviceDetailPayload["configs"][number]>[] = [
  // `current` can still be false when a LATER run changed one key only — then
  // that key's live value came from a different run and this one is stale.
  { key: "key", label: "Key", width: 26, className: "mono", get: (c) => `${c.key}${c.current ? "" : " (superseded)"}` },
  { key: "value", label: "Value", width: 38, className: "mono", get: (c) => c.value },
  {
    key: "by",
    label: "Set by",
    width: 16,
    get: (c) => c.set_by_run_id ?? "",
    render: (c) => (c.set_by_run_id ? (
      <Link className="val-link" to={`/production/flash-runs/${c.set_by_run_id}`}>run #{c.set_by_run_id}</Link>
    ) : "—"),
  },
  { key: "when", label: "When", width: 20, className: "muted", get: (c) => c.set_at ?? "", render: (c) => localWhen(c.set_at) },
];

/* The card sits in the narrow column, and a filter box needs 76 px with its cell,
   so only the two columns that can hold one take one. STARTED is a LENGTH, not a
   share: a timestamp has a fixed width and "2026-09-16 20:…" is not a time (same
   rule as the device list's serial). Batch, Procedure and By are the ones that
   truncate, and each carries a title. */
const RUN_COLS: Column<DeviceDetailPayload["runs"][number]>[] = [
  {
    key: "run",
    label: "Run",
    width: 24,
    interactive: false,
    sortable: true,
    get: (r) => r.id,
    title: (r) => `attempt ${r.attempt_no}`,
    // "#6345 (attempt 3)" clipped to "#6345 …", which hid the attempt it was
    // spelling out, so the attempt is a dot and a number.
    render: (r) => (
      <>
        <Link className="comp-link" to={`/production/flash-runs/${r.id}`}>#{r.id}</Link>
        {r.attempt_no > 1 ? <span className="muted dim"> ·{r.attempt_no}</span> : null}
      </>
    ),
  },
  { key: "result", label: "Result", width: 20, get: (r) => r.status, render: (r) => <StatusPill status={r.status} /> },
  {
    key: "batch",
    label: "Batch",
    width: 9,
    interactive: false,
    sortable: true,
    get: (r) => r.production_run?.label ?? "",
    render: (r) => (r.production_run ? (
      <Link className="val-link" to={`/production/batches/${r.production_run.id}`}>{r.production_run.label}</Link>
    ) : "—"),
  },
  {
    key: "procedure",
    label: "Procedure",
    width: 18,
    get: (r) => (r.deployment ? `${r.deployment.name} v${r.deployment.version_no}` : "—"),
  },
  // "By", not "Operator": the header was the widest thing in a column that
  // prints a name or a dash.
  { key: "by", label: "By", width: 9, interactive: false, sortable: true, get: (r) => r.operator || "—" },
  {
    key: "took",
    label: "Took",
    width: 20,
    numeric: true,
    interactive: false,
    sortable: true,
    get: (r) => r.duration_ms ?? "",
    render: (r) => fmtDuration(r.duration_ms),
  },
  {
    key: "started",
    label: "Started",
    width: "150px",
    className: "muted",
    interactive: false,
    sortable: true,
    get: (r) => r.started_at ?? "",
    render: (r) => localWhen(r.started_at),
  },
];

export default function DeviceDetail() {
  const { id } = useParams();
  const deviceId = Number(id);
  const [reveal, setReveal] = useState(false);
  const [notes, setNotes] = useState("");
  const [notesDirty, setNotesDirty] = useState(false);

  const { data: device, error, setError } = useLoad(
    (signal) =>
      getDevice(deviceId, reveal, signal).then((d) => {
        setNotes(d.notes);
        setNotesDirty(false);
        return d;
      }),
    [deviceId, reveal],
    { keep: true },
  );

  const saveNotes = async () => {
    try {
      await patchDevice(deviceId, notes);
      setNotesDirty(false);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  if (error || !device) return <PageLoading error={error} label="Loading device…" />;

  // Is it programmed: the server decides (`checks.verdict`) — the config run,
  // then an ACTIVE test after it, then no erase since. The page only prints it,
  // so the device list and any later reader cannot drift from this answer.
  const v = device.verdict;

  const runLink = (r: NonNullable<typeof v.config_run>) => (
    <Link className="val-link" to={`/production/flash-runs/${r.id}`}>
      #{r.id}
    </Link>
  );

  return (
    <PageShell>
      <div className="toolbar">
        <BackLink to="/production/devices">← Devices</BackLink>
        <h1 className="mono">{device.serial || device.mac}</h1>
        {device.last_status ? <StatusPill status={device.last_status} /> : null}
        <span className="toolbar-total">
          {device.project.name} · first seen {localWhen(device.first_seen)} · last seen {localWhen(device.last_seen)}
        </span>
      </div>

      <div className="detail-page">
        <div className="detail-left">
          <div className="card pad">
            <h2 className="card-title">What this device is proven to do</h2>
            {/* The verdict is a sentence the server wrote, plus the runs it
                rests on. Marking never appears here: it changes nothing. */}
            <p>
              <StatusPill status={v.programmed ? "programmed" : "not programmed"} />{" "}
              {v.reason}
              {v.requires_test ? " — this project's test must pass after every programming run." : ""}
            </p>
            <p className="muted dim">
              {v.config_run ? (
                <>
                  config {runLink(v.config_run)} ({v.config_run.status}) {localWhen(v.config_run.at)}
                </>
              ) : (
                <>no programming run</>
              )}
              {v.test_run ? (
                <> · test {runLink(v.test_run)} ({v.test_run.status}) {localWhen(v.test_run.at)}</>
              ) : null}
              {v.erased_after ? (
                <> · erased {runLink(v.erased_after)} {localWhen(v.erased_after.at)}</>
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

          <FoldSection
            title="Configuration"
            count={device.configs.length}
            foldKey={`device:${deviceId}:config`}
            chips={device.config_superseded > 0 ? <StatChip n={device.config_superseded}>earlier values</StatChip> : undefined}
            actions={
              <CheckField checked={reveal} onChange={setReveal}>reveal secrets</CheckField>
            }
          >
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
                <DataTable
                  rows={device.configs}
                  rowKey={(c) => `${c.key}:${c.set_by_run_id ?? ""}:${c.set_at ?? ""}`}
                  rowClass={(c) => (c.current ? "" : "dim")}
                  columns={CONFIG_COLS}
                />
              </div>
            )}
          </FoldSection>

          <div className="card pad">
            <h2 className="card-title">Notes</h2>
            <Field>
              <AutoTextarea
                className="text"
                value={notes}
                onChange={(e) => {
                  setNotes(e.target.value);
                  setNotesDirty(true);
                }}
              />
            </Field>
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
          <TwinCard deviceId={deviceId} />
          {/* The broker's live view. Deliberately NOT merged into the check
              grid or the identity table: those are what the bench proved and
              they never change, this is a cache that can be stale or absent. */}
          <DevicePresenceCard presence={device.presence} mac={device.mac} />
          <FoldSection
            title="Programming history"
            count={device.runs.length}
            foldKey={`device:${deviceId}:runs`}
            chips={
              <>
                {device.runs.some((r) => r.status === "fail") ? <StatChip n={device.runs.filter((r) => r.status === "fail").length} tone="err">fail</StatChip> : null}
                {device.runs.some((r) => r.status === "aborted") ? <StatChip n={device.runs.filter((r) => r.status === "aborted").length} tone="warn">aborted</StatChip> : null}
                <StatChip n={device.runs.filter((r) => r.status === "pass").length} tone="ok">pass</StatChip>
              </>
            }
          >
            <p className="muted dim">
              Every attempt, pass or fail — click through for the step timeline and the full
              serial log.
            </p>
            {device.runs.length === 0 ? (
              <p className="muted">No runs.</p>
            ) : (
              <div className="table-wrap">
                <DataTable
                  rows={device.runs}
                  rowKey={(r) => r.id}
                  columns={RUN_COLS}
                  defaultSort={{ key: "started", dir: "desc" }}
                />
              </div>
            )}
          </FoldSection>
        </div>
      </div>
    </PageShell>
  );
}
