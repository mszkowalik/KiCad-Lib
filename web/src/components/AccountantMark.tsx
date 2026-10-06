/** Whether the accountant has one document, and the controls that record it
 *  (decisions 0079, 0080). A KSeF document is hers without a click; a proforma
 *  or a transfer needs no sending; and a document the user decided she will
 *  never get is "not for the accountant", with the reason. */
import { useState } from "react";
import { errorMessage, markAccountant, type AccountantState } from "../api";
import { useDialog, type DialogApi } from "./Dialog";

const VIA_TEXT: Record<string, string> = {
  ksef: "from KSeF", kpir: "booked in the KPiR", mail: "by mail", manual: "marked by hand", history: "issued elsewhere",
};

/** Ask why the accountant will not get these documents. Empty means cancelled. */
export async function askNotSentReason(dialog: DialogApi, count = 1): Promise<string> {
  const reason = await dialog.prompt(
    `Why will the accountant not get ${count === 1 ? "this document" : `these ${count} documents`}? `
      + "For example: lost, private, too late.",
    { title: "Not for the accountant", initial: "too late", maxLength: 200 },
  );
  return (reason ?? "").trim();
}

export default function AccountantMark({ companyId, kind, id, state, onChange }: {
  companyId: number | null | undefined;
  kind: "document" | "sales_invoice";
  id: number;
  state: AccountantState | undefined;
  onChange: () => void;
}) {
  const dialog = useDialog();
  const [busy, setBusy] = useState(false);
  if (!state) return null;
  const record = async (sentAt: string, via = "manual", ref = "") => {
    if (!companyId) return;
    setBusy(true);
    try {
      await markAccountant(companyId, {
        ...(kind === "document" ? { document_ids: [id] } : { sales_invoice_ids: [id] }), sent_at: sentAt, via, ref,
      });
      onChange();
    } catch (e) {
      await dialog.alert(errorMessage(e), { title: "Not recorded" });
    } finally {
      setBusy(false);
    }
  };
  const notSent = state.via === "not_sent";
  const text = state.sent
    ? `Accountant has it: ${VIA_TEXT[state.via] ?? state.via}${state.at ? `, ${state.at}` : ""}`
    : notSent ? `Not for the accountant: ${state.ref}`
      : state.ignored ? "Accountant: nothing to send" : "Accountant: not sent yet";
  const open = !state.sent && !state.ignored && companyId;
  return (
    <>
      <span className={`pill ${state.sent ? "ok" : state.ignored ? "neutral" : "warn"}`}
        title={notSent ? `Decided ${state.at}. Left out of the company books; batch costs keep it.` : state.ref || undefined}>
        {text}
      </span>
      {open ? (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={async () => {
          const day = await dialog.prompt("Sent to the accountant on (YYYY-MM-DD):", {
            title: "Mark as sent", initial: new Date().toISOString().slice(0, 10),
          });
          if (day) await record(day);
        }}>Mark sent…</button>
      ) : null}
      {open ? (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={async () => {
          const reason = await askNotSentReason(dialog);
          if (reason) await record(new Date().toISOString().slice(0, 10), "not_sent", reason);
        }}>Not for the accountant…</button>
      ) : null}
      {(state.sent && state.via !== "ksef" || notSent) && companyId ? (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={async () => {
          const q = notSent ? "Put this document back on the list of what to send?"
            : "Clear the record that the accountant has this document?";
          if (await dialog.confirm(q, { title: notSent ? "To send" : "Not sent", confirmLabel: "Clear" })) {
            await record("");
          }
        }}>{notSent ? "Undo" : "Not sent"}</button>
      ) : null}
    </>
  );
}
