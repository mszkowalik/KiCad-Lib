/** The Deliveries & cash tab of a plan (decision 0107 items 4 and 20): units
 *  delivered by week, the advances against the purchases paid from them, the
 *  customer's payments by month and the advances due on each date against the
 *  limit. Every figure is the server's; nothing here adds money up except the
 *  totals line under a table, which sums the rows above it. */
import type { PlanFull } from "../../api";
import { amount } from "../../format";
import DataTable from "../DataTable";
import FoldSection, { StatChip } from "../FoldSection";
import { CashChart, DeliveriesChart } from "./PlanCharts";
import { fitColumns, monthName, units, useNarrow, type PlanColumn, type ProjectInfo } from "./planUtil";

type Month = PlanFull["schedule"]["cash"]["months"][number];
type Advance = PlanFull["schedule"]["advances"][number];

const fmt = (v: number) => v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function PlanMoney({ full, projects }: { full: PlanFull; projects: ProjectInfo[] }) {
  const s = full.schedule;
  const narrow = useNarrow();
  const cur = full.plan.currency;
  const cash = s.cash;
  const limit = full.plan.advance_limit_net;
  const overLimit = new Set(s.over_limit.map((a) => a.day));
  const low = cash.lowest;
  const purchases = cash.steps.length ? cash.steps[cash.steps.length - 1].cum_out : 0;
  const totalUnits = s.weeks.reduce((a, w) => a + w.total, 0);
  const overRate = s.coverage.filter((c) => c.over_rate.length);

  const payProjects = projects.filter((p) => cash.months.some((m) => m.by_project[String(p.id)]));
  const share = payProjects.length ? Math.floor(42 / payProjects.length) : 0;
  const monthCols: PlanColumn<Month>[] = [
    { key: "month", label: "Month", width: 58 - share * payProjects.length, narrow: 45, get: (m) => m.month, render: (m) => monthName(m.month) },
    ...payProjects.map((p): PlanColumn<Month> => ({
      key: `p${p.id}`, label: p.name, width: share, numeric: true,
      get: (m) => m.by_project[String(p.id)] ?? 0, render: (m) => fmt(m.by_project[String(p.id)] ?? 0),
    })),
    { key: "advance", label: "Advances", width: 14, numeric: true, get: (m) => m.advance, render: (m) => fmt(m.advance) },
    { key: "final", label: "Final invoices", width: 14, numeric: true, get: (m) => m.final, render: (m) => fmt(m.final) },
    { key: "total", label: `Total ${cur}`, width: 14, narrow: 55, numeric: true, get: (m) => m.total, render: (m) => fmt(m.total) },
  ];
  const sumAdv = cash.months.reduce((a, m) => a + m.advance, 0);
  const sumFin = cash.months.reduce((a, m) => a + m.final, 0);

  const advCols: PlanColumn<Advance>[] = [
    { key: "day", label: "Due", width: "104px", narrow: "104px", get: (a) => a.day, className: "mono" },
    { key: "orders", label: "Orders", width: 46, get: (a) => a.orders.join(", ") },
    { key: "net", label: `Net ${cur}`, width: 24, narrow: 36, numeric: true, get: (a) => a.net, render: (a) => fmt(a.net) },
    { key: "limit", label: "Limit", width: 30, narrow: 64, get: (a) => (overLimit.has(a.day) ? "over" : ""),
      render: (a) => overLimit.has(a.day) && limit != null
        ? <span className="pill err" title={`${fmt(a.net - limit)} ${cur} over the limit`}>{Math.round(a.net - limit).toLocaleString()} over</span> : null },
  ];

  return (
    <>
      <div className="plan-two">
        <div className="card pad">
          <h2 className="card-title">Deliveries by week</h2>
          <p className="muted dim">
            {units(totalUnits)} units in {s.weeks.length} deliveries. A dashed line is a project&apos;s line rate.
          </p>
          {s.weeks.length ? (
            <DeliveriesChart weeks={s.weeks} projects={projects} coverage={s.coverage} />
          ) : (
            <p className="muted">No delivery is planned yet.</p>
          )}
          {overRate.map((c) => (
            <div key={c.project_id} className="banner-warn">
              {c.project}: {c.over_rate.length} weeks need more than the line makes ({c.line_rate_week} a week), the
              first in the week of {c.over_rate[0].week} ({units(c.over_rate[0].units)}).
            </div>
          ))}
        </div>
        <div className="card pad">
          <h2 className="card-title">Cash: purchases paid from advances</h2>
          <p className="muted dim">
            Each purchase is paid from advances already received. An advance counts on the day it was paid,
            else on the day it falls due. Net {cur}.
          </p>
          <CashChart cash={cash} currency={cur} />
          {low ? (
            <p className={low.margin < 0 ? "err-text" : low.margin < 5000 ? "warn-text" : "muted"}>
              Purchases total {fmt(purchases)} {cur} net. The smallest margin is {fmt(low.margin)} {cur} on {low.day}.
            </p>
          ) : (
            <p className="muted">No purchase or batch cost is planned yet.</p>
          )}
        </div>
      </div>

      <div className="card pad">
        <h2 className="card-title">The customer&apos;s payments by month</h2>
        <p className="muted dim">
          Gross {cur}, by the month each payment falls due: the advance when the order is placed, the final
          invoice after the last delivery. A real invoice replaces the computed one.
        </p>
        <DataTable columns={fitColumns(monthCols, narrow)} rows={cash.months} rowKey={(m) => m.month} empty="No order yet." />
        {cash.months.length ? (
          <p className="muted">
            Total {amount(cash.total_gross, cur)} gross ({amount(cash.total_net, cur)} net): advances {fmt(sumAdv)},
            final invoices {fmt(sumFin)}.
          </p>
        ) : null}
      </div>

      <FoldSection title="Advances by due date" count={s.advances.length} foldKey={`plan-${full.plan.id}-advances`}
        chips={<>
          {s.over_limit.length ? <StatChip n={s.over_limit.length} tone="err">over the limit</StatChip> : null}
          {limit != null ? <StatChip>limit {fmt(limit)} net</StatChip> : <StatChip>no limit set</StatChip>}
        </>}>
        <p className="muted dim">
          The advances that fall due on one day, added up, against the customer&apos;s limit per due date.
        </p>
        <DataTable columns={fitColumns(advCols, narrow)} rows={s.advances} rowKey={(a) => a.day} empty="No advance yet." />
      </FoldSection>
    </>
  );
}
