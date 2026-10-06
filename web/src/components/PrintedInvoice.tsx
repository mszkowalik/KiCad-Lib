/** An invoice AS PRINTED, in the KSeF (FA(3)) structure — seller, buyer, the
 *  positions with their VAT rates, and the totals per rate (decision 0084).
 *
 *  A sales invoice and a supplier document keep the same `body`, so both pages
 *  draw its positions with `INVOICE_LINE_COLUMNS`. On a supplier document the
 *  body is what the supplier's own data said — KSeF's XML, or a transcription
 *  of the document's original file (decision 0085) — and is never edited in
 *  the UI; the cost positions under it are what the platform computes with.
 */
import { useState } from "react";
import type { PrintedSource, SalesInvoiceBody, SalesLine } from "../api";
import DataTable, { type Column } from "./DataTable";

/** An amount as the Polish invoice prints it: two decimals, Polish separators. */
export function pl(amount: string | number | null | undefined): string {
  const n = Number(amount ?? 0);
  return n.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export const INVOICE_LINE_COLUMNS: Column<SalesLine>[] = [
  { key: "pos", label: "Lp.", width: 7, numeric: true, get: (l) => l.position ?? 0 },
  { key: "name", label: "Name", width: 37, get: (l) => l.name },
  { key: "qty", label: "Qty", width: 8, numeric: true, get: (l) => Number(l.qty) },
  { key: "unit", label: "Unit", width: 6, get: (l) => l.unit },
  { key: "unit_net", label: "Unit net", width: 11, numeric: true, get: (l) => Number(l.unit_net),
    render: (l) => <>{pl(l.unit_net)}</> },
  { key: "net", label: "Net", width: 11, numeric: true, get: (l) => Number(l.net ?? 0), render: (l) => <>{pl(l.net)}</> },
  { key: "rate", label: "VAT", width: 7, get: (l) => l.vat_rate },
  { key: "gross", label: "Gross", width: 13, numeric: true, get: (l) => Number(l.gross ?? 0),
    render: (l) => <>{pl(l.gross)}</> },
];

/** Where the page was read from, in words. */
function sourceText(s: PrintedSource | undefined): string {
  if (!s) return "";
  if (s.kind === "ksef") return `Read from KSeF ${s.ksef_number}.`;
  return `Read from ${s.filename} by ${s.actor || "someone"} on ${s.read_on}.`;
}

/** The printed invoice behind a button: the cost positions are what a reader
 *  of a supplier document usually came for, the printed page is the evidence. */
export default function PrintedInvoice({ body, currency }: {
  body: SalesInvoiceBody & { source?: PrintedSource };
  currency: string;
}) {
  const [open, setOpen] = useState(false);
  const t = body.totals;
  return (
    <>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={() => setOpen(!open)}>
          {open ? "▾" : "▸"} Printed invoice ({body.lines.length} positions)
        </button>
      </div>
      {open ? (
        <>
          {body.source?.kind === "file" && body.source.problems.length ? (
            <div className="banner-warn">
              The page does not agree with the document: {body.source.problems.map((p) => p.text).join("; ")}.
              {" "}Reason given: {body.source.reason}
            </div>
          ) : null}
          <p className="muted dim">{sourceText(body.source)}</p>
          <p className="muted">
            Seller {body.seller.name} · NIP {body.seller.nip || "—"}
            {" · "}Buyer {body.buyer.name} · NIP {body.buyer.nip || "—"}
          </p>
          <DataTable rows={body.lines} rowKey={(l) => `p${l.position}`} columns={INVOICE_LINE_COLUMNS}
                     empty="No positions." />
          <p className="muted">
            {Object.entries(t.rates || {}).map(([rate, r]) => (
              <span key={rate}>
                {rate}: net {pl(r.net)}, VAT {pl(r.vat)}
                {r.vat_pln != null ? ` (${pl(r.vat_pln)} PLN)` : ""}
                {" · "}
              </span>
            ))}
            Gross {pl(t.gross)} {currency}
          </p>
        </>
      ) : null}
    </>
  );
}
