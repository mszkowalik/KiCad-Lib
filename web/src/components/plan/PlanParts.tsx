/** The Parts tab of a plan (decision 0107 items 14 to 18): the balance of every
 *  part the plan needs, the purchase proposals the server computed, the plan's
 *  purchase orders and its reservations.
 *
 *  A proposal is never stored: accepting it writes a draft purchase order, and
 *  the proposal leaves the list on the next read. The part list is the page's
 *  main list, so it never folds; the three below it fold above eight rows. */
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  acceptPlanProposals,
  deletePlanReservation,
  type PlanFull,
  type PlanPart,
  type PlanProposal,
  type PlanPurchase,
  type PlanReservationRow,
} from "../../api";
import { amount } from "../../format";
import DataTable from "../DataTable";
import { useDialog } from "../Dialog";
import FoldSection, { NarrowChip, StatChip } from "../FoldSection";
import { StatusPill } from "../Ui";
import { PartBalanceChart } from "./PlanCharts";
import ReserveDialog, { type ReserveDialogProps } from "./ReserveDialog";
import { fitColumns, units, useNarrow, type Apply, type PlanColumn } from "./planUtil";

const STATUS_WORD: Record<PlanPart["status"], string> = { short: "short", public: "public only", ok: "ok" };
const TIER_WORD: Record<string, string> = { lot: "machining", po_draft: "draft purchase", po_ordered: "ordered purchase" };

function partName(p: { name: string; mpn: string; lcsc: string }): string {
  return p.name || p.mpn || p.lcsc;
}

function PartCard({ part, today, onReserve, onClose }: {
  part: PlanPart;
  today: string;
  onReserve: () => void;
  onClose: () => void;
}) {
  const narrow = useNarrow();
  const needCols: PlanColumn<PlanPart["needs"][number]>[] = [
    { key: "day", label: "Day", width: "104px", narrow: "104px", get: (n) => n.day, className: "mono" },
    { key: "qty", label: "Need", width: 25, narrow: 30, numeric: true, get: (n) => n.qty, render: (n) => units(n.qty) },
    { key: "why", label: "For", width: 75, narrow: 70, get: (n) => n.why },
  ];
  const supCols: PlanColumn<PlanPart["supplies"][number]>[] = [
    { key: "day", label: "Day", width: "104px", narrow: "104px", get: (s) => s.day || "no date", className: "mono" },
    { key: "qty", label: "Supply", width: 22, narrow: 35, numeric: true, get: (s) => s.qty, render: (s) => units(s.qty) },
    { key: "tier", label: "From", width: 30, get: (s) => TIER_WORD[s.tier] ?? s.tier },
    { key: "why", label: "Which", width: 48, narrow: 65, get: (s) => s.why },
  ];
  return (
    <div className="card pad">
      <div className="fold-bar">
        <h2 className="card-title">{partName(part)}</h2>
        <StatusPill status={STATUS_WORD[part.status]} />
        {part.mpn || part.lcsc ? <span className="muted mono">{[part.mpn, part.lcsc].filter(Boolean).join(" · ")}</span> : null}
        <span className="btn-row plan-actions">
          {part.component_id ? (
            <Link className="comp-link" to={`/library/components/${part.component_id}`}>Part page</Link>
          ) : null}
          <button type="button" className="btn btn-sm" onClick={onReserve}>Reserve stock…</button>
          <button type="button" className="btn btn-sm" onClick={onClose}>Close</button>
        </span>
      </div>
      <div className="stat-row">
        <StatChip n={units(part.need)}>needed</StatChip>
        <StatChip n={units(part.on_hand)}>on hand</StatChip>
        <StatChip n={units(part.reserved)} tone={part.reserved ? "acc" : undefined}>reserved for the plan</StatChip>
        {part.reserved_broken ? <StatChip n={units(part.reserved_broken)} tone="err">reserved, gone</StatChip> : null}
        {part.other_reserved ? <StatChip n={units(part.other_reserved)}>reserved for other plans</StatChip> : null}
        {part.in_work_other ? <StatChip n={units(part.in_work_other)}>for batches in work</StatChip> : null}
        <StatChip n={units(part.free)}>free</StatChip>
        {part.incoming ? <StatChip n={units(part.incoming)}>incoming</StatChip> : null}
        {part.from_lots ? <StatChip n={units(part.from_lots)}>from machining</StatChip> : null}
        {part.jlc_public != null ? <StatChip n={units(part.jlc_public)} tone={part.status === "public" ? "warn" : undefined}>JLC public stock</StatChip> : null}
        {part.short ? <StatChip n={units(part.short)} tone="err">short from {part.first_short}</StatChip> : null}
        {part.unknown_arrivals ? <StatChip n={part.unknown_arrivals} tone="warn">arrivals with no date, not drawn</StatChip> : null}
      </div>
      <PartBalanceChart part={part} today={today} />
      <div className="plan-two">
        <div>
          <h3 className="plan-sub">Needs</h3>
          <DataTable columns={fitColumns(needCols, narrow)} rows={part.needs} rowKey={(n) => `${n.day}-${n.why}`} empty="No need." />
        </div>
        <div>
          <h3 className="plan-sub">Supplies</h3>
          <DataTable columns={fitColumns(supCols, narrow)} rows={part.supplies} rowKey={(s) => `${s.day}-${s.why}-${s.qty}`}
            empty="Nothing arrives yet." />
        </div>
      </div>
    </div>
  );
}

