/** In-house stock transfers between our two companies (decision 0064).
 *
 *  A transfer is how stock one company bought reaches a batch of the other. It
 *  is an internal record, never filed: no invoice is issued and no money moves.
 *  It is priced at the sender's average on the date, so both companies'
 *  figures together stay what they were. It changes only as a whole: a wrong
 *  one is reversed and written again.
 */
import { useCallback, useEffect, useState } from "react";
import {
  createTransfer,
  errorMessage,
  isAbortError,
  listTransfers,
  reverseTransfer,
  type TransferLineIn,
  type TransferPlan,
  type TransferRow,
} from "../api";
import { useAuth } from "../auth";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import Field, { FieldGrid, FieldRow } from "../components/Field";
import NumberInput from "../components/NumberInput";
import { ErrorBanner, Spinner } from "../components/Ui";
import { plain } from "../format";

const COLUMNS: Column<TransferRow>[] = [
  { key: "date", label: "Date", width: 11, className: "mono", get: (t) => t.date },
  { key: "number", label: "Number", width: 14, className: "mono", get: (t) => t.doc_number },
  { key: "from", label: "From", width: 12, get: (t) => t.sender },
  { key: "to", label: "To", width: 12, get: (t) => t.receiver },
  { key: "lines", label: "Positions", width: 10, numeric: true, get: (t) => t.lines.length },
  { key: "value", label: "Value (USD)", width: 13, numeric: true, get: (t) => t.value_usd,
    render: (t) => <>{plain(t.value_usd)}</> },
  { key: "state", label: "State", width: 10, get: (t) => (t.reversed ? "reversed" : "in force"),
    render: (t) => <span className={"pill " + (t.reversed ? "neutral" : "ok")}>{t.reversed ? "reversed" : "in force"}</span> },
  { key: "notes", label: "Notes", width: 18, className: "muted", get: (t) => t.notes },
];

const LINE_COLUMNS: Column<TransferRow["lines"][number]>[] = [
  { key: "part", label: "Part", width: 40, get: (ln) => ln.label || ln.mpn || ln.lcsc },
  { key: "qty", label: "Quantity", width: 15, numeric: true, get: (ln) => ln.qty,
    render: (ln) => <>{plain(ln.qty)}</> },
  { key: "unit", label: "Unit (USD)", width: 15, numeric: true, get: (ln) => ln.unit_cost_usd,
    render: (ln) => <>{ln.unit_cost_usd.toFixed(4)}</> },
  { key: "price", label: "Price", width: 30, className: "muted", get: (ln) => ln.price },
];

function TransferDetail({ t, onChanged }: { t: TransferRow; onChanged: () => void }) {
  const dialog = useDialog();
  const [err, setErr] = useState("");
  const reverse = async () => {
    const reason = await dialog.prompt(`Why is ${t.doc_number} reversed?`, { title: "Reverse transfer" });
    if (!reason) return;
    try {
      await reverseTransfer(t.id, reason, false);
      onChanged();
    } catch (e) {
      setErr(errorMessage(e));
    }
  };
  return (
    <div className="user-detail">
      <ErrorBanner message={err} />
      <DataTable rows={t.lines} rowKey={(ln) => ln.id} columns={LINE_COLUMNS} empty="No positions." />
      {!t.reversed ? (
        <div className="btn-row">
          <button type="button" className="btn btn-sm btn-danger" onClick={() => void reverse()}>
            Reverse…
          </button>
          <span className="muted dim">Refused while the receiving company used what it got.</span>
        </div>
      ) : null}
    </div>
  );
}

interface DraftLine { part: string; qty: number | null }

