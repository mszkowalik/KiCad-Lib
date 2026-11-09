/** What must happen, and when (decision 0107): every dated step of the plan,
 *  week by week. Ours to do, the customer's, and what suppliers deliver.
 *
 *  It is a calendar, not a list of records, so it is not a `DataTable`: the
 *  week is the unit a reader plans with, and a sortable column would take the
 *  weeks apart. It opens on the past weeks and the next eight, and the rest is
 *  one click away. */
import { useState } from "react";
import { Link } from "react-router-dom";

import type { PlanEvent } from "../../api";
import { NarrowChip } from "../FoldSection";
import { StatusPill } from "../Ui";
import { colorStyle, dayNo, longDay, parseLink, shortDay, weekStart, weekdayDay, type PlanLink, type ProjectInfo } from "./planUtil";

type Filter = "" | "ours" | "customer" | "supplier" | "problem";

const WEEKS_AHEAD = 8;
const MONEY_KINDS = new Set(["order", "advance", "invoice", "payment"]);

export default function PlanAgenda({ events, today, projects, currency, onLink }: {
  events: PlanEvent[];
  today: string;
  projects: ProjectInfo[];
  currency: string;
  onLink: (link: PlanLink) => void;
}) {
  const [filter, setFilter] = useState<Filter>("");
  const [all, setAll] = useState(false);
  const t = dayNo(today) ?? 0;
  const thisWeek = weekStart(t);
  const project = new Map(projects.map((p) => [p.id, p]));
  const shown = events.filter((e) =>
    filter === "" ? true : filter === "problem" ? e.problem : e.party === filter);
  const weeks = new Map<number, PlanEvent[]>();
  for (const e of shown) {
    const d = dayNo(e.day);
    if (d == null) continue;
    const k = weekStart(d);
    const list = weeks.get(k) ?? [];
    list.push(e);
    weeks.set(k, list);
  }
  const keys = [...weeks.keys()].sort((a, b) => a - b);
  const limit = thisWeek + 7 * WEEKS_AHEAD;
  const visible = all ? keys : keys.filter((k) => k < limit);
  const hidden = keys.length - visible.length;
  const count = (f: Filter) => events.filter((e) => (f === "problem" ? e.problem : e.party === f)).length;
  const problems = count("problem");

  return (
    <div className="card pad">
      <h2 className="card-title">What must happen, and when</h2>
      <p className="muted dim">
        Every dated step of the plan, week by week: ours, the customer&apos;s and the suppliers&apos;.
      </p>
      <div className="stat-row">
        <NarrowChip value="" current={filter} onNarrow={() => setFilter("")} n={events.length}>all</NarrowChip>
        <NarrowChip value="ours" current={filter} onNarrow={setFilter} n={count("ours")} tone="acc">our actions</NarrowChip>
        <NarrowChip value="customer" current={filter} onNarrow={setFilter} n={count("customer")} tone="ok">customer</NarrowChip>
        <NarrowChip value="supplier" current={filter} onNarrow={setFilter} n={count("supplier")}>suppliers</NarrowChip>
        <NarrowChip value="problem" current={filter} onNarrow={setFilter} n={problems} tone={problems ? "err" : undefined}>
          only problems
        </NarrowChip>
      </div>
      {visible.length === 0 ? <p className="muted">Nothing matches this filter.</p> : null}
      {visible.map((k) => {
        const list = weeks.get(k) ?? [];
        return (
          <section key={k} className="plan-week">
            <h3 className="plan-week-head">
              {shortDay(k)} to {longDay(k + 6)}
              {k === thisWeek ? <span className="stat-chip acc">this week</span> : null}
              <span className="fold-count">{list.length}</span>
            </h3>
            {list.map((e, i) => {
              const d = dayNo(e.day);
              const p = e.project_id != null ? project.get(e.project_id) : undefined;
              const link = parseLink(e.ref);
              return (
                <div key={`${e.ref}-${e.kind}-${i}`} className={`plan-ev${d != null && d < t ? " past" : ""}`}>
                  <span className="plan-ev-day">{weekdayDay(d)}</span>
                  <span className={`plan-party ${e.party}`}>{e.kind}</span>
                  <span className="plan-ev-text">
                    {p ? <span className="plan-ptag" style={colorStyle(p.color)}>{p.name}</span> : null}
                    {e.text}
                  </span>
                  <span className="plan-ev-amt">
                    {e.amount != null
                      ? `${e.amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${MONEY_KINDS.has(e.kind) ? currency : "PLN"}`
                      : ""}
                  </span>
                  <span className="plan-ev-st">
                    <StatusPill status={e.status} />
                    {link?.kind === "href" ? (
                      <Link className="comp-link" to={link.to} title={`Open ${link.label}`}>open</Link>
                    ) : link ? (
                      <button type="button" className="btn-link" onClick={() => onLink(link)}>
                        {link.kind === "part" ? "part" : "open"}
                      </button>
                    ) : null}
                  </span>
                </div>
              );
            })}
          </section>
        );
      })}
      {hidden > 0 || all ? (
        <button type="button" className="btn btn-sm" onClick={() => setAll((v) => !v)}>
          {all ? `Show the next ${WEEKS_AHEAD} weeks only` : `Show the remaining ${hidden} weeks`}
        </button>
      ) : null}
    </div>
  );
}
