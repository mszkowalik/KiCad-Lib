/** Stock → Organizers: which box in the office holds what (decision 0104).
 *
 *  The organizers are shared by both companies; the pieces in a box are a
 *  company's. This page replaced a Google sheet, so its first job is to answer
 *  "where is this part" and "how many are left".
 *
 *  A TAKE is more than a box going down: it is a draw from the stock ledger, so
 *  it is a cost. R&D is charged to no batch, and a batch take charges that
 *  batch. A COUNT is absolute, because the number is read off the box. Rules in
 *  `api/app/services/organizers.py` and docs/reference/organizers.md.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  addOrganizerBoxes,
  clearOrganizerPart,
  countOrganizerBox,
  deleteOrganizerBox,
  errorMessage,
  getAllRuns,
  getOrganizerMoves,
  getOrganizerResearch,
  getOrganizers,
  importOrganizers,
  isAbortError,
  moveOrganizerPart,
  patchOrganizerBox,
  recordOrganizerUse,
  renameOrganizer,
  takeFromOrganizerBox,
  type CompanyRef,
  type OrganizerBoxRow,
  type OrganizerImportPlanRow,
  type OrganizerImportResult,
  type OrganizerImportRow,
  type OrganizerMoveRow,
  type OrganizerOverview,
  type OrganizerPart,
  type OrganizerPartRef,
  type OrganizerResearchRow,
} from "../api";
import { useAuth } from "../auth";
import AutoTextarea from "../components/AutoTextarea";
import ComponentPickDialog from "../components/ComponentPickDialog";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import Field, { FieldGrid, FieldRow } from "../components/Field";
import FoldSection, { StatChip, NarrowChip } from "../components/FoldSection";
import NumberInput from "../components/NumberInput";
import { DryRunDialog } from "../components/process/StageDialogs";
import { ErrorBanner, Spinner } from "../components/Ui";
import { useModal } from "../components/modal";
import { plural, pln, today } from "../format";
import { useTodayRate } from "../useTodayRate";
import { useLoad } from "../components/useLoad";
import PageShell from "../components/PageShell";

/** One line of the table: a part in a box, or an empty box. */
interface Row {
  key: string;
  box: OrganizerBoxRow;
  part: OrganizerPart | null;
}

type Dlg =
  | { kind: "take"; row: Row }
  | { kind: "count"; row: Row }
  | { kind: "move"; row: Row }
  | { kind: "put"; box: OrganizerBoxRow; part: OrganizerPartRef & { name: string } }
  | { kind: "pick"; box: OrganizerBoxRow }
  | { kind: "add" }
  | { kind: "use" }
  | { kind: "import" };

/** Boxes sort as they are printed: 2 before 10, A9 before A10. */
const natural = (code: string) => code.replace(/\d+/g, (d) => d.padStart(6, "0"));
const pcs = (v: number) => Math.round(v * 1000) / 1000;
const partRef = (p: OrganizerPart): OrganizerPartRef => ({
  component_id: p.component_id, mpn: p.mpn, lcsc: p.lcsc,
});

/** The company a new write starts on: the one the header names, or the only one. */
const startCompany = (scope: string, companies: CompanyRef[]) =>
  (scope !== "all" ? Number(scope) : companies.length === 1 ? companies[0].id : null);

const KIND_LABEL: Record<OrganizerMoveRow["kind"], string> = {
  opening: "imported", count: "counted", take: "taken", move: "moved", clear: "cleared",
};

/** A cost that reads 0 needs its reason on the hover (decision 0104). */
const ZERO_COST = "no purchase in the records prices this part";

