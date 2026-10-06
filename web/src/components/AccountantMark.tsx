/** Whether the accountant has one document, and the control that records it
 *  (decision 0079). A KSeF document is hers without a click; a document
 *  nobody pays for needs no sending. */
import { useState } from "react";
import { errorMessage, markAccountant, type AccountantState } from "../api";
import { useDialog } from "./Dialog";

const VIA_TEXT: Record<string, string> = {
  ksef: "from KSeF", kpir: "booked in the KPiR", mail: "by mail", manual: "marked by hand", history: "issued elsewhere",
};

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
  const send = async (sentAt: string) => {
    if (!companyId) return;
    setBusy(true);
    try {
      await markAccountant(companyId, {
        ...(kind === "document" ? { document_ids: [id] } : { sales_invoice_ids: [id] }), sent_at: sentAt, via: "manual",
      });
      onChange();
    } catch (e) {
      await dialog.alert(errorMessage(e), { title: "Not recorded" });
    } finally {
      setBusy(false);
    }
  };
  const text = state.sent
    ? `Accountant has it: ${VIA_TEXT[state.via] ?? state.via}${state.at ? `, ${state.at}` : ""}`
    : state.ignored ? "Accountant: nothing to send" : "Accountant: not sent yet";
  return (
    <>
      <span className={`pill ${state.sent ? "ok" : state.ignored ? "neutral" : "warn"}`} title={state.ref || undefined}>{text}</span>
      {!state.sent && !state.ignored && companyId ? (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={async () => {
          const day = await dialog.prompt("Sent to the accountant on (YYYY-MM-DD):", {
            title: "Mark as sent", initial: new Date().toISOString().slice(0, 10),
          });
          if (day) await send(day);
        }}>Mark sent…</button>
      ) : null}
      {state.sent && state.via !== "ksef" && companyId ? (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={async () => {
          if (await dialog.confirm("Clear the record that the accountant has this document?", { title: "Not sent", confirmLabel: "Clear" })) {
            await send("");
          }
        }}>Not sent</button>
      ) : null}
    </>
  );
}
