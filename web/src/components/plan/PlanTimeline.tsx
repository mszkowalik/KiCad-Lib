/** The plan's timeline (decision 0107): one row for each order, purchase,
 *  batch, machining lot and milestone, drawn from the computed schedule.
 *
 *  Every mark sits on the day the server computed, so the chart never
 *  disagrees with the blockers. A mark shows its words on pointer-enter in the
 *  shared `.si-tip` bubble, placed with `position: fixed` like `InfoTip`. The
 *  chart scrolls sideways inside its own frame and the label column stays put;
 *  the page itself never scrolls sideways.
 *
 *  A draft order's date is moved on its order dialog, which a click on the
 *  order's label opens: editing the date IS the move. */
import { useMemo, useState, type CSSProperties, type MouseEvent, type ReactNode } from "react";

import type { PlanFull, PlanNode } from "../../api";
import {
  colorStyle,
  dayNo,
  kilo,
  longDay,
  monthLabel,
  monthStarts,
  refWords,
  units,
  weekdayDay,
  type ProjectInfo,
} from "./planUtil";

interface Row {
  key: string;
  label: string;
  sub: string;
  flag?: "err" | "warn";
  marks: ReactNode[];
  color?: string;
  onLabel?: () => void;
  labelTitle?: string;
}

interface Group {
  id: string;
  title: string;
  rows: Row[];
}

interface Tip {
  text: string;
  style: CSSProperties;
}

/** Pixels per day before the chart is wider than its frame. */
const PX_PER_DAY = 4;

function placeTip(el: HTMLElement): CSSProperties {
  const r = el.getBoundingClientRect();
  const W = 300;
  const left = Math.min(Math.max(8, r.left + r.width / 2 - 40), window.innerWidth - W - 8);
  const below = window.innerHeight - r.bottom;
  return below > 160 ? { left, top: r.bottom + 6 } : { left, bottom: window.innerHeight - r.top + 6 };
}

/** The days a lag spans, for drawing only: a working day counts as 7/5 of a
 *  day and a month as 30. The server's dates stay the truth. */
function lagDays(n: PlanNode | undefined): number {
  if (!n) return 0;
  const lag = n.lag || 0;
  if (n.lag_unit === "weeks") return lag * 7;
  if (n.lag_unit === "workdays") return Math.round((lag * 7) / 5);
  if (n.lag_unit === "months") return lag * 30;
  return lag;
}

