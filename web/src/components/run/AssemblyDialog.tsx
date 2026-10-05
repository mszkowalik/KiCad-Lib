/** Record the batch's Board assembly step, or add to it (decision 0072).
 *
 *  Nothing records the step by itself — not receiving the boards, not applying
 *  the JLC order. The draft (`getAssemblyDraft`) is pre-filled from the batch's
 *  records and the JLC data, every row starts ticked, and only ticked rows
 *  reach the POST. The same dialog works fully by hand for another assembly
 *  house: with no JLC order linked, "Parts from our stock" starts from the
 *  design BOM × boards, and each ticked row becomes a NEW draw at the stock
 *  average on the day.
 *
 *  - **The draft's `lines` are three kinds, shown in two places.** A
 *    `position` (a fee: `pcba:smt`, `fab:setup`) is an invoice position. A
 *    `supplied_part` is a part the assembler bought that the invoice already
 *    itemises, and a `parts_lump` is a parts total not split yet — both live
 *    under "Parts the assembler supplied", the lump as the head of its
 *    breakdown rows.
 *  - **A parts total with ticked rows is SPLIT into them.** Its own line goes
 *    in too, so the children inherit the step link; untick every row and the
 *    total can be linked whole, as one position.
 *  - **In "Add to assembly" some rows start unticked**: the BOM suggestion
 *    (the step already holds the parts drawn for it) and the breakdown of a
 *    total the step already holds whole. The draft offers them; the person
 *    decides.
 *  - **The note is ADDED to the step's note** when the step exists, so it
 *    starts empty there — pre-filling it would write the old note twice.
 *  - **Apply is enabled only for the body the last Preview saw.** Any change
 *    to a field or a tick clears the preview.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  errorMessage,
  recordAssembly,
  type AssemblyDraft,
  type AssemblyDraftDraw,
  type AssemblyDraftLine,
  type AssemblyPartsLump,
  type AssemblyReplacementRow,
  type AssemblySuppliedBy,
  type RecordAssemblyBody,
  type RecordAssemblyResult,
  type RunInfo,
} from "../../api";
import { amount, usd } from "../../format";
import AutoTextarea from "../AutoTextarea";
import ComponentPickDialog from "../ComponentPickDialog";
import DataTable, { type Column } from "../DataTable";
import Field, { CheckField, FieldGrid } from "../Field";
import { useModal } from "../modal";
import NumberInput from "../NumberInput";
import { today } from "../process/MakeDialog";
import { ErrorBanner, Spinner } from "../Ui";

/** "1 position", "3 positions". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** A row of "Parts from our stock": a measured draw already written (linked
 *  by id, quantity fixed), or a NEW draw from our stock (quantity typed). */
interface StockRow {
  key: string;
  on: boolean;
  draw: AssemblyDraftDraw | null;
  component_id: number | null;
  name: string;
  mpn: string;
  lcsc: string;
  qty: number | null;
}

/** A row of "Parts the assembler supplied": one child of a parts total. */
interface SuppliedRow {
  key: string;
  on: boolean;
  parent_line_id: number;
  lcsc: string;
  mpn: string;
  designator: string;
  qty: number | null;
  unit_price: number | null;
  /** "rounding" closes the cent the supplier rounded its billed total by. */
  source: string;
}

interface ReplRow extends AssemblyReplacementRow {
  key: string;
  on: boolean;
  by: AssemblySuppliedBy;
}

const BY_LABEL: Record<AssemblySuppliedBy, string> = {
  supplier: "assembler's parts",
  pool: "our parts",
  both: "part ours, part assembler's",
};

/** The child line's label — the same words the invoice's own "supplier" fill
 *  writes, so a split made here reads like one made there. */
function suppliedLabel(r: SuppliedRow): string {
  if (r.source === "rounding") return "Rounding in the supplier's billed parts total";
  const part = r.mpn || r.lcsc;
  return (r.designator ? `${part} - ${r.designator}` : part).slice(0, 200);
}

function partName(r: { name?: string; mpn?: string; lcsc?: string; component_id?: number | null }): string {
  return r.name || r.mpn || r.lcsc || (r.component_id ? `component ${r.component_id}` : "—");
}

