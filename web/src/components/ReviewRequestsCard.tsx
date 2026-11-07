/** What was handed to the agent with "Queue shown → agent", and the way to take
 *  it back. The queue shows only that a row is handed off; this is the list. */
import { useCallback, useEffect, useState } from "react";
import {
  errorMessage,
  isAbortError,
  listReviewRequests,
  withdrawReviewRequest,
  type ReviewRequestRow,
} from "../api";
import DataTable from "./DataTable";
import { useDialog } from "./Dialog";
import FoldSection, { StatChip } from "./FoldSection";
import { localWhen } from "../format";
import { ErrorBanner } from "./Ui";

export default function ReviewRequestsCard() {
  const dialog = useDialog();
  const [rows, setRows] = useState<ReviewRequestRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback((signal?: AbortSignal) => {
    listReviewRequests(false, signal)
      .then((r) => { setRows(r); setError(null); })
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
  }, []);
  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  if (error) return <ErrorBanner message={error} />;
  // Nothing handed off is nothing to say.
  if (!rows?.length) return null;
  const withdraw = async (r: ReviewRequestRow) => {
    const ok = await dialog.confirm(`Take ${r.name} back from the agent?`, { title: "Withdraw request", confirmLabel: "Withdraw" });
    if (!ok) return;
    try {
      await withdrawReviewRequest(r.id);
      load();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not withdraw" });
    }
  };
  const count = (kind: string) => rows.filter((r) => r.kind === kind).length;
  return (
    <FoldSection title="Handed to the agent" count={rows.length} limit={0} foldKey="reviews:requests"
      chips={<>
        {count("component") ? <StatChip n={count("component")}>components</StatChip> : null}
        {count("symbol") ? <StatChip n={count("symbol")}>symbols</StatChip> : null}
        {count("footprint") ? <StatChip n={count("footprint")}>footprints</StatChip> : null}
      </>}>
      <DataTable
        rows={rows}
        rowKey={(r) => r.id}
        columns={[
          { key: "kind", label: "Kind", width: 12, get: (r) => r.kind },
          { key: "name", label: "Name", width: 36, className: "mono", get: (r) => r.name },
          { key: "by", label: "By", width: 16, get: (r) => r.requested_by },
          { key: "at", label: "When", width: 20, get: (r) => r.requested_at, render: (r) => localWhen(r.requested_at) },
          { key: "x", label: "", width: 16, interactive: false, get: () => "",
            render: (r) => <button type="button" className="btn btn-sm" onClick={() => void withdraw(r)}>Withdraw…</button> },
        ]}
      />
    </FoldSection>
  );
}