function ProposalsCard({ full, apply, onPart }: { full: PlanFull; apply: Apply; onPart: (key: string) => void }) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const narrow = useNarrow();
  const rows = full.schedule.proposals;
  if (!rows.length) return null;
  const open = rows.filter((p) => !p.covered_by_po_id);
  const valid = [...picked].filter((k) => open.some((p) => p.key === k));
  const late = rows.filter((p) => p.late).length;
  const noLead = rows.filter((p) => p.no_lead).length;
  const toggle = (k: string) =>
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const allOn = open.length > 0 && open.every((p) => picked.has(p.key));
  const accept = async () => {
    setBusy(true);
    const ok = await apply(`${valid.length} proposals as draft purchase orders`, () => acceptPlanProposals(full.plan.id, valid));
    setBusy(false);
    if (ok) setPicked(new Set());
  };
  const cols: PlanColumn<PlanProposal>[] = [
    {
      key: "pick", width: 5, narrow: "36px", interactive: false, sortable: true, className: "ctr",
      label: <input type="checkbox" aria-label="Pick every open proposal" checked={allOn}
        onChange={() => setPicked(allOn ? new Set() : new Set(open.map((p) => p.key)))} />,
      get: (p) => (picked.has(p.key) ? 0 : 1),
      render: (p) => p.covered_by_po_id
        ? null
        : <input type="checkbox" aria-label={`Pick ${p.name}`} checked={picked.has(p.key)}
            onClick={(e) => e.stopPropagation()} onChange={() => toggle(p.key)} />,
    },
    { key: "part", label: "Part", width: 24, narrow: 45, get: (p) => partName(p),
      render: (p) => <button type="button" className="btn-link" onClick={(e) => { e.stopPropagation(); onPart(p.part_key); }}>{partName(p)}</button> },
    { key: "supplier", label: "Supplier", width: 28, get: (p) => p.supplier || "no source with a lead time",
      title: (p) => p.lead_source || p.supplier || "No supplier link of this part has a lead time." },
    { key: "qty", label: "Qty", width: 10, numeric: true, get: (p) => p.qty, render: (p) => units(p.qty) },
    { key: "order", label: "Order", width: "104px", get: (p) => p.order_day, className: "mono" },
    { key: "arrival", label: "Arrival", width: "104px", get: (p) => p.arrival_day || "unknown", className: "mono" },
    { key: "need", label: "Needed by", width: "104px", get: (p) => p.need_day, className: "mono" },
    { key: "state", label: "State", width: 18, narrow: 55,
      get: (p) => (p.covered_by_po_id ? "in a draft" : p.no_lead ? "no lead time" : p.late ? "late" : "in time"),
      render: (p) => p.covered_by_po_id
        ? <Link className="comp-link" to={`/stock/purchase-orders/${p.covered_by_po_id}`} onClick={(e) => e.stopPropagation()}>draft #{p.covered_by_po_id}</Link>
        : p.no_lead ? <span className="pill warn">no lead time</span>
          : p.late ? <span className="pill err">late</span> : <span className="pill ok">in time</span> },
    { key: "amount", label: "PLN", width: 15, numeric: true, get: (p) => p.amount_pln ?? "",
      render: (p) => (p.amount_pln != null ? p.amount_pln.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—"),
      title: (p) => (p.unit_price_pln != null ? `${p.unit_price_pln} PLN a piece, the moving average` : "No price known") },
  ];
  return (
    <FoldSection title="Purchase proposals" count={rows.length} foldKey={`plan-${full.plan.id}-proposals`}
      chips={<>
        {late ? <StatChip n={late} tone="err">late</StatChip> : null}
        {noLead ? <StatChip n={noLead} tone="warn">no lead time</StatChip> : null}
      </>}
      actions={
        <button type="button" className="btn btn-sm btn-primary" disabled={busy || !valid.length} onClick={() => void accept()}>
          Accept {valid.length || ""} as drafts
        </button>
      }>
      <p className="muted dim">
        The plan computes these for every short part and stores none. An accepted proposal becomes a
        draft purchase order. When the proposal changes later, the draft says so and keeps its own values.
      </p>
      <DataTable columns={fitColumns(cols, narrow)} rows={rows} rowKey={(p) => p.key} />
    </FoldSection>
  );
}

