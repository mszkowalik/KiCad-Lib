import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { DemandRow } from "../api";
import DataTable, { type Column } from "./DataTable";
import FoldSection, { StatChip } from "./FoldSection";
import { Spinner } from "./Ui";

const DEMAND_COLS: Column<DemandRow>[] = [
  {
    key: "project",
    label: "Project",
    width: 16,
    get: (r) => r.project,
    render: (r) => <Link className="comp-link" to={`/projects/${r.project_id}`}>{r.project}</Link>,
  },
  { key: "open", label: "Open", width: 9, numeric: true, get: (r) => r.open, render: (r) => <>{r.open.toLocaleString()}</> },
  { key: "orders", label: "Orders", width: 8, numeric: true, get: (r) => r.open_orders },
  {
    key: "sellable",
    // The widest header on the row, and it names the rule the column applies, so
    // it has to be readable: 12 where the other figures take 9.
    label: (
      <span title="Devices that can actually be sold — condition `ok`. A faulty or prototype unit is on the shelf and a shipment may never draw it, so it is not supply.">
        Sellable now
      </span>
    ),
    width: 12,
    numeric: true,
    get: (r) => r.on_shelf,
    render: (r) => <>{r.on_shelf.toLocaleString()}</>,
  },
  { key: "planned", label: "Planned", width: 9, numeric: true, get: (r) => r.planned, render: (r) => <>{r.planned.toLocaleString()}</> },
  {
    key: "short",
    label: "Short",
    width: 9,
    numeric: true,
    get: (r) => r.shortfall,
    render: (r) => (r.shortfall ? (
      <span className="err-text">{r.shortfall.toLocaleString()}</span>
    ) : r.surplus ? (
      <span className="muted">+{r.surplus.toLocaleString()}</span>
    ) : "—"),
  },
  {
    key: "batches",
    label: "Planned batches",
    width: 37,
    get: (r) => r.planned_runs.map((b) => b.label).join(", "),
    render: (r) => (r.planned_runs.length === 0 ? (
      <span className="muted">—</span>
    ) : r.planned_runs.map((b, i) => (
      <span key={b.run_id}>
        {i ? ", " : ""}
        <Link className="comp-link" to={`/production/batches/${b.run_id}`}>{b.label}</Link>
        <span className="muted"> ({b.qty.toLocaleString()})</span>
      </span>
    ))),
  },
];

/** Open demand per project against the shelf and the planned batches. */
export default function DemandCard({ rows, title = "Demand" }: { rows: DemandRow[] | null; title?: string }) {
  const live = useMemo(() => (rows ? rows.filter((r) => r.open || r.on_shelf || r.planned) : []), [rows]);
  const shortUnits = live.reduce((a, r) => a + r.shortfall, 0);
  return (
    <FoldSection
      title={title}
      count={live.length}
      foldKey={`demand:${title}`}
      chips={live.length ? (
        <>
          {shortUnits ? <StatChip n={shortUnits.toLocaleString()} tone="err">short</StatChip> : null}
          <StatChip n={live.reduce((a, r) => a + r.open, 0).toLocaleString()} tone="acc">open</StatChip>
          <StatChip n={live.reduce((a, r) => a + r.on_shelf, 0).toLocaleString()}>sellable now</StatChip>
          <StatChip n={live.reduce((a, r) => a + r.planned, 0).toLocaleString()}>planned</StatChip>
        </>
      ) : undefined}
    >
      {/* `.card-subtitle` is an uppercase mono LABEL, 11px with letter-spacing.
          A paragraph in it is five lines of shouting — which is what this card
          and the one below had until 2026-09-21. Explanations go in
          `muted dim`, the way the devices tab already did it. */}
      <p className="muted dim">
        Open is what customers ordered and have not received. <b>Sellable now</b> counts
        only devices a shipment may draw — condition <code>ok</code>. A faulty or prototype
        unit is on the shelf and can never leave, so counting it as supply would say an
        order can be filled by devices that cannot go out of the door; every device we
        hold, whatever condition, is on <Link to="/stock/finished">Stock → Finished devices</Link>. Planned
        counts every batch still in the planned state, and Short is what nothing covers
        yet.
      </p>
      {!rows ? (
        <Spinner label="Counting…" />
      ) : live.length === 0 ? (
        <p className="muted">Nothing open.</p>
      ) : (
        <DataTable rows={live} rowKey={(r) => r.project_id} columns={DEMAND_COLS} />
      )}
    </FoldSection>
  );
}
