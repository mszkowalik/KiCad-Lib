/** Which company owned this project, and when (decision 0063).
 *
 *  Ownership is a list of periods, never one field: a move starts a new period
 *  on a date and keeps the old one, so a 2024 invoice still reads as the
 *  company that owned the project in 2024. Moving is admin work, because it
 *  changes what the books of two companies say.
 */
import { useState } from "react";
import { errorMessage, moveProject, type OwnershipPeriod, type ProjectInfo } from "../../api";
import { useAuth } from "../../auth";
import Field, { FieldGrid } from "../Field";
import DataTable, { type Column } from "../DataTable";

const COLUMNS: Column<OwnershipPeriod>[] = [
  { key: "company", label: "Company", width: 22, get: (o) => o.company ?? "" },
  { key: "from", label: "From", width: 14, className: "mono", get: (o) => o.from_date },
  { key: "until", label: "Until", width: 14, className: "mono", get: (o) => o.to_date ?? "now" },
  { key: "note", label: "Note", width: 36, get: (o) => o.note },
  { key: "by", label: "By", width: 14, get: (o) => o.created_by },
];

export default function OwnershipCard({
  project,
  onMoved,
}: {
  project: ProjectInfo;
  onMoved: () => void;
}) {
  const { companies, isAdmin } = useAuth();
  const [open, setOpen] = useState(false);
  const [companyId, setCompanyId] = useState<number | "">("");
  const [fromDate, setFromDate] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const others = companies.filter((c) => c.id !== project.company_id);

  const submit = async () => {
    if (companyId === "" || !fromDate) return;
    setBusy(true);
    setErr("");
    try {
      await moveProject(project.id, { company_id: companyId, from_date: fromDate, note });
      setOpen(false);
      setCompanyId("");
      setFromDate("");
      setNote("");
      onMoved();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card pad">
      <div className="card-title">Owner</div>
      <p className="muted dim">
        The company that owns the project on a date. Its new batches and orders default to that company.
      </p>
      <DataTable
        rows={project.ownership}
        rowKey={(o) => o.id}
        columns={COLUMNS}
        empty="No owner recorded."
        defaultSort={{ key: "from", dir: "desc" }}
      />
      {isAdmin && !open ? (
        <div className="btn-row">
          <button type="button" className="btn btn-sm" disabled={!others.length} onClick={() => setOpen(true)}>
            Move to another company…
          </button>
        </div>
      ) : null}
      {isAdmin && open ? (
        <>
          <FieldGrid>
            <Field label="New owner">
              <select
                className="text"
                value={companyId}
                onChange={(e) => setCompanyId(e.target.value === "" ? "" : Number(e.target.value))}
              >
                <option value="">—</option>
                {others.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </Field>
            <Field label="From" hint="The first day the new company owns it. Earlier batches and orders keep their company.">
              <input className="text" type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
            </Field>
            <Field label="Note" wide>
              <input className="text" value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
          </FieldGrid>
          {err ? <div className="banner-error">{err}</div> : null}
          <div className="btn-row">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={busy || companyId === "" || !fromDate}
              onClick={() => void submit()}
            >
              {busy ? "Moving…" : "Move"}
            </button>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