/** A tick box for a table header that ticks every row of that table. */
function TickAll({ rows, set }: { rows: { on: boolean }[]; set: (on: boolean) => void }) {
  const all = rows.length > 0 && rows.every((r) => r.on);
  return (
    <input
      type="checkbox"
      checked={all}
      disabled={!rows.length}
      title={all ? "Untick every row" : "Tick every row"}
      onChange={(e) => set(e.target.checked)}
    />
  );
}

/** `TickAll` for a list of invoice positions, whose ticks are keyed by id. */
function TickLines({ lines, on, set }: {
  lines: AssemblyDraftLine[];
  on: Record<number, boolean>;
  set: (next: Record<number, boolean>) => void;
}) {
  return (
    <TickAll rows={lines.map((l) => ({ on: !!on[l.line_id] }))}
      set={(v) => set({ ...on, ...Object.fromEntries(lines.map((l) => [l.line_id, v])) })} />
  );
}

export default function AssemblyDialog({ run, draft, onClose }: {
  run: RunInfo;
  draft: AssemblyDraft;
  onClose: (changed: boolean) => void;
}) {
  const modal = useModal(() => onClose(false));
  const adding = draft.status === "recorded";
  const rec = draft.recorded;
  const h = draft.header;
  const jlc = (h.orders ?? []).length > 0;
  const inStep = useMemo(() => new Set((rec?.lines ?? []).map((l) => l.line_id)), [rec]);

  const [assembler, setAssembler] = useState((adding ? rec?.assembler : h.assembler) ?? "");
  const [reference, setReference] = useState((adding ? rec?.reference : h.reference) ?? "");
  const [madeAt, setMadeAt] = useState((adding ? rec?.made_at : h.made_at) || today());
  const [note, setNote] = useState("");

  const [lineOn, setLineOn] = useState<Record<number, boolean>>(
    () => Object.fromEntries(draft.lines.map((l) => [l.line_id, true])));
  const [stock, setStock] = useState<StockRow[]>(() => [
    ...draft.parts_from_stock.map((d) => ({
      key: `d${d.consumption_id}`, on: true, draw: d, component_id: d.component_id,
      name: d.name, mpn: d.mpn, lcsc: d.lcsc, qty: d.qty,
    })),
    ...(jlc ? [] : draft.bom_suggestion.map((b, i) => ({
      key: `b${i}`, on: !adding, draw: null, component_id: b.component_id,
      name: b.name, mpn: b.mpn, lcsc: b.lcsc, qty: b.qty,
    }))),
  ]);
  const [supplied, setSupplied] = useState<SuppliedRow[]>(() => draft.parts_supplied.map((s, i) => ({
    key: `s${i}`,
    on: !inStep.has(s.parent_line_id) && (s.qty > 0 || s.source === "rounding"),
    parent_line_id: s.parent_line_id, lcsc: s.lcsc, mpn: s.mpn, designator: s.designator,
    qty: s.qty, unit_price: s.unit_price, source: s.source ?? "",
  })));
  const [repl, setRepl] = useState<ReplRow[]>(() => draft.replacements.map((r, i) => ({
    ...r, key: `r${i}`, on: true,
    by: (r.supplied_by === "pool" || r.supplied_by === "both" ? r.supplied_by : "supplier"),
  })));
  // Keys for rows added here. A ref, not state: it is read inside event
  // handlers only, and bumping state from inside a setState updater runs twice
  // under StrictMode.
  const seq = useRef(0);

  const [picking, setPicking] = useState<
    { kind: "stock" } | { kind: "supplied"; key: string } | null>(null);
  const [plan, setPlan] = useState<RecordAssemblyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const patchStock = (key: string, next: Partial<StockRow>) =>
    setStock((rs) => rs.map((r) => (r.key === key ? { ...r, ...next } : r)));
  const patchSupplied = (key: string, next: Partial<SuppliedRow>) =>
    setSupplied((rs) => rs.map((r) => (r.key === key ? { ...r, ...next } : r)));
  const patchRepl = (key: string, next: Partial<ReplRow>) =>
    setRepl((rs) => rs.map((r) => (r.key === key ? { ...r, ...next } : r)));
  const newKey = (p: string) => `${p}${++seq.current}`;

  const kindOf = (l: AssemblyDraftLine) => l.kind ?? (l.is_parts_lump ? "parts_lump" : "position");
  const positionLines = draft.lines.filter((l) => kindOf(l) === "position");
  const suppliedLines = draft.lines.filter((l) => kindOf(l) === "supplied_part");
  const lumpLines = new Map(draft.lines.filter((l) => kindOf(l) === "parts_lump").map((l) => [l.line_id, l]));
  // A total with ticked rows is split into them, and goes in with them.
  const splitLumps = new Set(supplied.filter((r) => r.on).map((r) => r.parent_line_id));
  const lineTicked = (l: AssemblyDraftLine) => !!lineOn[l.line_id] || splitLumps.has(l.line_id);

  const body = (dry: boolean): RecordAssemblyBody => ({
    dry_run: dry,
    made_at: madeAt,
    assembler: assembler.trim(),
    reference: reference.trim(),
    note: note.trim(),
    line_ids: draft.lines.filter(lineTicked).map((l) => l.line_id),
    draw_ids: stock.filter((r) => r.on && r.draw).map((r) => (r.draw as AssemblyDraftDraw).consumption_id),
    parts: stock.filter((r) => r.on && !r.draw).map((r) => ({
      component_id: r.component_id, mpn: r.mpn, lcsc: r.lcsc, name: r.name, qty: r.qty ?? 0,
    })),
    supplied: supplied.filter((r) => r.on).map((r) => ({
      parent_line_id: r.parent_line_id, lcsc: r.lcsc, mpn: r.mpn, label: suppliedLabel(r),
      qty: r.qty ?? 0, unit_price: r.unit_price ?? 0, source: r.source ?? "",
    })),
    replacements: repl.filter((r) => r.on).map((r) => ({
      designator: r.designator, supplier_designator: r.supplier_designator,
      specified_lcsc: r.specified_lcsc, specified_mpn: r.specified_mpn,
      specified_component_id: r.specified_component_id, fitted_lcsc: r.fitted_lcsc,
      fitted_component_id: null, fitted_mpn: r.fitted_mpn, supplied_by: r.by,
      supplier_source: r.supplier_source, board: r.board, variant: r.variant,
      evidence: r.evidence, note: "",
    })),
  });
  const bodyKey = JSON.stringify(body(true));
  useEffect(() => { setPlan(null); }, [bodyKey]);

  const invalid =
    !madeAt ? "Give the date the boards were assembled."
    : stock.some((r) => r.on && !r.draw && !((r.qty ?? 0) > 0))
      ? "Give every ticked part from our stock a quantity."
    : supplied.some((r) => r.on && (!((r.qty ?? 0) > 0) || r.unit_price == null))
      ? "Give every ticked supplied row a quantity and a unit price."
    : supplied.some((r) => r.on && r.source !== "rounding" && !(r.mpn || r.lcsc))
      ? "Name the part on every ticked supplied row."
    : "";

  const go = async (dry: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const res = await recordAssembly(run.id, body(dry));
      if (dry) setPlan(res); else onClose(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const twinsJoin = adding ? (h.twins_not_in_step ?? 0) : (h.twins ?? 0);

  // ------------------------------------------------------------- tables
  const lineCols: Column<AssemblyDraftLine>[] = [
    { key: "on", width: 4, interactive: false, className: "ctr", get: (l) => (lineTicked(l) ? 1 : 0),
      label: <TickLines lines={positionLines} on={lineOn} set={setLineOn} />,
      render: (l) => (
        <input type="checkbox" checked={!!lineOn[l.line_id]}
          onChange={(e) => setLineOn({ ...lineOn, [l.line_id]: e.target.checked })} />
      ) },
    { key: "label", label: "Invoice position", width: 40, get: (l) => l.label },
    { key: "key", label: "Step key", width: 14, className: "mono", get: (l) => l.plan_key || "—" },
    { key: "doc", label: "Document", width: 24, get: (l) => [l.supplier, l.doc_number].filter(Boolean).join(" "),
      title: (l) => [l.supplier, l.doc_number, l.doc_date].filter(Boolean).join(" · ") },
    { key: "amount", label: "Amount", width: 18, numeric: true, get: (l) => l.amount,
      render: (l) => amount(l.amount, l.currency) },
  ];

  const itemisedCols: Column<AssemblyDraftLine>[] = [
    { key: "on", width: 4, interactive: false, className: "ctr", get: (l) => (lineOn[l.line_id] ? 1 : 0),
      label: <TickLines lines={suppliedLines} on={lineOn} set={setLineOn} />,
      render: (l) => (
        <input type="checkbox" checked={!!lineOn[l.line_id]}
          onChange={(e) => setLineOn({ ...lineOn, [l.line_id]: e.target.checked })} />
      ) },
    { key: "label", label: "Part", width: 50, get: (l) => l.label },
    { key: "doc", label: "Document", width: 26, get: (l) => [l.supplier, l.doc_number].filter(Boolean).join(" "),
      title: (l) => [l.supplier, l.doc_number, l.doc_date].filter(Boolean).join(" · ") },
    { key: "amount", label: "Amount", width: 20, numeric: true, get: (l) => l.amount,
      render: (l) => amount(l.amount, l.currency) },
  ];

  const stockCols: Column<StockRow>[] = [
    { key: "on", width: 4, interactive: false, className: "ctr", get: (r) => (r.on ? 1 : 0),
      label: <TickAll rows={stock} set={(on) => setStock((rs) => rs.map((r) => ({ ...r, on })))} />,
      render: (r) => (
        <input type="checkbox" checked={r.on} onChange={(e) => patchStock(r.key, { on: e.target.checked })} />
      ) },
    { key: "part", label: "Part", width: 30, get: (r) => partName(r),
      title: (r) => [r.name, r.mpn, r.lcsc].filter(Boolean).join(" · ") },
    { key: "lcsc", label: "LCSC", width: 12, className: "mono", get: (r) => r.lcsc || "—" },
    { key: "lots", label: "Lots", width: 22,
      get: (r) => (r.draw ? (r.draw.lots ?? []).map((x) => `${x.lot} × ${x.qty}`).join(", ") : "new draw"),
      render: (r) => (r.draw
        ? ((r.draw.lots ?? []).map((x) => `${x.lot} × ${x.qty}`).join(", ") || "—")
        : <span className="muted">new draw from our stock</span>) },
    { key: "qty", label: "Qty", width: 14, numeric: true, interactive: false, get: (r) => r.qty ?? 0,
      render: (r) => (r.draw ? r.qty : (
        <NumberInput className="row-input num" value={r.qty} min={0}
          onChange={(v) => patchStock(r.key, { qty: v })} onEmpty={() => patchStock(r.key, { qty: null })} />
      )) },
    { key: "value", label: "Value", width: 18, numeric: true, get: (r) => r.draw?.value_usd ?? 0,
      title: (r) => (r.draw ? undefined : "Priced at the stock average on the day. Preview shows the total."),
      render: (r) => (r.draw ? usd(r.draw.value_usd) : <span className="muted">at the average</span>) },
  ];

  const suppliedCols = (rows: SuppliedRow[], currency = "USD"): Column<SuppliedRow>[] => [
    { key: "on", width: 4, interactive: false, className: "ctr", get: (r) => (r.on ? 1 : 0),
      label: <TickAll rows={rows} set={(on) => {
        const keys = new Set(rows.map((r) => r.key));
        setSupplied((rs) => rs.map((r) => (keys.has(r.key) ? { ...r, on } : r)));
      }} />,
      render: (r) => (
        <input type="checkbox" checked={r.on} onChange={(e) => patchSupplied(r.key, { on: e.target.checked })} />
      ) },
    { key: "part", label: "Part", width: 26, interactive: false, get: (r) => r.mpn || r.lcsc,
      title: (r) => [r.mpn, r.lcsc].filter(Boolean).join(" · ") || undefined,
      render: (r) => (r.source === "rounding" ? <span className="muted">rounding</span> : (
        <button type="button" className="btn btn-sm" title="Name the part the assembler bought"
          onClick={() => setPicking({ kind: "supplied", key: r.key })}>
          {r.mpn || r.lcsc || "— part —"}
        </button>
      )) },
    { key: "lcsc", label: "LCSC", width: 12, className: "mono", interactive: false, get: (r) => r.lcsc || "—" },
    { key: "des", label: "Designator", width: 18, interactive: false, get: (r) => r.designator,
      render: (r) => (r.source === "rounding" ? "" : (
        <input className="row-input" value={r.designator}
          onChange={(e) => patchSupplied(r.key, { designator: e.target.value })} />
      )) },
    { key: "qty", label: "Qty", width: 12, numeric: true, interactive: false, get: (r) => r.qty ?? 0,
      render: (r) => (
        <NumberInput className="row-input num" value={r.qty} min={0}
          onChange={(v) => patchSupplied(r.key, { qty: v })} onEmpty={() => patchSupplied(r.key, { qty: null })} />
      ) },
    { key: "unit", label: "Unit price", width: 14, numeric: true, interactive: false, get: (r) => r.unit_price ?? 0,
      render: (r) => (
        <NumberInput className="row-input num" value={r.unit_price} step={0.0001}
          onChange={(v) => patchSupplied(r.key, { unit_price: v })}
          onEmpty={() => patchSupplied(r.key, { unit_price: null })} />
      ) },
    { key: "amount", label: "Amount", width: 14, numeric: true, interactive: false,
      get: (r) => (r.qty ?? 0) * (r.unit_price ?? 0),
      render: (r) => amount((r.qty ?? 0) * (r.unit_price ?? 0), currency) },
  ];

  const replCols: Column<ReplRow>[] = [
    { key: "on", width: 4, interactive: false, className: "ctr", get: (r) => (r.on ? 1 : 0),
      label: <TickAll rows={repl} set={(on) => setRepl((rs) => rs.map((r) => ({ ...r, on })))} />,
      render: (r) => (
        <input type="checkbox" checked={r.on} onChange={(e) => patchRepl(r.key, { on: e.target.checked })} />
      ) },
    { key: "des", label: "Designator", width: 14, className: "mono", get: (r) => r.designator },
    { key: "spec", label: "Specified part", width: 30, get: (r) => r.specified_mpn || r.specified_lcsc,
      title: (r) => [r.specified_mpn, r.specified_lcsc].filter(Boolean).join(" · ") },
    { key: "fit", label: "Fitted part", width: 30, get: (r) => r.fitted_mpn || r.fitted_lcsc,
      title: (r) => [r.fitted_mpn, r.fitted_lcsc, r.evidence].filter(Boolean).join(" · ") },
    { key: "by", label: "Supplied by", width: 22, interactive: false, get: (r) => BY_LABEL[r.by],
      render: (r) => (
        <select className="row-input" value={r.by}
          onChange={(e) => patchRepl(r.key, { by: e.target.value as AssemblySuppliedBy })}>
          {(Object.keys(BY_LABEL) as AssemblySuppliedBy[]).map((k) => (
            <option key={k} value={k}>{BY_LABEL[k]}</option>
          ))}
        </select>
      ) },
  ];

  // Supplied rows grouped by the total they split. A row naming a total the
  // draft did not list still gets a group, so nothing ticked is out of sight.
  const lumps: AssemblyPartsLump[] = [
    ...draft.parts_lumps,
    ...[...new Set([...supplied.map((r) => r.parent_line_id), ...lumpLines.keys()])]
      .filter((id) => !draft.parts_lumps.some((l) => l.line_id === id))
      .map((id) => ({ line_id: id, label: lumpLines.get(id)?.label || `Position ${id}`,
                      amount: lumpLines.get(id)?.amount ?? 0, currency: lumpLines.get(id)?.currency || "USD",
                      residual: null, reconciles: null, reason: "" })),
  ];

  const P = plan;
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">{adding ? "Add to assembly" : "Record assembly"}</h2>
        <p className="muted dim">
          {adding
            ? `Add what is not in the assembly step of ${run.label} yet. Only ticked rows go in.`
            : `Record how the boards of ${run.label} were assembled. Only ticked rows go in.`}
          {jlc ? ` Pre-filled from the JLC order ${(h.orders ?? []).join(", ")}.` : " No JLC order is linked, so fill it in by hand."}
        </p>
        {draft.closed ? (
          <p className="banner-warn">{run.label} is closed. Reopen it before you record the assembly.</p>
        ) : null}
        {error ? <ErrorBanner message={error} /> : null}

        <FieldGrid>
          <Field label="Assembler" hint={jlc ? "from the linked JLC order" : "who assembled the boards"}>
            <input className="text" value={assembler} onChange={(e) => setAssembler(e.target.value)} />
          </Field>
          <Field label="Reference" hint="order codes or invoice numbers">
            <input className="text mono" value={reference} onChange={(e) => setReference(e.target.value)} />
          </Field>
          <Field label="Date assembled">
            <input className="text" type="date" value={madeAt} onChange={(e) => setMadeAt(e.target.value)} />
          </Field>
          <Field label="Note" wide hint={adding ? "added to the step's note" : undefined}>
            <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>
        <p className="muted">{plural(twinsJoin, "twin")} join the step.</p>

        <h3 className="card-subtitle">Invoice positions</h3>
        <DataTable rows={positionLines} columns={lineCols} rowKey={(l) => l.line_id}
          empty="No board or assembly position of this batch is outside a step." />

        <h3 className="card-subtitle">Parts from our stock</h3>
        <p className="muted dim">
          {jlc
            ? "The parts JLC reports it took from our consigned stock for this batch."
            : adding
              ? "The design BOM times the boards. The step already holds parts, so these start unticked."
              : "The design BOM times the boards. Each ticked row becomes a new draw from our stock, priced at the average on the date assembled."}
        </p>
        <DataTable rows={stock} columns={stockCols} rowKey={(r) => r.key}
          empty={jlc ? "No measured draw of this batch is outside a step." : "No part from our stock yet."} />
        {!jlc ? (
          <div className="btn-row">
            <button type="button" className="btn btn-sm" onClick={() => setPicking({ kind: "stock" })}>
              Add part…
            </button>
          </div>
        ) : null}

        <h3 className="card-subtitle">Parts the assembler supplied</h3>
        <p className="muted dim">
          The assembler bills the parts it bought as one total. Ticked rows split that total, one row per part.
        </p>
        {suppliedLines.length ? (
          <>
            <p className="muted">
              <b>Itemised on the invoice</b> — {plural(suppliedLines.length, "part")},{" "}
              {usd(suppliedLines.reduce((a, l) => a + l.amount, 0))}.
            </p>
            <DataTable rows={suppliedLines} columns={itemisedCols} rowKey={(l) => l.line_id} />
          </>
        ) : null}
        {lumps.length === 0 && suppliedLines.length === 0 ? (
          <DataTable rows={[] as SuppliedRow[]} columns={suppliedCols([])} rowKey={(r) => r.key}
            empty="No part the assembler bought is charged to this batch outside a step." />
        ) : lumps.map((lump) => {
          const rows = supplied.filter((r) => r.parent_line_id === lump.line_id);
          const sum = rows.filter((r) => r.on).reduce((a, r) => a + (r.qty ?? 0) * (r.unit_price ?? 0), 0);
          const diff = Math.round((lump.amount - sum) * 10000) / 10000;
          const ticked = rows.some((r) => r.on);
          return (
            <div key={lump.line_id}>
              <p className="muted">
                <b>{lump.label || `Position ${lump.line_id}`}</b> — {amount(lump.amount, lump.currency)}
                {lump.order ? <> from <span className="mono">{lump.order}</span></> : null}.{" "}
                {inStep.has(lump.line_id) ? "The step holds this total as one position. " : null}
                {!ticked ? "No row is ticked, so the total is not split."
                  : Math.abs(diff) < 0.005 ? <>Ticked rows sum to {amount(sum, lump.currency)}. <span className="pill ok">matches</span></>
                  : diff > 0 ? <>Ticked rows sum to {amount(sum, lump.currency)}. <span className="pill warn">{amount(diff, lump.currency)} not split</span></>
                  : <>Ticked rows sum to {amount(sum, lump.currency)}. <span className="pill err">{amount(-diff, lump.currency)} over</span></>}
                {lump.reason ? <> No breakdown: {lump.reason}.</> : null}
              </p>
              {lumpLines.has(lump.line_id) ? (
                <CheckField
                  checked={lineTicked(lumpLines.get(lump.line_id) as AssemblyDraftLine)}
                  disabled={ticked}
                  title={ticked ? "The total is split into the ticked rows, and goes in with them." : undefined}
                  onChange={(v) => setLineOn({ ...lineOn, [lump.line_id]: v })}>
                  {ticked ? "Split into the ticked rows, which go in the step"
                    : "Link the total to the step as one position"}
                </CheckField>
              ) : null}
              <DataTable rows={rows} columns={suppliedCols(rows, lump.currency)} rowKey={(r) => r.key}
                empty="No breakdown. Add a row for each part the assembler bought." />
              <div className="btn-row">
                <button type="button" className="btn btn-sm" onClick={() => {
                  const key = newKey("n");
                  setSupplied((rs) => [...rs, {
                    key, on: true, parent_line_id: lump.line_id, lcsc: "", mpn: "", designator: "",
                    qty: null, unit_price: null, source: "hand",
                  }]);
                }}>Add row</button>
              </div>
            </div>
          );
        })}

        <h3 className="card-subtitle">Replacements</h3>
        <p className="muted dim">Positions the order fitted with another part than the design specifies.</p>
        <DataTable rows={repl} columns={replCols} rowKey={(r) => r.key}
          empty="No replacement found that is not recorded yet." />

        {P ? (
          <div className="banner-ok">
            Preview: the step would be {P.status === "extended" ? "extended" : "recorded"}, with{" "}
            {plural(P.units, "unit")} in all ({P.twins_added} new).{" "}
            {plural(P.lines_linked, "invoice line")} linked
            {P.value_usd.lines != null ? ` (${usd(P.value_usd.lines)})` : ""}.{" "}
            {plural(P.draws_linked, "draw")} linked ({usd(P.value_usd.draws ?? 0)}) and{" "}
            {plural(P.draws_written, "new draw")} from our stock ({usd(P.value_usd.parts ?? 0)}).{" "}
            {plural(P.supplied_children, "supplied part row")} split from the parts totals.{" "}
            {plural(P.replacements_recorded, "replacement")} recorded.
            {(P.supplied_residual ?? []).map((x) => (
              <div key={x.line_id}>
                {x.label || `Position ${x.line_id}`}: {x.residual.toFixed(2)} {x.currency} is not split into
                parts and is charged to nobody.
              </div>
            ))}
          </div>
        ) : null}
        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          {invalid ? <span className="muted">{invalid}</span> : null}
          <button type="button" className="btn" onClick={() => onClose(false)}>Cancel</button>
          <button type="button" className="btn" disabled={busy || !!invalid} onClick={() => go(true)}>Preview</button>
          <button type="button" className="btn btn-primary" disabled={busy || !plan || !!invalid}
            onClick={() => go(false)}>Apply</button>
        </div>
      </div>
      {picking?.kind === "stock" ? (
        <ComponentPickDialog
          line={{ kind: "part from our stock" }}
          title="Which part from our stock did the assembler use?"
          confirmLabel="Add"
          onPick={(componentId, mpn) => {
            const key = newKey("p");
            setStock((rs) => [...rs, {
              key, on: true, draw: null, component_id: componentId, name: mpn, mpn, lcsc: "", qty: null,
            }]);
          }}
          onClose={() => setPicking(null)}
        />
      ) : null}
      {picking?.kind === "supplied" ? (
        <ComponentPickDialog
          // The current name goes in as the LABEL, not the MPN: the picker
          // seeds its search from either, but returns a library part's MPN
          // only when the subject had none — so an MPN here could never be
          // replaced by picking.
          line={{ kind: "part the assembler bought",
                  label: (() => {
                    const r = supplied.find((x) => x.key === picking.key);
                    return r ? r.mpn || r.lcsc || null : null;
                  })() }}
          allowFreeText
          title="Which part did the assembler buy?"
          confirmLabel="Use this part"
          onPick={(_componentId, mpn) => {
            const typed = mpn.trim();
            patchSupplied(picking.key, /^C\d+$/i.test(typed) ? { lcsc: typed.toUpperCase() } : { mpn: typed });
          }}
          onClose={() => setPicking(null)}
        />
      ) : null}
    </div>
  );
}