function PurchasesCard({ full }: { full: PlanFull }) {
  const narrow = useNarrow();
  const rows = full.schedule.purchase_orders;
  if (!rows.length) return null;
  const stale = rows.filter((p) => p.out_of_date).length;
  const surplus = rows.filter((p) => p.surplus?.length).length;
  const cols: PlanColumn<PlanPurchase>[] = [
    { key: "id", label: "#", width: 7, narrow: 20, get: (p) => p.id, render: (p) => (
      <Link className="comp-link" to={`/stock/purchase-orders/${p.id}`} onClick={(e) => e.stopPropagation()}>#{p.id}</Link>
    ) },
    { key: "supplier", label: "Supplier", width: 16, narrow: 45, get: (p) => p.supplier },
    { key: "what", label: "Lines", width: 19, get: (p) => p.lines.map((l) => `${l.name || l.mpn || l.lcsc} × ${units(l.qty)}`).join(", ") },
    { key: "status", label: "Status", width: 11, narrow: 35, get: (p) => p.status, render: (p) => <StatusPill status={p.status} /> },
    { key: "order", label: "Order", width: "104px", get: (p) => p.order_day, className: "mono" },
    { key: "arrival", label: "Arrival", width: "104px", get: (p) => p.arrival_day, className: "mono" },
    { key: "amount", label: "Amount", width: 18, numeric: true, get: (p) => p.amount, render: (p) => amount(p.amount, p.currency) },
    { key: "note", label: "The plan says", width: 29,
      get: (p) => p.out_of_date || (p.surplus?.length ? `more than needed: ${p.surplus.map((s) => `${s.name} ${units(s.qty)}`).join(", ")}` : ""),
      render: (p) => p.out_of_date ? <span className="warn-text">{p.out_of_date}</span>
        : p.surplus?.length ? <span className="warn-text">more than needed: {p.surplus.map((s) => `${s.name} ${units(s.qty)}`).join(", ")}</span>
          : null },
  ];
  return (
    <FoldSection title="The plan's purchase orders" count={rows.length} foldKey={`plan-${full.plan.id}-pos`}
      chips={<>
        {stale ? <StatChip n={stale} tone="warn">out of date</StatChip> : null}
        {surplus ? <StatChip n={surplus} tone="warn">more than needed</StatChip> : null}
      </>}>
      <p className="muted dim">Each opens on Stock → Purchase orders, where a draft takes the new proposal or is deleted.</p>
      <DataTable columns={fitColumns(cols, narrow)} rows={rows} rowKey={(p) => p.id} />
    </FoldSection>
  );
}

