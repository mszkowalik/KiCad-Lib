/** The plan's blockers in three columns (decision 0107): what stops a date,
 *  what may stop one, and what waits for a person. The server computes every
 *  card; this only sorts them by the day they must be acted on and gives each
 *  one the place that fixes it.
 *
 *  A column with nothing in it is not drawn, and a plan with no blocker draws
 *  no card at all: a check that passes draws nothing. */
import { useState } from "react";
import { Link } from "react-router-dom";

import type { PlanBlocker } from "../../api";
import { blockerLink, dayNo, shortDay, type PlanLink } from "./planUtil";

const COLUMNS: { sev: PlanBlocker["severity"]; title: string }[] = [
  { sev: "block", title: "Blocking" },
  { sev: "risk", title: "At risk" },
  { sev: "decide", title: "Waits for a decision" },
];

/** Cards shown per column before "Show all". */
const FIRST = 5;

function byChip(by: string, today: number): { cls: string; text: string } | null {
  const n = dayNo(by);
  if (n == null) return null;
  const x = n - today;
  if (x < 0) return { cls: "plan-by over", text: `overdue ${-x} d` };
  if (x === 0) return { cls: "plan-by over", text: "today" };
  if (x <= 14) return { cls: "plan-by soon", text: `by ${shortDay(n)} · ${x} d` };
  return { cls: "plan-by later", text: `by ${shortDay(n)}` };
}

export default function PlanBlockers({ blockers, today, onLink }: {
  blockers: PlanBlocker[];
  today: string;
  /** a link to the Parts tab: the page owns the tab */
  onLink: (link: PlanLink) => void;
}) {
  const [all, setAll] = useState<Record<string, boolean>>({});
  if (!blockers.length) return null;
  const t = dayNo(today) ?? 0;
  const cols = COLUMNS.map((c) => ({
    ...c,
    items: blockers
      .filter((b) => b.severity === c.sev)
      .sort((a, b) => (a.by || "9999").localeCompare(b.by || "9999")),
  })).filter((c) => c.items.length);
  return (
    <div className="card pad">
      <h2 className="card-title">Blockers</h2>
      <p className="muted dim">
        What stops a date, what may stop one, and what waits for a person. Each card says what it
        stops and what to do, and the date by which to do it.
      </p>
      <div className="plan-blockers">
        {cols.map((c) => {
          const shown = all[c.sev] ? c.items : c.items.slice(0, FIRST);
          return (
            <section key={c.sev} className={`plan-blk-col ${c.sev}`}>
              <h3>
                {c.title} <span className="fold-count">{c.items.length}</span>
              </h3>
              {shown.map((b, i) => {
                const chip = byChip(b.by, t);
                const link = blockerLink(b.link, b.source);
                return (
                  <article key={`${b.title}-${i}`} className={`plan-blk ${b.severity}`}>
                    <div className="plan-blk-head">
                      <span>{b.title}</span>
                      {chip ? <span className={chip.cls}>{chip.text}</span> : null}
                    </div>
                    {b.text ? <p>{b.text}</p> : null}
                    {b.stops ? (
                      <p>
                        <span className="muted">Stops:</span> {b.stops}
                      </p>
                    ) : null}
                    {b.action ? (
                      <p>
                        <span className="muted">Do:</span> {b.action}
                      </p>
                    ) : null}
                    <div className="plan-blk-foot">
                      <span className="muted">{b.source}</span>
                      {link?.kind === "href" ? (
                        <Link className="comp-link" to={link.to}>Open {link.label}</Link>
                      ) : link ? (
                        <button type="button" className="btn-link" onClick={() => onLink(link)}>
                          {link.kind === "part" ? "Open the part" : link.kind === "tab" ? `Open ${link.label}` : "Open the parts"}
                        </button>
                      ) : null}
                    </div>
                  </article>
                );
              })}
              {c.items.length > FIRST ? (
                <button type="button" className="btn btn-sm"
                  onClick={() => setAll((a) => ({ ...a, [c.sev]: !a[c.sev] }))}>
                  {all[c.sev] ? `Show the first ${FIRST}` : `Show all ${c.items.length}`}
                </button>
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}