export default function Organizers() {
  const dialog = useDialog();
  const [data, setData] = useState<OrganizerOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [organizer, setOrganizer] = useState("");
  const [showEmpty, setShowEmpty] = useState(false);
  const [dlg, setDlg] = useState<Dlg | null>(null);
  const [research, setResearch] = useState<OrganizerResearchRow[]>([]);
  // A box and R&D belong to no batch, so their money reads at today's rate (decision 0103).
  const rate = useTodayRate();
  // An open row reads its own history, so it must hear that a write happened.
  const [revision, setRevision] = useState(0);
  const [params] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");

  const load = useCallback((signal?: AbortSignal) => {
    getOrganizers(signal)
      .then((d) => { setData(d); setError(null); })
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    getOrganizerResearch(signal)
      .then((r) => setResearch(r.rows))
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    setRevision((n) => n + 1);
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  // The last box of an organizer can be deleted, and its chip goes with it. A
  // filter with no chip could not be turned off.
  useEffect(() => {
    if (organizer && data && !data.organizers.some((o) => o.name === organizer)) setOrganizer("");
  }, [data, organizer]);

  const allRows = useMemo<Row[]>(() => (data?.boxes ?? []).flatMap((box): Row[] =>
    box.parts.length
      ? box.parts.map((part) => ({ key: `${box.id}:${part.item_id}`, box, part }))
      : [{ key: `${box.id}:`, box, part: null }]), [data]);

  const emptyCount = useMemo(() => {
    const scoped = (data?.boxes ?? []).filter((b) => !organizer || b.organizer === organizer);
    return scoped.filter((b) => !b.parts.some((p) => p.qty > 0)).length;
  }, [data, organizer]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return allRows.filter((r) => {
      if (organizer && r.box.organizer !== organizer) return false;
      if (showEmpty !== (r.part === null || r.part.qty <= 0)) {
        // the search looks everywhere: a part used up must still be findable
        if (!needle || r.part === null) return false;
      }
      if (!needle) return true;
      return [r.box.code, r.part?.name, r.part?.mpn, r.part?.lcsc, r.part?.note]
        .some((v) => (v ?? "").toLowerCase().includes(needle));
    });
  }, [allRows, organizer, showEmpty, search]);

  const researchUsd = useMemo(() => research.reduce((n, m) => n + m.value_usd, 0), [research]);

  /** The boxes a click on this organizer's chip shows, so a chip at 0 has nothing
   *  to show. A new organizer holds nothing and appears beside "empty boxes". */
  const boxesShown = (o: OrganizerOverview["organizers"][number]) => (showEmpty ? o.boxes - o.filled : o.filled);

  const done = (message: string) => {
    setDlg(null);
    setError(null);
    setNotice(message);
    load();
  };

  const fail = (err: unknown) => {
    setNotice(null);
    setError(errorMessage(err));
  };

  const clearRow = async (r: Row) => {
    if (!r.part) return;
    const ok = await dialog.confirm(
      `Take ${r.part.name} off box ${r.box.code}? The box holds none of it, and its history stays.`,
      { title: "Clear this row", confirmLabel: "Clear", tone: "danger" });
    if (!ok) return;
    try {
      await clearOrganizerPart(r.box.id, partRef(r.part));
      done(`Took ${r.part.name} off box ${r.box.code}.`);
    } catch (err) {
      fail(err);
    }
  };

  const deleteBox = async (box: OrganizerBoxRow) => {
    const ok = await dialog.confirm(
      `Delete box ${box.code} of organizer ${box.organizer}? It never held anything. History → Write batches can undo this.`,
      { title: "Delete this box", confirmLabel: "Delete", tone: "danger" });
    if (!ok) return;
    try {
      await deleteOrganizerBox(box.id);
      done(`Deleted box ${box.code} of organizer ${box.organizer}.`);
    } catch (err) {
      fail(err);
    }
  };

  const rename = async () => {
    const name = await dialog.prompt(`New name for organizer ${organizer}:`, {
      title: "Rename the organizer", initial: organizer, confirmLabel: "Rename", maxLength: 60,
    });
    if (!name || name.trim() === organizer) return;
    try {
      await renameOrganizer(organizer, name.trim());
      setOrganizer(name.trim());
      done(`Organizer ${organizer} is now ${name.trim()}.`);
    } catch (err) {
      fail(err);
    }
  };

  const cols: Column<Row>[] = [
    {
      key: "box", label: "Box", width: 8, className: "mono",
      get: (r) => r.box.code,
      sortValue: (r) => natural(r.box.code),
      title: (r) => r.box.note || r.box.organizer,
    },
    { key: "organizer", label: "Organizer", width: 9, get: (r) => r.box.organizer },
    {
      key: "part", label: "Part", width: 21,
      get: (r) => r.part?.name ?? "",
      title: (r) => [r.part?.mpn, r.part?.lcsc].filter(Boolean).join(" · "),
      render: (r) => !r.part ? <span className="muted">empty</span> : r.part.in_library && r.part.component_id ? (
        <Link to={`/library/components/${r.part.component_id}`} className="mono comp-link"
          onClick={(e) => e.stopPropagation()}>{r.part.name}</Link>
      ) : <span className="mono">{r.part.name}</span>,
    },
    { key: "note", label: "Note", width: 16, className: "cell-desc", get: (r) => r.part?.note ?? "" },
    {
      key: "company", label: "Company", width: 8,
      get: (r) => (r.part?.companies ?? []).map((c) => c.name).join(", "),
      title: (r) => (r.part?.companies ?? []).map((c) => `${c.name}: ${pcs(c.qty)}`).join(", "),
    },
    {
      key: "qty", label: "Qty", width: 8, numeric: true,
      get: (r) => r.part?.qty ?? "",
      render: (r) => r.part ? <>{pcs(r.part.qty).toLocaleString()}</> : <>—</>,
    },
    {
      key: "last", label: "Last change", width: 10, className: "muted",
      get: (r) => r.part?.last_at ?? "",
      title: (r) => r.part?.last_actor ?? "",
    },
    {
      key: "actions", label: "", width: 20, interactive: false, className: "ctr",
      get: () => "",
      render: (r) => <RowActions row={r} onOpen={setDlg} onClear={clearRow} />,
    },
  ];

  const researchCols: Column<OrganizerResearchRow>[] = [
    { key: "at", label: "Date", width: 11, className: "mono", get: (m) => m.at },
    { key: "name", label: "Part", width: 20, className: "mono", get: (m) => m.name },
    { key: "box", label: "Box", width: 8, className: "mono", get: (m) => m.box },
    { key: "qty", label: "Qty", width: 8, numeric: true, get: (m) => m.qty,
      render: (m) => <>{pcs(m.qty).toLocaleString()}</> },
    { key: "value", label: "Cost", width: 14, numeric: true, get: (m) => pln(m.value_usd, rate),
      sortValue: (m) => m.value_usd,
      title: (m) => (m.value_usd === 0 ? ZERO_COST : pln(m.value_usd, rate)) },
    { key: "company", label: "Company", width: 9, get: (m) => m.company },
    { key: "note", label: "What for", width: 21, className: "cell-desc", get: (m) => m.note },
    { key: "actor", label: "Who", width: 9, className: "muted", get: (m) => m.actor },
  ];

  return (
    <PageShell>
      <div className="toolbar">
        <h1>Organizers</h1>
        {data ? (
          <span className="toolbar-total">
            {data.totals.parts} parts, {pcs(data.totals.pieces).toLocaleString()} pieces in{" "}
            {data.totals.filled} of {data.totals.boxes} boxes
          </span>
        ) : null}
        <button type="button" className="btn" onClick={() => setDlg({ kind: "import" })}>
          Load a list…
        </button>
        <button type="button" className="btn btn-primary" onClick={() => setDlg({ kind: "add" })}>
          Add organizer
        </button>
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      {notice ? <div className="banner-ok">{notice}</div> : null}

      {!data ? (
        <div className="card pad"><Spinner label="Loading the boxes…" /></div>
      ) : data.totals.boxes === 0 ? (
        <div className="card pad">
          <p className="muted dim">No organizer yet. Add one and give it its boxes, or load a list.</p>
        </div>
      ) : (
        <>
          <div className="stat-row">
            {data.organizers
              .filter((o) => boxesShown(o) > 0 || organizer === o.name)
              .map((o) => (
                <NarrowChip key={o.name} n={boxesShown(o).toLocaleString()} value={o.name} current={organizer} onNarrow={setOrganizer}
                  title={`${o.filled} of ${o.boxes} boxes hold something, ${pcs(o.pieces).toLocaleString()} pieces`}>
                  {o.name}
                </NarrowChip>
              ))}
            {emptyCount > 0 || showEmpty ? (
              <StatChip n={emptyCount.toLocaleString()} on={showEmpty} onClick={() => setShowEmpty(!showEmpty)}>
                empty boxes
              </StatChip>
            ) : null}
          </div>

          <div className="toolbar">
            <input className="text search" value={search} placeholder="Find a part or a box"
              onChange={(e) => setSearch(e.target.value)} />
            {organizer ? (
              <button type="button" className="btn btn-sm" onClick={rename}>Rename {organizer}</button>
            ) : null}
            <span className="toolbar-total">{rows.length} / {allRows.length}</span>
            {organizer || showEmpty || search ? (
              <button type="button" className="row-del clear-filters"
                onClick={() => { setOrganizer(""); setShowEmpty(false); setSearch(""); }}
                title="Clear filters" aria-label="Clear filters">
                &#x2715;
              </button>
            ) : null}
          </div>

          <div className="card table-wrap">
            <DataTable
              columns={cols}
              rows={rows}
              rowKey={(r) => r.key}
              persistKey="organizers"
              defaultSort={{ key: "box", dir: "asc" }}
              expand={(r) => (
                <RowPanel row={r} rate={rate} revision={revision} onOpen={setDlg} onDelete={deleteBox} onSaved={done} />
              )}
              empty={showEmpty ? "No empty box here." : "Nothing here matches."}
            />
          </div>
        </>
      )}

      <FoldSection
        title="Used for R&D"
        count={research.length}
        foldKey="organizers:research"
        chips={research.length ? <StatChip n={pln(researchUsd, rate)}>at cost</StatChip> : undefined}
        actions={(
          <button type="button" className="btn btn-sm" onClick={() => setDlg({ kind: "use" })}>
            Pieces in no box…
          </button>
        )}
      >
        <p className="muted dim">
          Charged to no batch. A part with no purchase in the records costs 0 here. A row with no box was used
          before its invoice reached the stock records.
          The company&apos;s books counted stock as a cost when it was bought, so these figures add nothing
          there.
        </p>
        <DataTable columns={researchCols} rows={research} rowKey={(m) => m.id} persistKey="organizers:research"
          empty="Nothing has been taken for R&D." />
      </FoldSection>

      {dlg?.kind === "take" ? <TakeDialog row={dlg.row} rate={rate} onClose={() => setDlg(null)} onDone={done} /> : null}
      {dlg?.kind === "move" && data ? (
        <MoveDialog row={dlg.row} boxes={data.boxes} onClose={() => setDlg(null)} onDone={done} />
      ) : null}
      {dlg?.kind === "count" && dlg.row.part ? (
        <CountDialog box={dlg.row.box} part={dlg.row.part} onClose={() => setDlg(null)} onDone={done} />
      ) : null}
      {dlg?.kind === "put" ? (
        <CountDialog box={dlg.box} newPart={dlg.part} onClose={() => setDlg(null)} onDone={done} />
      ) : null}
      {dlg?.kind === "pick" ? (
        <ComponentPickDialog
          line={{ kind: `Box ${dlg.box.code}` }}
          title={`What goes in box ${dlg.box.code}?`}
          confirmLabel="Choose"
          allowFreeText
          onClose={() => setDlg((d) => (d?.kind === "pick" ? null : d))}
          onPick={(componentId, mpn) => setDlg({
            kind: "put", box: dlg.box, part: { component_id: componentId, mpn, name: mpn || `component ${componentId}` },
          })}
        />
      ) : null}
      {dlg?.kind === "add" ? <AddOrganizerDialog onClose={() => setDlg(null)} onDone={done} /> : null}
      {dlg?.kind === "use" ? <NoBoxDialog rate={rate} onClose={() => setDlg(null)} onDone={done} /> : null}
      {dlg?.kind === "import" ? <ImportDialog onClose={() => setDlg(null)} onDone={done} /> : null}
    </PageShell>
  );
}

function RowActions({ row, onOpen, onClear }: {
  row: Row;
  onOpen: (d: Dlg) => void;
  onClear: (r: Row) => void;
}) {
  const stop = (fn: () => void) => (e: React.MouseEvent) => { e.stopPropagation(); fn(); };
  if (!row.part) {
    return <button type="button" className="btn btn-sm" onClick={stop(() => onOpen({ kind: "pick", box: row.box }))}>Put</button>;
  }
  if (row.part.qty <= 0) {
    return (
      <>
        <button type="button" className="btn btn-sm" onClick={stop(() => onOpen({ kind: "count", row }))}>Count</button>{" "}
        <button type="button" className="btn btn-sm" onClick={stop(() => onClear(row))}>Clear</button>
      </>
    );
  }
  return (
    <>
      <button type="button" className="btn btn-sm" onClick={stop(() => onOpen({ kind: "take", row }))}>Take</button>{" "}
      <button type="button" className="btn btn-sm" onClick={stop(() => onOpen({ kind: "count", row }))}>Count</button>{" "}
      <button type="button" className="btn btn-sm" onClick={stop(() => onOpen({ kind: "move", row }))}>Move</button>
    </>
  );
}

/** The code and the note of a box. They belong to the box, so they read the same
 *  on each of its rows. The patch names only what differs, so the audit row names
 *  the edit and not the whole form. */
function BoxForm({ box, onSaved }: { box: OrganizerBoxRow; onSaved: (message: string) => void }) {
  const [code, setCode] = useState(box.code);
  const [note, setNote] = useState(box.note);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const patch = {
    ...(code.trim() !== box.code ? { code: code.trim() } : {}),
    ...(note.trim() !== box.note ? { note: note.trim() } : {}),
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await patchOrganizerBox(box.id, patch);
      onSaved(res.code !== box.code ? `Box ${box.code} is now box ${res.code}.` : `Saved the note of box ${res.code}.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {error ? <ErrorBanner message={error} /> : null}
      <FieldRow>
        <Field label="Code on the box">
          <input className="text" value={code} maxLength={40} onChange={(e) => { setCode(e.target.value); setError(null); }} />
        </Field>
        <Field label="Note on the box">
          <input className="text" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <button type="button" className="btn btn-primary btn-sm" onClick={save}
          disabled={busy || !code.trim() || !Object.keys(patch).length}>
          Save box
        </button>
      </FieldRow>
    </>
  );
}

/** The fold of a row: its box, and the moves of this part in this box. A row with
 *  no part lists every move of the box, because a part moved away leaves its row
 *  and keeps its history. */
function RowPanel({ row, rate, revision, onOpen, onDelete, onSaved }: {
  row: Row;
  rate: number | null;
  revision: number;
  onOpen: (d: Dlg) => void;
  onDelete: (box: OrganizerBoxRow) => void;
  onSaved: (message: string) => void;
}) {
  const itemId = row.part?.item_id;
  const { data: moves, error } = useLoad(
    (signal) => getOrganizerMoves({ box_id: row.box.id, item_id: itemId, limit: 1000 }, signal),
    [row.box.id, itemId, revision],
    { keep: true },
  );

  const cost = (m: OrganizerMoveRow) => (m.value_usd == null ? "" : pln(m.value_usd, rate));
  const columns: Column<OrganizerMoveRow>[] = [
    { key: "at", label: "Date", width: 11, className: "mono", get: (m) => m.at },
    ...(row.part ? [] : [{ key: "name", label: "Part", width: 14, className: "mono", get: (m: OrganizerMoveRow) => m.name }]),
    { key: "what", label: "What", width: 13,
      get: (m) => `${KIND_LABEL[m.kind]}${m.purpose === "research" ? " for R&D" : ""}` },
    { key: "qty", label: "Qty", width: 8, numeric: true, get: (m) => m.qty,
      render: (m) => <>{m.qty > 0 ? "+" : ""}{pcs(m.qty).toLocaleString()}</> },
    { key: "batch", label: "Batch", width: row.part ? 13 : 9,
      get: (m) => (m.run_id ? m.run_label ?? `batch ${m.run_id}` : ""),
      render: (m) => (m.run_id ? <Link to={`/production/batches/${m.run_id}`}>{m.run_label ?? `batch ${m.run_id}`}</Link> : null) },
    { key: "cost", label: "Cost", width: 14, numeric: true, get: cost, sortValue: (m) => m.value_usd ?? -1,
      title: (m) => (m.value_usd === 0 ? ZERO_COST : cost(m)) },
    { key: "company", label: "Company", width: 9, get: (m) => m.company },
    { key: "actor", label: "Who", width: 11, className: "muted", get: (m) => m.actor },
    { key: "note", label: "Note", width: row.part ? 21 : 11, className: "cell-desc", get: (m) => m.note },
  ];

  return (
    <>
      <BoxForm key={`${row.box.id}:${row.box.code}:${row.box.note}`} box={row.box} onSaved={onSaved} />
      {row.part || moves?.length === 0 ? (
        <div className="btn-row">
          {row.part ? (
            <button type="button" className="btn btn-sm" onClick={() => onOpen({ kind: "pick", box: row.box })}>
              Put another part in box {row.box.code}
            </button>
          ) : null}
          {moves?.length === 0 ? (
            <button type="button" className="btn btn-sm btn-danger" onClick={() => onDelete(row.box)}>
              Delete box {row.box.code}
            </button>
          ) : null}
        </div>
      ) : null}
      {error ? <ErrorBanner message={error} /> : !moves ? <Spinner label="Loading…" /> : moves.length ? (
        <FoldSection bare title="History" count={moves.length} foldKey="organizers:history">
          <DataTable columns={columns} rows={moves} rowKey={(m) => m.id} />
        </FoldSection>
      ) : <p className="muted dim">This box never held anything.</p>}
    </>
  );
}

/** The frame of the dialogs here that write at once. `DryRunDialog` is the only
 *  shared frame, and these writes have no dry run for its Preview to call. */
function Modal({ title, subtitle, onClose, busy, error, onSubmit, submitLabel, disabled, children }: {
  title: string;
  subtitle?: React.ReactNode;
  onClose: () => void;
  busy: boolean;
  error: string | null;
  onSubmit: () => void;
  submitLabel: string;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const modal = useModal(onClose);
  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card" {...modal.cardProps}>
        <h2 className="card-title">{title}</h2>
        {subtitle ? <p className="muted dim">{subtitle}</p> : null}
        {error ? <ErrorBanner message={error} /> : null}
        {children}
        <div className="btn-row modal-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={onSubmit} disabled={busy || disabled}>
            {submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Asked only when both companies hold the part in this box (user decision
 *  2026-11-07): with one company there is nothing to choose. */
function CompanyOfBox({ part, value, onChange }: {
  part: OrganizerPart;
  value: number | null;
  onChange: (id: number) => void;
}) {
  if (part.companies.length < 2) return null;
  return (
    <Field label="Whose pieces">
      <select className="text" value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))}>
        <option value="" disabled>Choose…</option>
        {part.companies.map((c) => <option key={c.id} value={c.id}>{c.name} ({pcs(c.qty)})</option>)}
      </select>
    </Field>
  );
}

function TakeDialog({ row, rate, onClose, onDone }: {
  row: Row;
  rate: number | null;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const part = row.part as OrganizerPart;
  const { companies } = useAuth();
  const [qty, setQty] = useState<number | null>(null);
  const [company, setCompany] = useState<number | null>(part.companies.length === 1 ? part.companies[0].id : null);
  const [purpose, setPurpose] = useState<"research" | "batch">("research");
  const [runId, setRunId] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [at, setAt] = useState(today());
  const [busy, setBusy] = useState(false);
  const { data: runs, error, setError } = useLoad(getAllRuns, [], { enabled: purpose === "batch", once: true });

  const held = company != null ? part.companies.find((c) => c.id === company)?.qty ?? 0 : part.qty;
  const batches = (runs ?? []).filter((r) => company == null || !r.company_id || r.company_id === company);
  const run = (runs ?? []).find((r) => r.id === runId);
  const missing = !qty || qty > held || company == null
    || (purpose === "research" && !note.trim()) || (purpose === "batch" && runId == null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await takeFromOrganizerBox(row.box.id, {
        ...partRef(part), qty: qty as number, purpose, company_id: company,
        run_id: purpose === "batch" ? runId : null, note, at,
      });
      const who = companies.length > 1 ? `, ${part.companies.find((c) => c.id === res.company_id)?.name}` : "";
      onDone(
        `Took ${qty} of ${part.name} from box ${row.box.code}${who}. ${pcs(res.left)} left in the box. ` +
        (res.value_usd != null ? `Cost: ${pln(res.value_usd, rate)}. ` : "The batch's process steps draw the parts. ") +
        `History → Write batches can undo it (batch ${res.batch_id}).`,
      );
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Modal title={`Take from box ${row.box.code}`} subtitle={<><span className="mono">{part.name}</span>, {pcs(part.qty)} in the box</>}
      onClose={onClose} busy={busy} error={error} onSubmit={submit} submitLabel="Take" disabled={missing}>
      <FieldRow>
        <Field label="Pieces"><NumberInput className="text num-input" value={qty} min={1} max={held} onChange={setQty} onEmpty={() => setQty(null)} /></Field>
        <CompanyOfBox part={part} value={company} onChange={setCompany} />
        <Field label="Date"><input className="text" type="date" value={at} onChange={(e) => setAt(e.target.value)} /></Field>
      </FieldRow>
      <Field label="Used for">
        <select className="text" value={purpose} onChange={(e) => setPurpose(e.target.value as "research" | "batch")}>
          <option value="research">R&amp;D: a cost of no batch</option>
          <option value="batch">A batch</option>
        </select>
      </Field>
      {purpose === "batch" ? (
        <Field label="Batch" hint={run?.process_version_id
          ? "This batch's process steps draw the parts, so this take moves the box only."
          : "This batch pays for the pieces."}>
          {runs === null ? <Spinner label="Loading batches…" /> : (
            <select className="text" value={runId ?? ""} onChange={(e) => setRunId(Number(e.target.value))}>
              <option value="" disabled>Choose…</option>
              {batches.map((r) => <option key={r.id} value={r.id}>{r.label} ({r.run_date || r.status})</option>)}
            </select>
          )}
        </Field>
      ) : null}
      <Field label={purpose === "research" ? "What the work is" : "Note (optional)"}>
        <input className="text" value={note} maxLength={400} onChange={(e) => setNote(e.target.value)} />
      </Field>
    </Modal>
  );
}

/** What the box holds, read off the box. Also how a part goes into a box. */
function CountDialog({ box, part, newPart, onClose, onDone }: {
  box: OrganizerBoxRow;
  part?: OrganizerPart;
  newPart?: OrganizerPartRef & { name: string };
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const { companies, scope } = useAuth();
  const name = part?.name ?? newPart?.name ?? "";
  const start = scope === "all" && part?.companies.length === 1 ? part.companies[0].id : startCompany(scope, companies);
  const [company, setCompany] = useState<number | null>(start);
  const held = part?.companies.find((c) => c.id === company)?.qty ?? 0;
  const [qty, setQty] = useState<number | null>(part ? held : null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const ref = part ? partRef(part) : { component_id: newPart?.component_id, mpn: newPart?.mpn, lcsc: newPart?.lcsc };
      const res = await countOrganizerBox(box.id, { ...ref, company_id: company as number, qty: qty as number, note });
      const extra = res.found > 0
        ? ` ${pcs(res.found)} are in no purchase and entered stock at zero value.`
        : res.written_off > 0 ? ` ${pcs(res.written_off)} were written off stock.` : "";
      onDone(res.changed
        ? `Box ${box.code} holds ${qty} of ${name}.${extra} History → Write batches can undo it (batch ${res.batch_id}).`
        : `Box ${box.code} already held ${qty} of ${name}.`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Modal title={part ? `Count box ${box.code}` : `Put in box ${box.code}`}
      subtitle={<><span className="mono">{name}</span>. Type what the box holds now, not the change.</>}
      onClose={onClose} busy={busy} error={error} onSubmit={submit} submitLabel="Save"
      disabled={qty == null || company == null}>
      <FieldRow>
        <Field label="Pieces in the box"><NumberInput className="text num-input" value={qty} min={0} onChange={setQty} onEmpty={() => setQty(null)} /></Field>
        {companies.length > 1 ? (
          <Field label="Company">
            <select className="text" value={company ?? ""} onChange={(e) => {
              const id = Number(e.target.value);
              setCompany(id);
              if (part) setQty(part.companies.find((c) => c.id === id)?.qty ?? 0);
            }}>
              <option value="" disabled>Choose…</option>
              {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        ) : null}
      </FieldRow>
      <Field label="Note (optional)">
        <input className="text" value={note} maxLength={400} onChange={(e) => setNote(e.target.value)} />
      </Field>
    </Modal>
  );
}

function MoveDialog({ row, boxes, onClose, onDone }: {
  row: Row;
  boxes: OrganizerBoxRow[];
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const part = row.part as OrganizerPart;
  const [qty, setQty] = useState<number | null>(part.qty);
  const [company, setCompany] = useState<number | null>(part.companies.length === 1 ? part.companies[0].id : null);
  const [to, setTo] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const targets = useMemo(() => boxes.filter((b) => b.id !== row.box.id)
    .sort((a, b) => a.organizer.localeCompare(b.organizer) || natural(a.code).localeCompare(natural(b.code))), [boxes, row.box.id]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await moveOrganizerPart(row.box.id, { ...partRef(part), qty: qty as number, to_box_id: to as number, company_id: company });
      onDone(`Moved ${qty} of ${part.name}. ${pcs(res.left)} left in box ${row.box.code}.`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Modal title={`Move from box ${row.box.code}`} subtitle={<span className="mono">{part.name}</span>}
      onClose={onClose} busy={busy} error={error} onSubmit={submit} submitLabel="Move"
      disabled={!qty || to == null || company == null}>
      <FieldRow>
        <Field label="Pieces"><NumberInput className="text num-input" value={qty} min={1} onChange={setQty} onEmpty={() => setQty(null)} /></Field>
        <CompanyOfBox part={part} value={company} onChange={setCompany} />
      </FieldRow>
      <Field label="To box">
        <select className="text" value={to ?? ""} onChange={(e) => setTo(Number(e.target.value))}>
          <option value="" disabled>Choose…</option>
          {targets.map((b) => (
            <option key={b.id} value={b.id}>
              {b.organizer} / {b.code}{b.parts.some((p) => p.qty > 0) ? ` (${b.parts.map((p) => p.name).join(", ")})` : " (empty)"}
            </option>
          ))}
        </select>
      </Field>
    </Modal>
  );
}

/** A new organizer is its boxes: a prefix and a range, as they are printed. */
function AddOrganizerDialog({ onClose, onDone }: {
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const [name, setName] = useState("");
  const [prefix, setPrefix] = useState("");
  const [from, setFrom] = useState<number | null>(1);
  const [to, setTo] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const codes = useMemo(() => {
    if (from == null || to == null || to < from || to - from > 2000) return [];
    return Array.from({ length: to - from + 1 }, (_, i) => `${prefix.trim()}${from + i}`);
  }, [prefix, from, to]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await addOrganizerBoxes(name.trim(), codes);
      onDone(`Added ${res.made.length} boxes to ${name.trim()}.`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Modal title="Add an organizer" onClose={onClose} busy={busy} error={error} onSubmit={submit}
      submitLabel={codes.length ? `Add ${codes.length} boxes` : "Add"} disabled={!name.trim() || !codes.length}
      subtitle="To add boxes to an organizer, use its name again. A box that exists stays as it is.">
      <Field label="Organizer"><input className="text" value={name} maxLength={60} autoFocus onChange={(e) => setName(e.target.value)} /></Field>
      <FieldRow>
        <Field label="Printed prefix" hint="C for C1, C2 and so on. Can be empty."><input className="text num-input" value={prefix} maxLength={20} onChange={(e) => setPrefix(e.target.value)} /></Field>
        <Field label="First number"><NumberInput className="text num-input" value={from} min={0} onChange={setFrom} onEmpty={() => setFrom(null)} /></Field>
        <Field label="Last number"><NumberInput className="text num-input" value={to} min={0} onChange={setTo} onEmpty={() => setTo(null)} /></Field>
      </FieldRow>
      {codes.length ? <p className="muted dim mono">{codes[0]} … {codes[codes.length - 1]}</p> : null}
    </Modal>
  );
}

type UsePurpose = "research" | "external" | "loss";

const USE_PURPOSES: { key: UsePurpose; label: string; note: string }[] = [
  { key: "research", label: "R&D: a cost of no batch", note: "What the work is" },
  { key: "external", label: "A project the platform does not track", note: "Which project, and what for" },
  { key: "loss", label: "Lost: the pieces are gone", note: "Why they are gone" },
];

/** Pieces that left before Henry knew about them: the pool still counts them and
 *  no box holds them. Only R&D reads back on this page's list, so the notice says
 *  where the other two went. */
function NoBoxDialog({ rate, onClose, onDone }: {
  rate: number | null;
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const { companies, scope } = useAuth();
  const [part, setPart] = useState<OrganizerPartRef & { name: string } | null>(null);
  const [picking, setPicking] = useState(false);
  const [purpose, setPurpose] = useState<UsePurpose>("research");
  const [qty, setQty] = useState<number | null>(null);
  const [company, setCompany] = useState<number | null>(startCompany(scope, companies));
  const [at, setAt] = useState(today());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const noteLabel = USE_PURPOSES.find((p) => p.key === purpose)?.note;

  const submit = async () => {
    if (!part) return;
    setBusy(true);
    setError(null);
    try {
      const res = await recordOrganizerUse({
        component_id: part.component_id, mpn: part.mpn, lcsc: part.lcsc,
        qty: qty as number, company_id: company as number, purpose, at, note: note.trim(),
      });
      const value = pln(res.value_usd, rate);
      const undo = `History → Write batches can undo it (batch ${res.batch_id}).`;
      onDone(
        purpose === "research" ? `Recorded ${qty} of ${part.name} for R&D, at ${value}. ${undo}`
        : purpose === "external" ? `Recorded ${qty} of ${part.name} for a project outside the platform, at ${value}. The list here shows R&D only: this draw is in the part's ledger on Stock → Parts. ${undo}`
        : `Wrote off ${qty} of ${part.name}, at ${value}. The list here shows R&D only: this loss is under Stock adjustments on Stock → Parts. ${undo}`,
      );
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Modal title="Pieces in no box" subtitle="The stock records still count these pieces. To take from a box, use Take on its row."
      onClose={onClose} busy={busy} error={error} onSubmit={submit}
      submitLabel={purpose === "loss" ? "Write off" : "Record"}
      disabled={!part || !qty || company == null || !note.trim()}>
      <Field label="Part">
        <button type="button" className="btn" onClick={() => setPicking(true)}>
          {part ? part.name : "Choose the part…"}
        </button>
      </Field>
      <Field label="What happened to them">
        <select className="text" value={purpose} onChange={(e) => setPurpose(e.target.value as UsePurpose)}>
          {USE_PURPOSES.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
        </select>
      </Field>
      <FieldRow>
        <Field label="Pieces"><NumberInput className="text num-input" value={qty} min={1} onChange={setQty} onEmpty={() => setQty(null)} /></Field>
        {companies.length > 1 ? (
          <Field label="Company">
            <select className="text" value={company ?? ""} onChange={(e) => setCompany(Number(e.target.value))}>
              <option value="" disabled>Choose…</option>
              {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
        ) : null}
        <Field label="Date"><input className="text" type="date" value={at} onChange={(e) => setAt(e.target.value)} /></Field>
      </FieldRow>
      <Field label={noteLabel}>
        <input className="text" value={note} maxLength={400} onChange={(e) => setNote(e.target.value)} />
      </Field>
      {picking ? (
        <ComponentPickDialog
          line={{ kind: "Pieces in no box", mpn: part?.mpn, component_id: part?.component_id }}
          title="Which part?"
          confirmLabel="Choose"
          allowFreeText
          onClose={() => setPicking(false)}
          onPick={(componentId, mpn) => setPart({
            component_id: componentId, mpn, name: mpn || `component ${componentId}`,
          })}
        />
      ) : null}
    </Modal>
  );
}

const IMPORT_PLACEHOLDER = [
  "A;A1;ESP32-WROOM-32D-N4;;1;7Sigma;Sheet name differs",
  "Numbered;2;;C123456;250",
  "B;B7",
].join("\n");

/** A count off a sheet. A space can only be a thousands separator. "1,000" is
 *  refused: it is 1 in one locale and 1000 in another, and a preview line with a
 *  plausible number is easy to miss. */
function readPieces(cell: string): number | null {
  const s = cell.replace(/\s/g, "");
  return /^\d+([.,]\d{1,2})?$/.test(s) ? Number(s.replace(",", ".")) : null;
}

/** The rows of a paste, or an Error that names the line. The server answers for the
 *  parts. This answers for what only the paste can say: the columns, the count and
 *  the company's name. */
function parseImportRows(text: string, companies: CompanyRef[], fallback: number | null): OrganizerImportRow[] {
  const rows: OrganizerImportRow[] = [];
  text.split(/\r?\n/).forEach((line, i) => {
    if (!line.trim()) return;
    const where = `Line ${i + 1}`;
    const cells = line.split(line.includes("\t") ? "\t" : ";").map((c) => c.trim());
    const [organizer = "", code = "", mpn = "", lcsc = "", pieces = "", who = "", note = ""] = cells;
    if (cells.slice(7).some(Boolean)) throw new Error(`${where}: a row has 7 columns, and this one has ${cells.length}.`);
    if (!rows.length && organizer.toLowerCase() === "organizer") return; // a header copied with the rows
    if (!organizer || !code) throw new Error(`${where}: a row starts with the organizer and the box code.`);
    if (!mpn && !lcsc) {
      if (pieces && readPieces(pieces) !== 0) throw new Error(`${where}: ${pieces} pieces, and no MPN or LCSC code names them.`);
      rows.push({ organizer, code });
      return;
    }
    const qty = readPieces(pieces);
    if (qty === null) {
      throw new Error(`${where}: "${pieces}" is not a number of pieces. Write 0 for a part used up, with no thousands separator.`);
    }
    const named = companies.find((c) => [c.name.toLowerCase(), c.key.toLowerCase()].includes(who.toLowerCase()));
    if (who && !named) throw new Error(`${where}: no company named ${who}. Use ${companies.map((c) => c.name).join(" or ")}.`);
    const company_id = named?.id ?? fallback;
    if (company_id == null) throw new Error(`${where}: name the company in the row, or choose one above the list.`);
    rows.push({ organizer, code, mpn, lcsc, qty, company_id, note });
  });
  if (!rows.length) throw new Error("Paste at least one row.");
  return rows;
}

const PLAN_WORD = (r: OrganizerImportPlanRow) => (
  r.status === "written" ? (r.new_box ? "new box, writes" : "writes")
  : r.status === "already_imported" ? "already in"
  : r.new_box ? "new empty box" : "box exists");

/** The dry run's answer, row by row. */
function ImportPlan({ plan, companies }: { plan: OrganizerImportResult; companies: CompanyRef[] }) {
  const { totals } = plan;
  const outside = plan.rows.filter((r) => r.part && !r.in_library).length;
  const number = (v: number | undefined) => (v === undefined ? "" : pcs(v));
  const columns: Column<OrganizerImportPlanRow>[] = [
    { key: "organizer", label: "Organizer", width: 10, get: (r) => r.organizer },
    { key: "code", label: "Box", width: 8, className: "mono", get: (r) => r.code, sortValue: (r) => natural(r.code) },
    { key: "part", label: "Part", width: 20, className: "mono", get: (r) => r.part ?? "",
      title: (r) => (r.part ? `${r.part}${r.in_library ? "" : ": not in the library"}` : undefined) },
    { key: "company", label: "Company", width: 8,
      get: (r) => companies.find((c) => c.id === r.company_id)?.name ?? "" },
    { key: "qty", label: "Pieces", width: 8, numeric: true, get: (r) => number(r.qty) },
    { key: "pool", label: "Pool", width: 7, numeric: true, interactive: false, get: (r) => number(r.pool_before),
      title: () => "What the stock records hold of this part, before this row" },
    { key: "jlc", label: "JLC", width: 7, numeric: true, interactive: false, get: (r) => number(r.jlc),
      title: () => "What JLC's count holds of this part" },
    { key: "free", label: "Free", width: 7, numeric: true, interactive: false, get: (r) => number(r.free_before),
      title: () => "Pieces the stock records hold that are neither at JLC nor in a box, before this row" },
    { key: "zero", label: "At zero", width: 10, numeric: true, interactive: false, sortable: true,
      get: (r) => (r.found_at_zero ? pcs(r.found_at_zero) : ""),
      title: () => "Pieces no purchase covers: they enter stock at zero value" },
    { key: "what", label: "Result", width: 15, get: PLAN_WORD },
  ];
  return (
    <FoldSection bare title="Rows" count={plan.rows.length} foldKey="organizers:import"
      chips={(
        <>
          {totals.found_rows ? <StatChip n={totals.found_rows} tone="warn">enter at zero value</StatChip> : null}
          {totals.boxes_made ? <StatChip n={totals.boxes_made}>new boxes</StatChip> : null}
          {totals.already_imported ? <StatChip n={totals.already_imported}>already in</StatChip> : null}
          {outside ? <StatChip n={outside} title="The library knows no component by this name or LCSC code">not in the library</StatChip> : null}
        </>
      )}>
      <DataTable columns={columns} rows={plan.rows} rowKey={(r) => plan.rows.indexOf(r)} />
    </FoldSection>
  );
}

/** Boxes and their contents from a list, as a sheet copies them. Preview runs the
 *  whole write and rolls it back, so its answer is the answer the write will give. */
function ImportDialog({ onClose, onDone }: {
  onClose: () => void;
  onDone: (message: string) => void;
}) {
  const { companies, scope } = useAuth();
  const [text, setText] = useState("");
  const [company, setCompany] = useState<number | null>(startCompany(scope, companies));
  const [at, setAt] = useState(today());
  const [source, setSource] = useState("");
  const applied = useRef<OrganizerImportResult | null>(null);

  return (
    <DryRunDialog<OrganizerImportResult>
      wide
      title="Load a list of boxes"
      intro="Preview writes nothing. Apply is one write, and History → Write batches can undo all of it. A row that is already in stays as it is, so a second run writes only what is new."
      onClose={(changed) => {
        const r = applied.current;
        if (!changed || !r) { onClose(); return; }
        const { written, pieces, boxes_made: boxes, found_pieces: found } = r.totals;
        onDone(
          (written ? `Loaded ${plural(written, "row")} with ${pcs(pieces).toLocaleString()} pieces. ` : "") +
          (boxes ? `Made ${plural(boxes, "box", "boxes")}. ` : "") +
          (found ? `${pcs(found).toLocaleString()} pieces entered stock at zero value. ` : "") +
          `History → Write batches can undo all of it (batch ${r.batch_id}).`,
        );
      }}
      run={async (dry) => {
        const r = await importOrganizers({
          rows: parseImportRows(text, companies, company), at, source_ref: source.trim(), dry_run: dry,
        });
        if (!dry) applied.current = r;
        return r;
      }}
      canApply={(p) => p.totals.written + p.totals.boxes_made > 0}
      applyLabel={(p) => (p.totals.written ? `Load ${plural(p.totals.written, "row")}`
        : p.totals.boxes_made ? `Make ${plural(p.totals.boxes_made, "box", "boxes")}` : "Apply")}
      describe={(p) => (p.totals.written + p.totals.boxes_made === 0
        ? <>Nothing to write. Each box and each row is already in.</>
        : (
          <>
            {p.totals.written ? (
              <>Writes <b>{plural(p.totals.written, "row")}</b> with <b>{pcs(p.totals.pieces).toLocaleString()} pieces</b>. </>
            ) : null}
            {p.totals.boxes_made ? <>Makes <b>{plural(p.totals.boxes_made, "box", "boxes")}</b>.</> : null}
            {p.totals.already_imported ? ` ${plural(p.totals.already_imported, "row")} already in.` : ""}
            {p.totals.found_rows ? (
              <> No purchase covers <b>{pcs(p.totals.found_pieces).toLocaleString()} pieces</b> on{" "}
                {plural(p.totals.found_rows, "row")}: they enter stock at zero value.</>
            ) : null}
          </>
        ))}
      detail={(p) => <ImportPlan plan={p} companies={companies} />}
      fields={(
        <FieldGrid>
          <Field label="Rows" wide
            hint="One row per line, columns split by a tab (a copy from a sheet) or a semicolon: organizer, box code, MPN, LCSC code, pieces, company, note. A row with no part makes an empty box. A first line that starts with “organizer” is a header.">
            <AutoTextarea className="text mono" rows={6} value={text} placeholder={IMPORT_PLACEHOLDER} spellCheck={false}
              onChange={(e) => setText(e.target.value)} />
          </Field>
          {companies.length > 1 ? (
            <Field label="Company of a row that names none">
              <select className="text" value={company ?? ""} onChange={(e) => setCompany(Number(e.target.value))}>
                <option value="" disabled>Choose…</option>
                {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
          ) : null}
          <Field label="Date of the list" hint="It dates each row: the day the boxes were counted.">
            <input className="text" type="date" value={at} onChange={(e) => setAt(e.target.value)} />
          </Field>
          <Field label="Where it comes from (optional)">
            <input className="text" value={source} maxLength={100} onChange={(e) => setSource(e.target.value)} />
          </Field>
        </FieldGrid>
      )}
    />
  );
}