function ReservationsCard({ full, apply, onReserve }: { full: PlanFull; apply: Apply; onReserve: () => void }) {
  const dialog = useDialog();
  const narrow = useNarrow();
  const rows = full.schedule.reservations;
  const name = new Map(full.schedule.parts.map((p) => [p.key, partName(p)]));
  const spent = rows.filter((r) => r.remaining < r.qty).length;
  const remove = async (r: PlanReservationRow) => {
    const what = `${units(r.qty)} × ${name.get(r.key) ?? (r.mpn || r.lcsc || r.key)}`;
    const ok = await dialog.confirm(
      `Release the reservation of ${what}? The stock stays where it is and becomes free for other demand. `
      + "History → Write batches can undo it.",
      { title: "Release reservation", confirmLabel: "Release", tone: "danger" },
    );
    if (ok) await apply(`the release of ${what}`, () => deletePlanReservation(r.id));
  };
  const cols: PlanColumn<PlanReservationRow>[] = [
    { key: "part", label: "Part", width: 24, narrow: 64, get: (r) => name.get(r.key) ?? (r.mpn || r.lcsc || r.key) },
    { key: "qty", label: "Reserved", width: 11, narrow: 24, numeric: true, get: (r) => r.qty, render: (r) => units(r.qty) },
    { key: "left", label: "Left", width: 10, numeric: true, get: (r) => r.remaining, render: (r) => units(r.remaining),
      title: () => "Reserved less what the plan's batches drew" },
    { key: "source", label: "From", width: 14, get: (r) => (r.source_line_id ? `purchase line #${r.source_line_id}` : "stock") },
    { key: "note", label: "Note", width: 22, get: (r) => r.note, className: "muted" },
    { key: "by", label: "By", width: 13, get: (r) => r.created_by },
    { key: "date", label: "On", width: "104px", get: (r) => r.created_at, className: "mono" },
    { key: "del", label: "", width: 6, narrow: 12, interactive: false, className: "ctr", get: () => "",
      render: (r) => (
        <button type="button" className="row-del" title="Release this reservation" aria-label="Release this reservation"
          onClick={() => void remove(r)}>&#x2715;</button>
      ) },
  ];
  return (
    <FoldSection title="Reservations" count={rows.length} foldKey={`plan-${full.plan.id}-reservations`}
      chips={spent ? <StatChip n={spent}>partly drawn</StatChip> : null}
      actions={<button type="button" className="btn btn-sm" onClick={onReserve}>Reserve stock…</button>}>
      <p className="muted dim">
        Stock set aside for this plan. It moves no stock and no money: other demand sees only the free rest.
      </p>
      <DataTable columns={fitColumns(cols, narrow)} rows={rows} rowKey={(r) => r.id} empty="Nothing is reserved for this plan." />
    </FoldSection>
  );
}

