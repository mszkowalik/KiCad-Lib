/** Stock → JLCPCB: the order centre at JLCPCB, read live through the browser session.
 *
 *  It is read-only. The rows are JLC's own payload, close to raw, so a row opens
 *  into that payload rather than into a second mapping of it (docs/jlcpcb-web-api.md).
 *  JLC pages this list, so the search goes to the server, and the other columns offer
 *  no filter and no sort, because they could only act on one page.
 *
 *  A dead session is an answer here, not a failure: the route says 409 with its own
 *  sentence, and this panel prints that sentence. The page keeps working, because
 *  the panels above it read local data.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  errorMessage,
  getJlcWebOrderDetail,
  getJlcWebOrderInvoice,
  getJlcWebOrders,
  getJlcWebPartsInvoice,
  getJlcWebPartsOrders,
  isAbortError,
  type JlcWebBatch,
  type JlcWebPartsOrder,
  type JlcWebPartsSubOrder,
} from "../../api";
import { plain, localWhen } from "../../format";
import DataTable, { type Column } from "../DataTable";
import Field from "../Field";
import FoldSection, { StatChip } from "../FoldSection";
import TabStrip from "../TabStrip";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import JlcInvoicePdfDialog from "./JlcInvoicePdfDialog";

type Source = "assembly" | "parts";

const PAGE_SIZE = 25;

/** JLC's own words for its two lists (docs/jlcpcb-web-api.md §3.1, §3.4). */
const STATUSES: Record<Source, string[]> = {
  assembly: ["shipped", "inProduction", "cancelled", "waitPay", "waitReview"],
  parts: ["paySuccess", "waitPay", "cancelled", "completed"],
};

/** A parts sub-order's `orderStatus` (docs/jlcpcb-web-api.md §3.4). */
const SUB_ORDER_STATE: Record<number, string> = { 10: "unpaid", 20: "in progress", 30: "completed", 40: "cancelled" };

function subOrders(o: JlcWebPartsOrder): JlcWebPartsSubOrder[] {
  // All four lists: `stockList` alone drops every part JLC sourced for us.
  return [o.stockList, o.buyList, o.overseasShopList, o.idleOrderList].flatMap((l) => l ?? []);
}

function subOrderStates(o: JlcWebPartsOrder): string {
  const counts = new Map<string, number>();
  for (const s of subOrders(o)) {
    const word = SUB_ORDER_STATE[s.orderStatus ?? -1] ?? `status ${s.orderStatus ?? "?"}`;
    counts.set(word, (counts.get(word) ?? 0) + 1);
  }
  return [...counts].map(([word, n]) => `${n} ${word}`).join(" · ");
}

/** The doc names the field and not its form, so take a time in ms or a string. */
function when(v: string | number | undefined): string {
  if (v === undefined || v === null || v === "") return "—";
  if (typeof v === "number") return localWhen(new Date(v).toISOString());
  return v;
}

const ASSEMBLY_COLUMNS: Column<JlcWebBatch>[] = [
  { key: "batch", label: "Batch", width: 30, serverFilter: true, className: "mono", get: (b) => b.batchNum ?? "" },
  { key: "created", label: "Created", width: 20, interactive: false, className: "mono", get: (b) => when(b.batchCreateTime) },
  { key: "status", label: "Status", width: 18, interactive: false, get: (b) => b.batchStatus ?? "",
    render: (b) => <StatusPill status={b.batchStatus} /> },
  { key: "orders", label: "Orders", width: 12, numeric: true, interactive: false,
    get: (b) => b.payUnionSecondVO?.orderInfoVOList?.length ?? null },
  { key: "fee", label: "Total fee", width: 20, numeric: true, interactive: false,
    title: () => "JLC's totalFee. It leaves out prepaid components.",
    get: (b) => b.payUnionSecondVO?.totalFee ?? null,
    render: (b) => plain(b.payUnionSecondVO?.totalFee) },
];

const PARTS_COLUMNS: Column<JlcWebPartsOrder>[] = [
  { key: "batch", label: "Order", width: 34, serverFilter: true, className: "mono", get: (o) => o.orderBatchNo ?? "" },
  { key: "subs", label: "Sub-orders", width: 14, numeric: true, interactive: false, get: (o) => subOrders(o).length },
  { key: "lots", label: "Lots", width: 12, numeric: true, interactive: false,
    get: (o) => subOrders(o).reduce((n, s) => n + (s.presaleGoodsRecords?.length ?? 0), 0) },
  { key: "state", label: "Sub-order states", width: 40, interactive: false, get: subOrderStates },
];

type RawTab = "row" | "invoice";

/** One row's raw JLC data. It fetches only what its open tab shows, because each
 *  fetch is a call to JLC. */
function RawPanel({ source, id, row }: { source: Source; id: string; row: unknown }) {
  const [tab, setTab] = useState<RawTab>("row");
  const [data, setData] = useState<unknown>(undefined);
  const [error, setError] = useState("");

  useEffect(() => {
    setData(undefined);
    setError("");
    // A parts order has no detail route: its list row is the whole answer.
    if (tab === "row" && source === "parts") {
      setData(row);
      return undefined;
    }
    const ac = new AbortController();
    const read = tab === "invoice"
      ? (source === "assembly" ? getJlcWebOrderInvoice : getJlcWebPartsInvoice)
      : getJlcWebOrderDetail;
    read(id, ac.signal)
      .then(setData)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [tab, source, id, row]);

  return (
    <div onClick={(e) => e.stopPropagation()}>
      <TabStrip<RawTab>
        label="Raw JLC data"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "row", label: source === "assembly" ? "Order detail" : "List row" },
          { id: "invoice", label: "Invoice data" },
        ]}
      />
      <ErrorBanner message={error} />
      {data === undefined && !error ? <Spinner label="Reading JLC…" /> : null}
      {data !== undefined ? <pre className="code-block code-block-prompt">{JSON.stringify(data, null, 2)}</pre> : null}
    </div>
  );
}