export default function PlanTimeline({ full, projects, onOrder }: {
  full: PlanFull;
  projects: ProjectInfo[];
  /** a click on an order's label: open its dialog */
  onOrder?: (orderId: number) => void;
}) {
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const [tip, setTip] = useState<Tip | null>(null);
  const s = full.schedule;
  const today = dayNo(s.today) ?? 0;

  const model = useMemo(() => {
    const colorOf = new Map(projects.map((p) => [p.id, p.color]));
    const nodes = new Map(full.nodes.map((n) => [n.id, n]));
    const partByKey = new Map(s.parts.map((p) => [p.key, p]));
    const days: number[] = [today];
    const add = (...xs: (string | null | undefined)[]) => {
      for (const x of xs) {
        const n = dayNo(x);
        if (n != null) days.push(n);
      }
    };
    for (const o of s.orders) {
      add(o.order_date, o.advance_due, o.advance_effective, o.final_due, o.earliest_delivery);
      for (const li of o.lines) for (const d of li.deliveries) add(d.day, d.planned);
    }
    for (const b of s.batches) add(b.order_day, b.arrival_day);
    for (const po of s.purchase_orders) add(po.order_day, po.arrival_day);
    for (const pr of s.proposals) add(pr.order_day, pr.arrival_day, pr.need_day);
    for (const l of s.lots) add(l.start_day, l.end_day);
    for (const m of s.milestones) add(m.day, m.end_day, m.planned);
    const r0 = Math.min(...days) - 4;
    const r1 = Math.max(Math.max(...days) + 8, r0 + 60);
    const P = (n: number) => Math.max(0, Math.min(100, ((n - r0) / (r1 - r0)) * 100));

    const tipProps = (text: string) => ({
      "aria-label": text,
      onMouseEnter: (e: MouseEvent<HTMLElement>) => setTip({ text, style: placeTip(e.currentTarget) }),
      onMouseLeave: () => setTip(null),
    });
    const pt = (key: string, iso: string | null | undefined, cls: string, text: string, label?: ReactNode,
      color?: string): ReactNode => {
      const n = dayNo(iso);
      if (n == null) return null;
      return (
        <span key={key} className={`plan-mk ${cls}`} style={{ left: `${P(n)}%`, ...(color ? colorStyle(color) : {}) }}
          {...tipProps(text)}>
          {label}
        </span>
      );
    };
    const bar = (key: string, a: number | null, b: number | null, cls: string, text: string, label?: ReactNode,
      color?: string): ReactNode => {
      if (a == null || b == null) return null;
      const lo = Math.min(a, b);
      const hi = Math.max(a, b);
      return (
        <span key={key} className={`plan-mk ${cls}`}
          style={{ left: `${P(lo)}%`, width: `${Math.max(P(hi) - P(lo), 0.4)}%`, ...(color ? colorStyle(color) : {}) }}
          {...tipProps(text)}>
          {label}
        </span>
      );
    };

    const groups: Group[] = [];
    // --- customer orders, one group per project
    const shortDays = new Map<number, Set<string>>();
    for (const c of s.coverage) shortDays.set(c.project_id, new Set(c.short.map((x) => x.delivery)));
    for (const p of projects) {
      const orders = s.orders.filter((o) => (o.lines[0]?.project_id ?? -1) === p.id);
      if (!orders.length) continue;
      groups.push({
        id: `orders-${p.id}`,
        title: `Customer orders · ${p.name}`,
        rows: orders.map((o) => {
          const color = colorOf.get(p.id);
          const qty = o.lines.reduce((a, li) => a + (li.qty || 0), 0);
          const past = o.flags.some((f) => f.code === "order_past");
          const badOrder = o.flags.some((f) => f.code === "one_month" || f.code === "two_month");
          const marks: ReactNode[] = [];
          marks.push(bar("span", dayNo(o.order_date), dayNo(o.final_due) ?? dayNo(o.last_delivery), "span",
            `${o.key}: from the order to the final payment`));
          marks.push(pt("earliest", o.earliest_delivery, "tick",
            `Earliest delivery for ${o.key}: the advance due date plus ${full.plan.min_lead_months} months, ${weekdayDay(dayNo(o.earliest_delivery))}`));
          marks.push(pt("order", o.order_date, `dot${o.draft ? "" : " filled"}${past ? " late" : ""}`,
            `${o.key} ${o.draft ? "is planned for" : "was placed on"} ${weekdayDay(dayNo(o.order_date))}${o.draft ? " (draft)" : ""}.`
            + ` Advance invoice ${o.advance_gross.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${full.plan.currency} gross.`
            + (past ? " The date has passed and the customer has not ordered." : ""), undefined, color));
          const adv = o.advance_paid_on || o.advance_effective || o.advance_due;
          marks.push(pt("advance", adv,
            `dia${o.advance_state === "late" ? " late" : ""}${o.advance_state === "paid" ? " done" : ""}`,
            o.advance_state === "paid"
              ? `The ${o.key} advance was paid on ${weekdayDay(dayNo(o.advance_paid_on))}.`
              : `The customer pays the ${o.key} advance by ${weekdayDay(dayNo(o.advance_due))}`
                + (o.advance_state === "late" ? ". It is late, so the plan counts it from today." : "."),
          ));
          for (const li of o.lines)
            for (const d of li.deliveries) {
              const short = shortDays.get(li.project_id)?.has(d.day) ?? false;
              const bad = !!d.conflict || short || badOrder;
              const why = [d.conflict, short ? "The boards do not cover it." : "",
                d.late_days ? `${d.late_days} days late, counted from today.` : "",
                ...o.flags.filter((f) => f.code === "one_month" || f.code === "two_month").map((f) => f.text)]
                .filter(Boolean).join(" ");
              marks.push(pt(`del-${d.id}`, d.day, `del${bad ? " bad" : ""}`,
                `Deliver ${units(d.qty)} of ${o.key} on ${weekdayDay(dayNo(d.day))}`
                + (d.mode === "fixed" ? " (a fixed date)." : ".") + (why ? ` ${why}` : ""),
                units(d.qty), color));
            }
          marks.push(pt("final", o.final_due, "fin",
            `The customer pays the ${o.key} final invoice by ${weekdayDay(dayNo(o.final_due))}: `
            + `${o.final_gross.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${full.plan.currency} gross.`));
          return {
            key: `o-${o.id}`,
            label: o.key,
            sub: `${units(qty)} · ${kilo(o.net)} ${full.plan.currency}${o.draft ? "" : " · confirmed"}`,
            flag: o.flags.length ? "err" : undefined,
            marks,
            onLabel: onOrder ? () => onOrder(o.id) : undefined,
            labelTitle: o.flags.length ? o.flags.map((f) => f.text).join(" ") : "Open the order's dates",
          } as Row;
        }),
      });
    }

    // --- purchases: the plan's purchase orders, then the proposals no draft covers
    const purchaseRows: Row[] = [];
    for (const po of s.purchase_orders) {
      const ln = po.lines[0];
      const part = ln?.key ? partByKey.get(ln.key) : undefined;
      const need = part?.first_need || "";
      const a = dayNo(po.order_day);
      const b = dayNo(po.arrival_day);
      const late = b != null && dayNo(need) != null && b > (dayNo(need) as number);
      const names = po.lines.slice(0, 3).map((x) => x.name || x.mpn || x.lcsc).join(", ");
      const marks: ReactNode[] = [];
      if (a != null && b != null)
        marks.push(bar("lead", a, b, "bar soft", `${po.supplier}: order ${longDay(a)}, arrival ${longDay(b)}`, `${b - a} d`));
      else if (a != null && dayNo(need) != null)
        marks.push(bar("lead", a, dayNo(need), "unk", `${po.supplier}: the arrival is not known. Needed by ${longDay(dayNo(need))}.`));
      if (need)
        marks.push(pt("need", need, `need${late ? " late" : ""}`,
          `Needed by ${weekdayDay(dayNo(need))}` + (late ? ". It arrives later." : "")));
      marks.push(pt("order", po.order_day, `dot${po.status === "draft" ? "" : " filled"}${po.order_late_days ? " late" : ""}`,
        `Order from ${po.supplier} on ${weekdayDay(a)}: ${names}. Status ${po.status}.`
        + (po.order_late_days ? ` ${po.order_late_days} days late.` : "")));
      purchaseRows.push({
        key: `po-${po.id}`,
        label: names || `#${po.id}`,
        sub: `${po.supplier} · ${po.status}${po.amount_pln ? ` · ${kilo(po.amount_pln)} PLN` : ""}`,
        flag: late || po.order_late_days || po.arrival_late_days ? "err" : po.out_of_date ? "warn" : undefined,
        marks,
      });
    }
    for (const pr of s.proposals) {
      if (pr.covered_by_po_id) continue;
      const a = dayNo(pr.order_day);
      const b = dayNo(pr.arrival_day);
      const marks: ReactNode[] = [];
      if (a != null && b != null)
        marks.push(bar("lead", a, b, "bar prop", `Proposed: order ${longDay(a)}, arrival ${longDay(b)} (${pr.lead_days} days`
          + `${pr.lead_source ? `, ${pr.lead_source}` : ""})`, `${pr.lead_days} d`));
      else if (a != null)
        marks.push(bar("lead", a, dayNo(pr.need_day), "unk", `No source with a lead time. Needed by ${longDay(dayNo(pr.need_day))}.`));
      marks.push(pt("need", pr.need_day, `need${pr.late ? " late" : ""}`,
        `Needed by ${weekdayDay(dayNo(pr.need_day))}` + (pr.late ? ". The proposal arrives later." : "")));
      marks.push(pt("order", pr.order_day, "dot", `Proposed order of ${units(pr.qty)} × ${pr.name}`
        + (pr.supplier ? ` from ${pr.supplier}` : "") + ` on ${weekdayDay(a)}. Accept it on the Parts tab.`));
      purchaseRows.push({
        key: `pr-${pr.key}`,
        label: `${pr.name} × ${units(pr.qty)}`,
        sub: `proposed · ${pr.supplier || "no source with a lead time"}`,
        flag: pr.late ? "err" : pr.no_lead ? "warn" : undefined,
        marks,
      });
    }
    if (purchaseRows.length) groups.push({ id: "purchases", title: "Purchases", rows: purchaseRows });

    // --- PCBA batches
    if (s.batches.length)
      groups.push({
        id: "batches",
        title: "PCBA batches",
        rows: s.batches.map((b) => {
          const color = colorOf.get(b.project_id);
          const a = dayNo(b.order_day);
          const z = dayNo(b.arrival_day);
          const arr = b.arrival_node_id ? nodes.get(b.arrival_node_id) : undefined;
          const start = z != null ? Math.max(a ?? z, z - lagDays(arr)) : null;
          const marks: ReactNode[] = [];
          if (a != null && start != null && start > a) {
            const waits = refWords(full, (arr?.after ?? []).filter((r) => r !== `n:${b.order_node_id}`));
            marks.push(bar("wait", a, start, "wait", `Ordered ${longDay(a)}. It waits`
              + (waits ? ` for ${waits}` : "") + ` until ${longDay(start)}.`, "waits"));
          }
          marks.push(bar("make", start ?? a, z, `bar${b.planned ? "" : " filled"}`,
            `${b.label}: ${units(b.qty)} boards, ${longDay(start ?? a)} to ${longDay(z)}`
            + (b.closures.length ? `. In production over ${b.closures.join(", ")}.` : "")
            + (b.conflict ? `. ${b.conflict}` : ""), units(b.qty), color));
          return {
            key: `b-${b.id}`,
            label: b.label,
            sub: `${b.project} · ${b.planned ? "planned" : b.status}${b.cost ? ` · ${kilo(b.cost)} ${b.cost_currency}` : ""}`,
            flag: b.conflict || b.closures.length ? "err" : b.order_late_days ? "warn" : undefined,
            marks,
          } as Row;
        }),
      });

    // --- machining lots
    if (s.lots.length)
      groups.push({
        id: "lots",
        title: "Machining lots",
        rows: s.lots.map((l) => ({
          key: `l-${l.id}`,
          label: l.label,
          sub: `${units(l.qty)}${l.rate_per_day ? ` · ${l.rate_per_day} a working day` : ""}`,
          flag: l.unknown_recipe ? "err" : l.late_days ? "warn" : undefined,
          marks: [bar("lot", dayNo(l.start_day), dayNo(l.end_day) ?? dayNo(l.start_day), "lot",
            `${l.label}: ${units(l.qty)}, ${longDay(dayNo(l.start_day))} to ${longDay(dayNo(l.end_day))}`
            + (l.workdays ? ` (${l.workdays} working days)` : "")
            + (l.unknown_recipe ? ". The recipe is not in the project's current process." : ""), units(l.qty))],
        })),
      });

    // --- milestones and closures
    if (s.milestones.length)
      groups.push({
        id: "milestones",
        title: "Milestones and closures",
        rows: s.milestones.map((m) => {
          const d = dayNo(m.day);
          const marks: ReactNode[] = [];
          if (m.kind === "closure") {
            marks.push(bar("closure", d, dayNo(m.end_day) ?? d, "closure",
              `${m.label}: closed ${longDay(d)} to ${longDay(dayNo(m.end_day) ?? d)}`, m.label));
          } else {
            const planned = dayNo(m.planned);
            if (planned != null && d != null && planned !== d) {
              marks.push(bar("moved", planned, d, "span", `Moved from ${longDay(planned)} to ${longDay(d)}`));
              marks.push(pt("ghost", m.planned, "ghost", `In the plan: ${weekdayDay(planned)}`));
            }
            if (m.end_day && d != null)
              marks.push(bar("dur", d, dayNo(m.end_day), "bar soft", `${m.label}: ${longDay(d)} to ${longDay(dayNo(m.end_day))}`));
            marks.push(pt("ms", m.day, `ms${m.late_days || m.conflict ? " late" : ""}${m.done ? " done" : ""}`,
              `${m.label}: ${weekdayDay(d)}${m.done ? " (done)" : ""}`
              + (m.late_days ? `. ${m.late_days} days late, counted from today.` : "")
              + (m.conflict ? `. ${m.conflict}` : "")
              + (m.source_text ? ` Source: ${m.source_text}.` : "")));
          }
          return {
            key: `m-${m.id}`,
            label: m.label,
            sub: m.kind === "closure" ? "closure" : `${m.party}${m.source ? ` · ${m.source}` : ""}`,
            flag: m.conflict || (m.kind === "milestone" && m.late_days) ? "err" : undefined,
            marks,
          } as Row;
        }),
      });

    // --- the frame: months, today, closures
    const months = monthStarts(r0, r1);
    const lines: { n: number; cls: string; label?: string }[] = months.map((n) => ({ n, cls: "plan-g-vl" }));
    lines.push({ n: today, cls: "plan-g-vl today", label: "Today" });
    for (const m of s.milestones)
      if (m.kind === "closure") {
        const d = dayNo(m.day);
        if (d != null) lines.push({ n: d, cls: "plan-g-vl closure", label: m.label });
      }
    return { groups, months, lines, P, minWidth: Math.round(200 + (r1 - r0) * PX_PER_DAY) };
  }, [full, projects, onOrder, s, today]);

  if (!model.groups.length) return null;
  const toggle = (id: string) =>
    setClosed((c) => {
      const next = new Set(c);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="card pad">
      <h2 className="card-title">Timeline</h2>
      <p className="muted dim">
        One row for each order, purchase, batch, lot and milestone. A red mark is a problem. Point at
        a mark for its details, click a group to fold it, and click an order to move its date.
      </p>
      <div className="plan-gantt">
        <div className="plan-g" style={{ minWidth: model.minWidth }}>
          <div className="plan-g-head">
            <div className="plan-g-label">Row</div>
            <div className="plan-g-track">
              {model.months.map((n, i) => (
                <span key={n} className="plan-g-month" style={{ left: `${model.P(n)}%` }}>
                  {monthLabel(n, i === 0 || new Date(n * 864e5).getUTCMonth() === 0)}
                </span>
              ))}
              {model.lines.filter((l) => l.label).map((l) => (
                <span key={`${l.n}-${l.label}`} className={`plan-g-flag ${l.cls.includes("today") ? "today" : "closure"}`}
                  style={{ left: `${model.P(l.n)}%` }}>
                  {l.label}
                </span>
              ))}
            </div>
          </div>
          {model.groups.map((g) => {
            const isClosed = closed.has(g.id);
            return (
              <div key={g.id}>
                <button type="button" className="plan-g-group" aria-expanded={!isClosed} onClick={() => toggle(g.id)}>
                  <span className="fold-caret" aria-hidden="true">{isClosed ? "▸" : "▾"}</span>
                  {g.title}
                  <span className="fold-count">{g.rows.length}</span>
                </button>
                {isClosed ? null : g.rows.map((r) => (
                  <div key={r.key} className={`plan-g-row${r.flag ? ` ${r.flag}` : ""}`}>
                    <div className="plan-g-label" title={r.labelTitle ?? `${r.label} · ${r.sub}`}>
                      {r.flag ? <span className="plan-g-flagdot" aria-label={r.flag === "err" ? "problem" : "warning"}>!</span> : null}
                      {r.onLabel ? (
                        <button type="button" className="btn-link plan-g-key" onClick={r.onLabel}>{r.label}</button>
                      ) : (
                        <span className="plan-g-key">{r.label}</span>
                      )}
                      <span className="plan-g-sub">{r.sub}</span>
                    </div>
                    <div className="plan-g-track">{r.marks}</div>
                  </div>
                ))}
              </div>
            );
          })}
          <div className="plan-g-lines" aria-hidden="true">
            {model.lines.map((l) => (
              <span key={`${l.cls}-${l.n}`} className={l.cls} style={{ left: `${model.P(l.n)}%` }} />
            ))}
          </div>
        </div>
      </div>
      <div className="plan-legend">
        <span><span className="plan-lg"><span className="plan-mk dot" /></span>Order (hollow: draft)</span>
        <span><span className="plan-lg"><span className="plan-mk dia" /></span>Advance due</span>
        <span><span className="plan-lg"><span className="plan-mk tick" /></span>Earliest delivery</span>
        <span><span className="plan-lg wide"><span className="plan-mk del">300</span></span>Delivery, units</span>
        <span><span className="plan-lg"><span className="plan-mk fin" /></span>Final invoice due</span>
        <span><span className="plan-lg wide"><span className="plan-mk wait" /></span>Waits</span>
        <span><span className="plan-lg"><span className="plan-mk need" /></span>Needed by</span>
        <span><span className="plan-lg wide"><span className="plan-mk unk" /></span>Lead time unknown</span>
        <span><span className="plan-lg"><span className="plan-mk ms" /></span>Milestone</span>
        <span><span className="plan-lg"><span className="plan-mk ghost" /></span>Planned date, before the move</span>
      </div>
      {tip ? <span className="si-tip on plan-tip" style={tip.style}>{tip.text}</span> : null}
    </div>
  );
}
