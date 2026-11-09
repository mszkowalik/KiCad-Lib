/** Small helpers the plan screens share (decision 0107): plain-date arithmetic,
 *  the colour of a project, the names of the dates a node may follow, and where
 *  a blocker's link leads.
 *
 *  A plan date is a plain `YYYY-MM-DD` with no time and no zone, so it is
 *  counted in whole UTC days and never converted to local time. */
import { useEffect, useState, type CSSProperties } from "react";

import type { Column } from "../DataTable";
import type { PlanFull, PlanNode, PlanSchedule } from "../../api";

const DAY_MS = 864e5;
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** Monday first, as the API counts them (0 = Monday). */
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** Days since 1970-01-01, or null for an empty or bad date. */
export function dayNo(iso: string | null | undefined): number | null {
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null;
  const n = Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10))) / DAY_MS;
  return Number.isFinite(n) ? Math.round(n) : null;
}

export function isoOf(n: number): string {
  return new Date(n * DAY_MS).toISOString().slice(0, 10);
}

/** 0 = Monday. */
export function weekdayOf(n: number): number {
  return (((n + 3) % 7) + 7) % 7;
}

/** The Monday of the week the day falls in. */
export function weekStart(n: number): number {
  return n - weekdayOf(n);
}

/** "5 Feb". */
export function shortDay(n: number | null): string {
  if (n == null) return "—";
  const d = new Date(n * DAY_MS);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

/** "5 Feb 2027". */
export function longDay(n: number | null): string {
  if (n == null) return "—";
  return `${shortDay(n)} ${new Date(n * DAY_MS).getUTCFullYear()}`;
}

/** "Thu 5 Feb". */
export function weekdayDay(n: number | null): string {
  if (n == null) return "—";
  return `${WEEKDAYS[weekdayOf(n)]} ${shortDay(n)}`;
}

/** The first day of each month between two days, inclusive. */
export function monthStarts(from: number, to: number): number[] {
  const out: number[] = [];
  const d = new Date(from * DAY_MS);
  let y = d.getUTCFullYear();
  let m = d.getUTCMonth();
  for (;;) {
    const n = Date.UTC(y, m, 1) / DAY_MS;
    if (n > to) break;
    if (n >= from) out.push(n);
    m += 1;
    if (m > 11) {
      m = 0;
      y += 1;
    }
  }
  return out;
}

export function monthLabel(n: number, withYear: boolean): string {
  const d = new Date(n * DAY_MS);
  return withYear ? `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}` : MONTHS[d.getUTCMonth()];
}

/** "2026-12" as "Dec 2026". */
export function monthName(ym: string): string {
  const m = Number(ym.slice(5, 7));
  return m >= 1 && m <= 12 ? `${MONTHS[m - 1]} ${ym.slice(0, 4)}` : ym;
}

/** "1,234". */
export const units = (v: number | null | undefined): string =>
  v == null ? "—" : Math.round(v).toLocaleString();

/** "135k", "1.25M": an axis label, never a figure somebody adds up. */
export function kilo(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${Math.round(v / 1e3)}k`;
  return String(Math.round(v));
}

// ------------------------------------------------------------------ projects

/** One colour per project, from theme tokens that exist in both themes. The
 *  plan's own designs come first, so the first project is always the accent. */
const PROJECT_COLORS = ["var(--accent)", "var(--copper)", "var(--sim-trace-4)", "var(--sim-trace-5)", "var(--ok)"];

export interface ProjectInfo {
  id: number;
  name: string;
  color: string;
}

export function planProjects(full: PlanFull): ProjectInfo[] {
  const seen = new Map<number, string>();
  for (const p of full.plan.projects) seen.set(p.project_id, p.project);
  for (const o of full.schedule.orders)
    for (const li of o.lines) if (!seen.has(li.project_id)) seen.set(li.project_id, li.project);
  for (const b of full.schedule.batches) if (!seen.has(b.project_id)) seen.set(b.project_id, b.project);
  return [...seen.entries()].map(([id, name], i) => ({
    id,
    name: name || `project ${id}`,
    color: PROJECT_COLORS[i % PROJECT_COLORS.length],
  }));
}

/** The style that hands a project's colour to its marks (`--pc`). A computed
 *  value, so it is the one inline style these screens use. */
export function colorStyle(color: string): CSSProperties {
  return { ["--pc" as string]: color } as CSSProperties;
}

// ------------------------------------------------------------------ references

export interface RefOption {
  ref: string;
  label: string;
  day: string;
}

/** The computed day of every node the schedule draws. A node the schedule does
 *  not draw keeps its stored day. */
export function nodeDays(s: PlanSchedule): Map<number, string> {
  const m = new Map<number, string>();
  for (const o of s.orders)
    for (const li of o.lines) for (const d of li.deliveries) if (d.node_id) m.set(d.node_id, d.day);
  for (const b of s.batches) {
    if (b.order_node_id) m.set(b.order_node_id, b.order_day);
    if (b.arrival_node_id) m.set(b.arrival_node_id, b.arrival_day);
  }
  for (const po of s.purchase_orders) {
    if (po.order_node_id) m.set(po.order_node_id, po.order_day);
    if (po.arrival_node_id) m.set(po.arrival_node_id, po.arrival_day);
  }
  for (const l of s.lots) if (l.start_node_id) m.set(l.start_node_id, l.start_day);
  for (const ms of s.milestones) m.set(ms.id, ms.day);
  return m;
}

/** What a node may follow: the plan's other dates, and each order's date and
 *  advance. `ownId` is left out, because a node cannot follow itself. */
export function refOptions(full: PlanFull, ownId?: number | null): RefOption[] {
  const days = nodeDays(full.schedule);
  const out: RefOption[] = [];
  for (const o of full.schedule.orders) {
    out.push({ ref: `order:${o.id}`, label: `${o.key}: order date`, day: o.order_date });
    out.push({ ref: `advance:${o.id}`, label: `${o.key}: advance`, day: o.advance_effective || o.advance_due });
  }
  for (const n of full.nodes) {
    if (n.id === ownId) continue;
    out.push({ ref: `n:${n.id}`, label: nodeLabel(n), day: days.get(n.id) ?? n.day });
  }
  return out;
}

const KIND_WORD: Record<PlanNode["kind"], string> = {
  delivery: "delivery",
  batch_order: "batch order",
  batch_arrival: "batch arrival",
  po_order: "purchase order",
  po_arrival: "purchase arrival",
  lot: "machining lot",
  milestone: "milestone",
  closure: "closure",
};

export function nodeLabel(n: PlanNode): string {
  return n.label || `${KIND_WORD[n.kind]} ${n.id}`;
}

/** The words for a list of references, for a line of text. */
export function refWords(full: PlanFull, refs: string[] | null | undefined): string {
  if (!refs?.length) return "";
  const opts = new Map(refOptions(full).map((o) => [o.ref, o.label]));
  return refs.map((r) => opts.get(r) ?? r).join(", ");
}

// ------------------------------------------------------------------ links

/** Where a link of the schedule leads. `part:<key>` and `parts` open the Parts
 *  tab, `po:<id>` the purchase order, `order:<id>` the order, `run:<id>` the
 *  batch. */
export type PlanLink =
  | { kind: "part"; key: string }
  | { kind: "parts" }
  | { kind: "tab"; tab: "setup" | "money"; label: string }
  | { kind: "href"; to: string; label: string }
  | null;

/** Where a blocker with no link of its own is fixed, from the word the engine
 *  puts in its `source`. A problem leads somewhere, so every source the engine
 *  writes has a place here. */
const SOURCE_PLACE: Record<string, PlanLink> = {
  "the plan's draft orders": { kind: "tab", tab: "setup", label: "the orders" },
  orders: { kind: "tab", tab: "setup", label: "the orders" },
  "plan parameters": { kind: "tab", tab: "setup", label: "the contract" },
  plan: { kind: "tab", tab: "setup", label: "the contract" },
  "plan projects": { kind: "tab", tab: "setup", label: "the designs" },
  designs: { kind: "tab", tab: "setup", label: "the designs" },
  batches: { kind: "tab", tab: "setup", label: "the batches" },
  milestones: { kind: "tab", tab: "setup", label: "the milestones" },
  closures: { kind: "tab", tab: "setup", label: "the closures" },
  nodes: { kind: "tab", tab: "setup", label: "the dates" },
  "the node": { kind: "tab", tab: "setup", label: "the dates" },
  "customer parts": { kind: "tab", tab: "setup", label: "the customer parts" },
  cash: { kind: "tab", tab: "money", label: "the cash" },
  parts: { kind: "parts" },
  suppliers: { kind: "parts" },
  proposals: { kind: "parts" },
  reservations: { kind: "parts" },
  "purchase orders": { kind: "parts" },
  "sales invoices": { kind: "href", to: "/sales/invoices", label: "the sales invoices" },
};

/** The link of a blocker: its own, else the place of its source. */
export function blockerLink(link: string | null | undefined, source: string): PlanLink {
  return parseLink(link) ?? SOURCE_PLACE[source] ?? null;
}

export function parseLink(link: string | null | undefined): PlanLink {
  if (!link) return null;
  if (link === "parts") return { kind: "parts" };
  const [kind, id] = [link.slice(0, link.indexOf(":")), link.slice(link.indexOf(":") + 1)];
  if (!id) return null;
  if (kind === "part") return { kind: "part", key: id };
  if (kind === "po") return { kind: "href", to: `/stock/purchase-orders/${id}`, label: `purchase order #${id}` };
  if (kind === "order") return { kind: "href", to: `/sales/orders/${id}`, label: "the order" };
  if (kind === "run") return { kind: "href", to: `/production/batches/${id}`, label: "the batch" };
  return null;
}

/** A write of the plan page: it runs `work`, puts the answer on screen and says
 *  how to undo it, or shows the refusal. True when it worked, so a dialog
 *  closes only then. */
export type Apply = (what: string, work: () => Promise<PlanFull>) => Promise<boolean>;

/** Thrown by a write the person chose not to finish (a warning they declined):
 *  `Apply` drops it without a message. */
export class Declined extends Error {}

// ------------------------------------------------------------------ narrow screens

const NARROW = "(max-width: 700px)";

/** True on a phone-width window. A plan table then shows its key columns
 *  only, because nine columns in 320 px cut every one of them. */
export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia(NARROW).matches);
  useEffect(() => {
    const mq = window.matchMedia(NARROW);
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow;
}

/** A column with its width on a narrow screen. Without `narrow` the column
 *  is left out there. */
export type PlanColumn<T> = Column<T> & { narrow?: number | string };

export function fitColumns<T>(cols: PlanColumn<T>[], narrow: boolean): Column<T>[] {
  const pick = narrow ? cols.filter((c) => c.narrow != null) : cols;
  return pick.map(({ narrow: w, ...c }) => (narrow ? { ...c, width: w as number | string } : c));
}