export default function JlcOrdersPanel() {
  const [source, setSource] = useState<Source>("assembly");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [seq, setSeq] = useState(0);
  const [batches, setBatches] = useState<JlcWebBatch[]>([]);
  const [parts, setParts] = useState<JlcWebPartsOrder[]>([]);
  const [loading, setLoading] = useState(true);
  /** the server's sentence about the session: a 409 */
  const [session, setSession] = useState("");
  const [error, setError] = useState("");
  const [drawing, setDrawing] = useState(false);
  const typing = useRef<number | undefined>(undefined);

  useEffect(() => {
    const ac = new AbortController();
    const params = { page, page_size: PAGE_SIZE, status, search };
    setLoading(true);
    const done = () => {
      setSession("");
      setError("");
      setLoading(false);
    };
    const failed = (err: unknown) => {
      if (isAbortError(err)) return;
      setBatches([]);
      setParts([]);
      setLoading(false);
      if (err instanceof ApiError && err.status === 409) {
        setSession(err.message);
        setError("");
      } else {
        setSession("");
        setError(errorMessage(err));
      }
    };
    if (source === "assembly") {
      getJlcWebOrders(params, ac.signal).then((r) => { setBatches(r.list ?? []); done(); }).catch(failed);
    } else {
      getJlcWebPartsOrders(params, ac.signal).then((r) => { setParts(r.list ?? []); done(); }).catch(failed);
    }
    return () => ac.abort();
  }, [source, page, status, search, seq]);

  useEffect(() => () => window.clearTimeout(typing.current), []);

  const shown = source === "assembly" ? batches.length : parts.length;
  const chips = useMemo(() => {
    if (session) return <StatChip tone="warn">session not usable</StatChip>;
    if (source !== "assembly") return null;
    const counts = new Map<string, number>();
    for (const b of batches) counts.set(b.batchStatus ?? "?", (counts.get(b.batchStatus ?? "?") ?? 0) + 1);
    return <>{[...counts].slice(0, 4).map(([word, n]) => <StatChip key={word} n={n}>{word}</StatChip>)}</>;
  }, [session, source, batches]);

  const typed = (f: Record<string, string>) => {
    window.clearTimeout(typing.current);
    typing.current = window.setTimeout(() => {
      setPage(1);
      setSearch((f.batch ?? "").trim());
    }, 300);
  };

  return (
    <>
      <FoldSection
        title="Orders at JLCPCB"
        count={shown}
        chips={chips}
        foldKey="jlc-live-orders"
        actions={
          <>
            <button type="button" className="btn btn-sm" disabled={loading} onClick={() => setSeq((n) => n + 1)}>
              {loading ? "Reading…" : "Read again"}
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setDrawing(true)}>
              Draw invoice PDFs…
            </button>
          </>
        }
      >
        <p className="muted dim">
          These lists come from JLCPCB when you open this page. Nothing here writes to the platform. Open a row to
          see JLC&rsquo;s raw data.
        </p>
        {session ? (
          <>
            <div className="banner-warn">{session}</div>
            <p className="muted dim">
              Use the session box at the top of this page to log in again. This list reads JLC again after that.
            </p>
          </>
        ) : null}
        <ErrorBanner message={error} />
        <TabStrip<Source>
          label="Which JLC orders"
          value={source}
          onChange={(s) => {
            setSource(s);
            setPage(1);
            setStatus("");
            setSearch("");
          }}
          tabs={[
            { id: "assembly", label: "Assembly orders" },
            { id: "parts", label: "Parts orders" },
          ]}
        />
        <div className="btn-row">
          <Field label="Status">
            <select
              className="row-input"
              value={status}
              onChange={(e) => {
                setPage(1);
                setStatus(e.target.value);
              }}
            >
              <option value="">every status</option>
              {STATUSES[source].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>
        </div>
        {loading && !shown ? <Spinner label="Reading JLC…" /> : null}
        {source === "assembly" ? (
          <DataTable<JlcWebBatch>
            key="assembly"
            rows={batches}
            rowKey={(b) => b.batchNum ?? JSON.stringify(b).slice(0, 80)}
            columns={ASSEMBLY_COLUMNS}
            empty={session ? "JLC did not answer." : "No orders."}
            onServerFilters={typed}
            expand={(b) => <RawPanel source="assembly" id={b.batchNum ?? ""} row={b} />}
          />
        ) : (
          <DataTable<JlcWebPartsOrder>
            key="parts"
            rows={parts}
            rowKey={(o) => o.orderBatchNo ?? JSON.stringify(o).slice(0, 80)}
            columns={PARTS_COLUMNS}
            empty={session ? "JLC did not answer." : "No orders."}
            onServerFilters={typed}
            expand={(o) => <RawPanel source="parts" id={o.orderBatchNo ?? ""} row={o} />}
          />
        )}
        <div className="btn-row">
          <button type="button" className="btn btn-sm" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
            Previous
          </button>
          <span className="muted">Page {page}</span>
          <button
            type="button"
            className="btn btn-sm"
            disabled={shown < PAGE_SIZE || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      </FoldSection>
      {drawing ? <JlcInvoicePdfDialog onClose={() => setDrawing(false)} /> : null}
    </>
  );
}
