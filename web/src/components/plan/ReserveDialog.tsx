import { useState } from "react";
import {
  addPlanReservations,
  errorMessage,
  getReservableLines,
  listPlans,
  type PlanFull,
  type PlanReservationIn,
  type ReservableLines,
} from "../../api";
import ComponentPickDialog from "../ComponentPickDialog";
import DataTable, { type Column } from "../DataTable";
import Field, { FieldGrid } from "../Field";
import { useModal } from "../modal";
import { ErrorBanner, Spinner } from "../Ui";
import { useLoad } from "../useLoad";
import { plain, plural } from "../../format";

/** Reserve stock for a plan (decision 0107 item 18), from the part positions of
 *  one purchase document (`documentId`, e.g. a JLC parts order) or by part.
 *  With no `planId` the dialog asks which plan.
 *
 *  A reservation moves no stock and no money: it says which pieces the plan
 *  counts as its own, and other demand sees only the free rest. A position
 *  offers its unreserved rest by default, so reserving a whole order is one
 *  click. The dialog calls `onDone` with the plan's new schedule and then
 *  `onClose`. */
export interface ReserveDialogProps {
  planId?: number;
  documentId?: number;
  /** Preselect one part when opened from a plan's part row. */
  part?: { component_id: number | null; mpn: string; lcsc: string; name: string; qty?: number };
  onClose: () => void;
  onDone: (full: PlanFull) => void;
}

type Line = ReservableLines["lines"][number];

const reservedOf = (ln: Line) => ln.reserved.reduce((s, r) => s + (r.qty || 0), 0);
const restOf = (ln: Line) => Math.max(0, (ln.qty || 0) - reservedOf(ln));
/** A number as a person types it: a comma is a decimal point too. */
const num = (s: string) => Number(s.trim().replace(",", "."));
const LCSC = /^C\d+$/i;
/** One identity while the positions load, because `lines` feeds the table. */
const NO_LINES: Line[] = [];