function NewTransferCard({ onDone }: { onDone: () => void }) {
  const { companies } = useAuth();
  const [sender, setSender] = useState<number | "">(companies[0]?.id ?? "");
  const [receiver, setReceiver] = useState<number | "">(companies[1]?.id ?? "");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [lines, setLines] = useState<DraftLine[]>([{ part: "", qty: null }]);
  const [note, setNote] = useState("");
  const [plan, setPlan] = useState<TransferPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const body = (dryRun: boolean) => ({
    sender_id: Number(sender), receiver_id: Number(receiver), date, note, dry_run: dryRun,
    lines: lines.filter((l) => l.part.trim() && l.qty).map((l): TransferLineIn => {
      const p = l.part.trim();
      // An LCSC code is C followed by digits; anything else is an MPN.
      return /^C\d+$/i.test(p) ? { lcsc: p.toUpperCase(), qty: Number(l.qty) } : { mpn: p, qty: Number(l.qty) };
    }),
  });
  const run = async (dryRun: boolean) => {
    setBusy(true);
    setErr("");
    try {
      const res = await createTransfer(body(dryRun));
      setPlan(res);
      if (!dryRun) {
        setLines([{ part: "", qty: null }]);
        setNote("");
        setPlan(null);
        onDone();
      }
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const ready = sender !== "" && receiver !== "" && sender !== receiver && date
    && lines.some((l) => l.part.trim() && l.qty);
  const blocked = !!plan && (plan.shortages.length > 0 || plan.problems.length > 0);

  return (
    <div className="card pad edit-card">
      <h2 className="card-title">New transfer</h2>
      <p className="muted dim">
        Name the parts by MPN or LCSC code. Preview prices each one at the sending company's average on
        the date and checks that it held them. Nothing is written until you press Write.
      </p>
      <ErrorBanner message={err} />
      <FieldGrid>
        <Field label="From">
          <select className="text" value={sender} onChange={(e) => { setSender(Number(e.target.value)); setPlan(null); }}>
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="To">
          <select className="text" value={receiver} onChange={(e) => { setReceiver(Number(e.target.value)); setPlan(null); }}>
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Date" hint="On or before the receiving batch uses the parts.">
          <input className="text" type="date" value={date} onChange={(e) => { setDate(e.target.value); setPlan(null); }} />
        </Field>
        <Field label="Note" wide>
          <input className="text" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </FieldGrid>
      {lines.map((l, i) => (
        <FieldRow key={i}>
          <Field label={i === 0 ? "Part (MPN or LCSC)" : undefined}>
            <input className="text" value={l.part}
              onChange={(e) => { setLines(lines.map((x, j) => (j === i ? { ...x, part: e.target.value } : x))); setPlan(null); }} />
          </Field>
          <Field label={i === 0 ? "Quantity" : undefined}>
            <NumberInput className="text num-input" value={l.qty} min={0} step={1}
              onChange={(v) => { setLines(lines.map((x, j) => (j === i ? { ...x, qty: v } : x))); setPlan(null); }}
              onEmpty={() => setLines(lines.map((x, j) => (j === i ? { ...x, qty: null } : x)))} />
          </Field>
          {lines.length > 1 ? (
            <button type="button" className="btn btn-sm" onClick={() => setLines(lines.filter((_x, j) => j !== i))}>
              Remove
            </button>
          ) : null}
        </FieldRow>
      ))}
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={() => setLines([...lines, { part: "", qty: null }])}>
          Add a part
        </button>
        <button type="button" className="btn btn-sm" disabled={!ready || busy} onClick={() => void run(true)}>
          Preview
        </button>
        <button type="button" className="btn btn-primary btn-sm" disabled={!ready || busy || !plan || blocked}
          onClick={() => void run(false)}>
          Write
        </button>
      </div>
      {plan ? (
        <>
          {plan.problems.map((p) => <div key={p.line} className="banner-warn">Part {p.line + 1}: {p.problem}</div>)}
          {plan.shortages.map((sh) => (
            <div key={sh.label} className="banner-warn">
              {plan.sender} holds {plain(sh.on_hand)} of {sh.label || sh.mpn} on {plan.date}, not {plain(sh.needed)}.
            </div>
          ))}
          <p className="muted">
            {plan.lines.length} part(s), {plain(plan.value_usd)} USD:{" "}
            {plan.lines.map((ln) => `${ln.mpn || ln.lcsc} ${plain(ln.qty)} × ${ln.unit_cost_usd.toFixed(4)}`).join(", ")}
          </p>
        </>
      ) : null}
    </div>
  );
}

export default function Transfers() {
  const [rows, setRows] = useState<TransferRow[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback((signal?: AbortSignal) => {
    listTransfers(signal)
      .then((r) => { setRows(r); setError(""); })
      .catch((e) => { if (!isAbortError(e)) setError(errorMessage(e)); });
  }, []);
  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1 className="page-title">Transfers</h1>
          {rows ? (
            <span className="toolbar-total">{rows.filter((t) => !t.reversed).length} in force</span>
          ) : null}
        </div>
        <p className="muted dim">
          Stock moved between our two companies. Each company's batches draw only from its own stock
          once stock is kept per company (Admin → Configuration).
        </p>
        <ErrorBanner message={error} />
        <NewTransferCard onDone={() => load()} />
        <div className="card pad">
          <h2 className="card-title">Transfers</h2>
          {rows === null ? (
            <Spinner label="Loading transfers…" />
          ) : (
            <DataTable
              rows={rows}
              rowKey={(t) => t.id}
              columns={COLUMNS}
              empty="No transfers yet."
              defaultSort={{ key: "date", dir: "desc" }}
              expand={(t) => <TransferDetail t={t} onChanged={() => load()} />}
            />
          )}
        </div>
      </div>
    </div>
  );
}
