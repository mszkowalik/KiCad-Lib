/** The Overview of a plan (decision 0107): the summary figures, the blockers,
 *  the design inputs that changed since a person last reviewed them, the
 *  timeline, and the contract checks that fail. A check that passes draws
 *  nothing, and so does a design nobody changed. */
import { markPlanReviewed, type PlanChange, type PlanFull } from "../../api";
import CountTile from "../CountTile";
import { StatChip } from "../FoldSection";
import PlanBlockers from "./PlanBlockers";
import PlanTimeline from "./PlanTimeline";
import { dayNo, kilo, longDay, shortDay, units, type Apply, type PlanLink, type ProjectInfo } from "./planUtil";

function Kpis({ full, projects }: { full: PlanFull; projects: ProjectInfo[] }) {
  const s = full.schedule;
  const cur = full.plan.currency;
  const byProject = projects
    .map((p) => ({ p, n: s.orders.reduce((a, o) => a + o.lines.filter((l) => l.project_id === p.id).reduce((b, l) => b + l.qty, 0), 0) }))
    .filter((x) => x.n);
  const total = byProject.reduce((a, x) => a + x.n, 0);
  const days = s.orders.flatMap((o) => [dayNo(o.first_delivery), dayNo(o.last_delivery)]).filter((d): d is number => d != null);
  const first = days.length ? Math.min(...days) : null;
  const last = days.length ? Math.max(...days) : null;
  const count = (sev: string) => s.blockers.filter((b) => b.severity === sev).length;
  const drafts = s.orders.filter((o) => o.draft).length;
  return (
    <div className="counts">
      <CountTile value={units(total)} label="units"
        title={byProject.map((x) => `${units(x.n)} ${x.p.name}`).join(" · ") || undefined} />
      <CountTile value={`${s.orders.length}`} label={drafts === s.orders.length ? "draft orders" : `orders, ${drafts} draft`} />
      <CountTile value={first != null ? `${shortDay(first)} – ${shortDay(last)}` : "—"} label="deliveries"
        title={first != null ? `${longDay(first)} to ${longDay(last)}, ${s.weeks.length} delivery days` : undefined} />
      <CountTile value={`${kilo(s.cash.total_net)}`} label={`net ${cur}`} title={`${s.cash.total_net.toLocaleString()} ${cur} net`} />
      <CountTile value={`${kilo(s.cash.total_gross)}`} label={`gross ${cur}`} title={`${s.cash.total_gross.toLocaleString()} ${cur} gross`} />
      <CountTile value={count("block")} label="blocking" bad={count("block") > 0} />
      <CountTile value={count("risk")} label="at risk" />
      <CountTile value={count("decide")} label="wait for a decision" />
    </div>
  );
}

function ChangeBlock({ change, name }: { change: PlanChange; name: string }) {
  const bom = change.bom;
  return (
    <div className="plan-change">
      <h3 className="plan-sub">{name}</h3>
      <p>
        {change.snapshot_from !== change.snapshot_to ? <>Snapshot {change.snapshot_from ?? "—"} → {change.snapshot_to ?? "—"}. </> : null}
        {change.process_from !== change.process_to ? <>Process version {change.process_from ?? "—"} → {change.process_to ?? "—"}.</> : null}
      </p>
      {bom ? (
        <>
          <div className="stat-row">
            <StatChip n={bom.counts.added} tone={bom.counts.added ? "warn" : undefined}>added</StatChip>
            <StatChip n={bom.counts.removed} tone={bom.counts.removed ? "warn" : undefined}>removed</StatChip>
            <StatChip n={bom.counts.changed} tone={bom.counts.changed ? "warn" : undefined}>changed</StatChip>
          </div>
          <ul className="plan-change-list">
            {bom.added.slice(0, 6).map((r) => <li key={`a${r.refs}`}><b>+</b> {r.refs}: {r.qty} × {r.value}{r.lcsc ? ` (${r.lcsc})` : ""}</li>)}
            {bom.removed.slice(0, 6).map((r) => <li key={`r${r.refs}`}><b>−</b> {r.refs}: {r.qty} × {r.value}{r.lcsc ? ` (${r.lcsc})` : ""}</li>)}
            {bom.changed.slice(0, 6).map((r) => (
              <li key={`c${r.from.refs}`}><b>~</b> {r.from.refs}: {r.from.qty} × {r.from.value} → {r.to.qty} × {r.to.value}</li>
            ))}
          </ul>
          {bom.counts.added + bom.counts.removed + bom.counts.changed > 18 ? (
            <p className="muted dim">The first rows of each kind. The project&apos;s Design tab compares the two snapshots in full.</p>
          ) : null}
        </>
      ) : (
        <p className="muted dim">The BOM did not change, or no earlier snapshot was recorded.</p>
      )}
    </div>
  );
}

function DesignChanges({ full, projects, apply }: { full: PlanFull; projects: ProjectInfo[]; apply: Apply }) {
  const changes = full.schedule.changes.filter((c) => !c.first);
  if (!changes.length) return null;
  const name = new Map(projects.map((p) => [p.id, p.name]));
  return (
    <div className="card pad">
      <div className="fold-bar">
        <h2 className="card-title">A design input changed since the last review</h2>
        <button type="button" className="btn btn-sm btn-primary plan-actions"
          onClick={() => void apply("the design review", () => markPlanReviewed(full.plan.id))}>
          Reviewed
        </button>
      </div>
      <p className="muted dim">
        The planned batches already follow the new inputs, and the parts balance counts them. Read the
        difference, then mark it reviewed: the planned batches are moved to it, and an ordered batch keeps its own.
      </p>
      {changes.map((c) => <ChangeBlock key={c.project_id} change={c} name={name.get(c.project_id) ?? `project ${c.project_id}`} />)}
    </div>
  );
}

function Checks({ full }: { full: PlanFull }) {
  const bad = full.schedule.checks.filter((c) => !c.ok || c.skipped);
  if (!bad.length) return null;
  return (
    <div className="card pad">
      <h2 className="card-title">Contract checks</h2>
      <p className="muted dim">Only a check that fails, or could not run, is listed. The blockers above say what to do.</p>
      <ul className="plan-checks">
        {bad.map((c) => (
          <li key={c.key}>
            <span className={c.skipped ? "pill neutral" : "pill err"}>{c.skipped ? "not run" : "fails"}</span>
            <span>
              {c.label}
              {c.skipped ? <span className="muted">: no value is set on Setup.</span> : null}
              {c.items.length ? <span className="muted">: {c.items.join(", ")}</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function PlanOverview({ full, projects, apply, onLink, onOrder }: {
  full: PlanFull;
  projects: ProjectInfo[];
  apply: Apply;
  onLink: (link: PlanLink) => void;
  onOrder: (orderId: number) => void;
}) {
  return (
    <>
      <Kpis full={full} projects={projects} />
      {full.schedule.cycle ? <div className="banner-error">{full.schedule.cycle}</div> : null}
      <PlanBlockers blockers={full.schedule.blockers} today={full.schedule.today} onLink={onLink} />
      <DesignChanges full={full} projects={projects} apply={apply} />
      <PlanTimeline full={full} projects={projects} onOrder={onOrder} />
      <Checks full={full} />
    </>
  );
}
