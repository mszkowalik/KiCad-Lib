/** Batch → Devices: what the bench tried that the device list cannot show
 *  (`GET /api/flasher/production-runs/{id}/programming`).
 *
 *  An attempt that named no device is on no device's row. A device with attempts
 *  and no pass reads the same as a device with few attempts, unless a reader opens
 *  its row. A typed serial list has a gap only this reply states. The other figure
 *  in the reply, the devices with a pass, is what the list below already says.
 *
 *  A check that passes draws nothing, so this has no spinner and no empty state. A
 *  fetch that fails draws a banner: the check could not run.
 */
import { Link } from "react-router-dom";
import {
  getBatchProgramming,
  type ProgrammingRunSummary,
} from "../../api";
import DataTable, { type Column } from "../DataTable";
import { localWhen } from "../../format";
import FoldSection, { StatChip } from "../FoldSection";
import { ErrorBanner, StatusPill } from "../Ui";
import { useLoad } from "../useLoad";

const COLUMNS: Column<ProgrammingRunSummary>[] = [
  { key: "id", label: "Run", width: 8, className: "mono", get: (r) => r.id,
    render: (r) => <Link to={`/production/flash-runs/${r.id}`}>#{r.id}</Link> },
  { key: "at", label: "Started", width: 17, className: "mono", get: (r) => r.started_at ?? "",
    render: (r) => <>{localWhen(r.started_at)}</> },
  { key: "station", label: "Station", width: 9, get: (r) => r.station },
  { key: "procedure", label: "Procedure", width: 20,
    get: (r) => (r.deployment ? `${r.deployment.name} v${r.deployment.version_no}` : "—") },
  { key: "status", label: "Result", width: 10, get: (r) => r.status, render: (r) => <StatusPill status={r.status} /> },
  { key: "error", label: "Error", width: 36, get: (r) => r.error ?? "" },
];

export default function ProgrammingCoverage({ runId }: { runId: number }) {
  const { data, error } = useLoad((signal) => getBatchProgramming(runId, signal), [runId]);

  if (error) return <ErrorBanner message={`Programming coverage could not be read: ${error}`} />;
  if (!data) return null;
  const { unidentified_attempts: lost, unidentified_runs: lostRuns, failed_only: failed, missing, extra } = data;
  const count = lost + failed.length + missing.length + extra.length;
  if (!count) return null;

  const serials = (label: string, list: string[]) => (list.length ? (
    <p className="muted dim">{label}: <span className="mono">{list.join(", ")}</span></p>
  ) : null);
  return (
    <FoldSection
      title="Programming coverage"
      count={count}
      foldKey={`run:${runId}:coverage`}
      chips={
        <>
          {failed.length ? <StatChip n={failed.length} tone="err" title="Devices of this batch with attempts and no pass">never passed</StatChip> : null}
          {lost ? <StatChip n={lost} tone="warn" title="Attempts on this batch that ended before they named a device">attempts named no device</StatChip> : null}
          {missing.length ? <StatChip n={missing.length} tone="warn" title="On the batch's typed serial list, and no pass recorded">planned, not programmed</StatChip> : null}
          {extra.length ? <StatChip n={extra.length} tone="warn" title="Programmed with a pass, and not on the batch's typed serial list">programmed, not planned</StatChip> : null}
        </>
      }
    >
      {serials("Never passed", failed)}
      {serials("Planned, not programmed", missing)}
      {serials("Programmed, not planned", extra)}
      {lost ? (
        <>
          {lost > lostRuns.length ? <p className="muted dim">The newest {lostRuns.length} of {lost} attempts.</p> : null}
          <DataTable rows={lostRuns} rowKey={(r) => r.id} columns={COLUMNS} defaultSort={{ key: "at", dir: "desc" }} />
        </>
      ) : null}
    </FoldSection>
  );
}