export default function PlanParts({ full, apply, selected, onSelect }: {
  full: PlanFull;
  apply: Apply;
  selected: string | null;
  onSelect: (key: string | null) => void;
}) {
  const [narrow, setNarrow] = useState<"" | PlanPart["status"]>("");
  const small = useNarrow();
  const [reserve, setReserve] = useState<{ part?: ReserveDialogProps["part"] } | null>(null);
  const parts = full.schedule.parts;
  const part = selected ? parts.find((p) => p.key === selected) : undefined;
  const rows = narrow ? parts.filter((p) => p.status === narrow) : parts;
  const n = (s: PlanPart["status"]) => parts.filter((p) => p.status === s).length;
  const cols: PlanColumn<PlanPart>[] = [
    { key: "name", label: "Part", width: 34, narrow: 55, get: (p) => partName(p),
      title: (p) => [partName(p), p.mpn, p.lcsc, p.prepared ? "prepared in a machining lot" : ""].filter(Boolean).join(" · ") },
    { key: "status", label: "Status", width: "132px", get: (p) => STATUS_WORD[p.status],
      sortValue: (p) => ({ short: 0, public: 1, ok: 2 })[p.status],
      render: (p) => <StatusPill status={STATUS_WORD[p.status]} /> },
    { key: "need", label: "Need", width: 9, numeric: true, get: (p) => p.need, render: (p) => units(p.need) },
    { key: "reserved", label: "Reserved", width: 10, numeric: true, get: (p) => p.reserved, render: (p) => units(p.reserved) },
    { key: "free", label: "Free", width: 9, numeric: true, get: (p) => p.free, render: (p) => units(p.free) },
    { key: "incoming", label: "Incoming", width: 10, numeric: true, get: (p) => p.incoming, render: (p) => units(p.incoming) },
    { key: "lots", label: "Machined", width: 10, numeric: true, get: (p) => p.from_lots, render: (p) => units(p.from_lots) },
    { key: "first", label: "Short from", width: "104px", narrow: "104px", get: (p) => p.first_short, className: "mono" },
    { key: "short", label: "Short", width: 18, narrow: 45, numeric: true, get: (p) => p.short,
      render: (p) => (p.short ? <span className={p.status === "short" ? "err-text" : "warn-text"}>{units(p.short)}</span> : "") },
  ];
  const reserveFor = (p?: PlanPart) =>
    // What can be reserved is the free stock, up to what the plan needs.
    setReserve({ part: p ? { component_id: p.component_id, mpn: p.mpn, lcsc: p.lcsc, name: partName(p), qty: Math.min(p.need, p.free) || undefined } : undefined });
  return (
    <>
      {part ? (
        <PartCard part={part} today={full.schedule.today} onReserve={() => reserveFor(part)} onClose={() => onSelect(null)} />
      ) : null}
      <div className="card pad">
        <h2 className="card-title">Parts the plan needs</h2>
        <p className="muted dim">
          Each part&apos;s balance over time: stock reserved for the plan and free stock, then what
          arrives, against what the batches and the builds need. Click a part for its chart.
        </p>
        <div className="stat-row">
          <NarrowChip value="short" current={narrow} onNarrow={setNarrow} n={n("short")} tone={n("short") ? "err" : undefined}>short</NarrowChip>
          <NarrowChip value="public" current={narrow} onNarrow={setNarrow} n={n("public")} tone={n("public") ? "warn" : undefined}>
            only in JLC public stock
          </NarrowChip>
          <NarrowChip value="ok" current={narrow} onNarrow={setNarrow} n={n("ok")} tone="ok">covered</NarrowChip>
        </div>
        <DataTable columns={fitColumns(cols, small)} rows={rows} rowKey={(p) => p.key} persistKey={`plan-parts-${full.plan.id}`}
          rowClass={(p) => (p.key === selected ? "row-selected" : "")}
          onRowClick={(p) => onSelect(p.key === selected ? null : p.key)}
          empty={full.schedule.designs.length ? "No part needed yet: plan a batch or a delivery." : "Add a design on Setup first."} />
      </div>
      <ProposalsCard full={full} apply={apply} onPart={(k) => onSelect(k)} />
      <PurchasesCard full={full} />
      <ReservationsCard full={full} apply={apply} onReserve={() => reserveFor()} />
      {reserve ? (
        <ReserveDialog
          planId={full.plan.id}
          part={reserve.part}
          onClose={() => setReserve(null)}
          onDone={(f) => {
            setReserve(null);
            void apply("the reservation", async () => f);
          }}
        />
      ) : null}
    </>
  );
}