export default function ReserveDialog({ planId, documentId, part, onClose, onDone }: ReserveDialogProps) {
  const modal = useModal(onClose);
  const plans = useLoad(listPlans, [], { enabled: planId == null });
  const [chosenPlan, setChosenPlan] = useState<string>(planId != null ? String(planId) : "");
  const doc = useLoad((signal) => getReservableLines(documentId as number, signal), [documentId], {
    enabled: documentId != null,
  });
  // Per position: ticked, and the quantity typed. Unset means the default.
  const [ticked, setTicked] = useState<Record<number, boolean>>({});
  const [qtys, setQtys] = useState<Record<number, string>>({});
  // By part, when there is no document.
  const [picked, setPicked] = useState<{ id: number | null; label: string } | null>(
    part?.component_id ? { id: part.component_id, label: part.name || part.mpn || `#${part.component_id}` } : null,
  );
  const [code, setCode] = useState(part ? part.mpn || part.lcsc : "");
  const [qty, setQty] = useState(part?.qty != null ? String(part.qty) : "");
  const [note, setNote] = useState("");
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lines = doc.data?.lines ?? NO_LINES;
  // The rows the filters leave: the header box ticks what the reader sees.
  const [visible, setVisible] = useState<Line[]>([]);
  const isTicked = (ln: Line) => ticked[ln.id] ?? restOf(ln) > 0;
  const qtyText = (ln: Line) => qtys[ln.id] ?? String(+restOf(ln).toFixed(3));
  const selected = lines.filter(isTicked);
  const allTicked = visible.length > 0 && visible.every(isTicked);

  const columns: Column<Line>[] = [
    {
      // The box and the quantity take lengths: a cut "1200" reads as 120.
      key: "tick", width: "40px", className: "ctr", interactive: false, sortable: true,
      label: (
        <input type="checkbox" checked={allTicked} aria-label="Tick every position shown"
          onChange={(e) => {
            const on = e.target.checked;
            setTicked((t) => ({ ...t, ...Object.fromEntries(visible.map((ln) => [ln.id, on])) }));
          }} />
      ),
      get: (ln) => (isTicked(ln) ? 0 : 1),
      title: () => undefined,
      render: (ln) => (
        <input type="checkbox" checked={isTicked(ln)} aria-label={`Reserve ${ln.mpn || ln.lcsc}`}
          onChange={(e) => setTicked((t) => ({ ...t, [ln.id]: e.target.checked }))} />
      ),
    },
    { key: "part", label: "Part", width: 50, className: "mono",
      get: (ln) => [ln.mpn, ln.lcsc, ln.description].filter(Boolean).join(" · ") || `position ${ln.id}` },
    { key: "qty", label: "Bought", width: 25, numeric: true, get: (ln) => ln.qty, render: (ln) => <>{plain(ln.qty, 0)}</> },
    {
      key: "held", label: "Reserved", width: 25, numeric: true, get: (ln) => reservedOf(ln),
      title: (ln) => (ln.reserved.length ? ln.reserved.map((r) => `${plain(r.qty, 0)} for plan ${r.plan_id}`).join(", ") : undefined),
      render: (ln) => (reservedOf(ln) > 0 ? <span className="warn-text">{plain(reservedOf(ln), 0)}</span> : <>—</>),
    },
    {
      key: "reserve", label: "Reserve", width: "108px", numeric: true, interactive: false, get: () => "", title: () => undefined,
      render: (ln) => (
        <input className="row-input num" inputMode="decimal" value={qtyText(ln)} disabled={!isTicked(ln)}
          aria-label={`Quantity of ${ln.mpn || ln.lcsc} to reserve`}
          onChange={(e) => setQtys((q) => ({ ...q, [ln.id]: e.target.value }))} />
      ),
    },
  ];
  const planName = planId != null ? "" : plans.data?.find((p) => String(p.id) === chosenPlan)?.name ?? "";

  const reserve = async () => {
    const pid = Number(chosenPlan);
    if (!pid) {
      setError("Choose the plan the stock is for.");
      return;
    }
    const body: PlanReservationIn[] = [];
    if (documentId != null) {
      for (const ln of selected) {
        const q = num(qtyText(ln));
        if (!Number.isFinite(q) || q <= 0) {
          setError(`Give ${ln.mpn || ln.lcsc || "each ticked position"} a quantity above 0, or untick it.`);
          return;
        }
        body.push({ source_line_id: ln.id, qty: q, note: note.trim() });
      }
      if (!body.length) {
        setError("Tick at least one position.");
        return;
      }
    } else {
      const q = num(qty);
      const c = code.trim();
      if (!picked?.id && !c) {
        setError("Pick the part, or type its MPN or LCSC number.");
        return;
      }
      if (!Number.isFinite(q) || q <= 0) {
        setError("Give a quantity above 0.");
        return;
      }
      const isLcsc = LCSC.test(c);
      body.push({
        component_id: picked?.id ?? null,
        mpn: isLcsc ? "" : c,
        lcsc: isLcsc ? c.toUpperCase() : part?.lcsc ?? "",
        qty: q,
        note: note.trim(),
      });
    }
    setBusy(true);
    setError(null);
    try {
      const full = await addPlanReservations(pid, body);
      onDone(full);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <>
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">
          Reserve for a plan
          {doc.data ? <span className="muted"> · {doc.data.supplier} {doc.data.external_id}</span> : null}
        </h2>
        <p className="muted dim">
          A reservation moves no stock and no money. The plan counts these pieces as its own, and other demand sees
          only what is left. The plan&apos;s page lists each reservation and removes it.
        </p>
        <ErrorBanner message={error ?? plans.error ?? doc.error} />
        <FieldGrid>
          {planId == null ? (
            <Field label="Plan">
              {plans.data === null ? <Spinner /> : plans.data.length === 0 ? (
                <span className="muted">No plan exists yet. Make one on Sales → Plans.</span>
              ) : (
                <select className="text" value={chosenPlan} onChange={(e) => setChosenPlan(e.target.value)}>
                  <option value="">— choose a plan —</option>
                  {plans.data.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}{p.customer ? ` · ${p.customer}` : ""}</option>
                  ))}
                </select>
              )}
            </Field>
          ) : null}
          <Field label="Note" wide hint="Why these pieces are the plan's, e.g. the order they came with">
            <input className="text" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
          </Field>
        </FieldGrid>

        {documentId != null ? (
          doc.data === null ? <Spinner label="Loading the positions…" /> : lines.length === 0 ? (
            <p className="muted">This document holds no part position that went into stock.</p>
          ) : (
            // A JLC order holds 40 lots: scroll the rows, so Reserve stays reachable.
            <div className="split-rows-scroll">
              <DataTable
                rows={lines}
                rowKey={(ln) => ln.id}
                columns={columns}
                onVisibleChange={setVisible}
                rowClass={(ln) => (isTicked(ln) ? "" : "dim")}
              />
            </div>
          )
        ) : (
          <FieldGrid>
            <Field label="Part" group>
              <button type="button" className={picked?.id ? "linklike" : "btn btn-sm"} onClick={() => setPicking(true)}>
                {picked?.id ? picked.label : "Pick a part…"}
              </button>
            </Field>
            <Field label="MPN or LCSC" hint={picked?.id ? "The picked part's code, as the supplier prints it" : "When the part is not in the library"}>
              <input className="text mono" value={code} placeholder="MPN, or C123456" onChange={(e) => setCode(e.target.value)} />
            </Field>
            <Field label="Quantity">
              <input className="text num-input" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} />
            </Field>
          </FieldGrid>
        )}

        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || (documentId != null && !selected.length)}
            onClick={() => void reserve()}>
            {documentId != null
              ? `Reserve ${plural(selected.length, "position")}${planName ? ` for ${planName}` : ""}`
              : `Reserve${planName ? ` for ${planName}` : ""}`}
          </button>
        </div>
      </div>
    </div>
      {picking ? (
        <ComponentPickDialog
          line={{ label: picked?.label || code, mpn: LCSC.test(code.trim()) ? "" : code.trim(),
                  component_id: picked?.id ?? null, component_name: picked?.label ?? null, kind: "reservation" }}
          title="Which part does the plan reserve?"
          confirmLabel="Use this part"
          onPick={(componentId, mpn) => {
            setPicked(componentId ? { id: componentId, label: mpn || `#${componentId}` } : null);
            if (!code.trim()) setCode(mpn);
          }}
          onClose={() => setPicking(false)}
        />
      ) : null}
    </>
  );
}
