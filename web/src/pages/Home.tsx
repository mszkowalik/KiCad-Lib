/** Home (decision 0103): what is going on, and what waits for a person.
 *
 *  Batches in work come first, each with its mini board and what can go now.
 *  "Waiting" lists what needs an action, and each line links to the page that
 *  does it. Each source loads on its own, so a slow or refused one (the review
 *  queue takes about a second) never holds the others back. A figure stays on its
 *  own page: this page only says that something is there.
 *
 *  A line is drawn only when its count is above 0. The sales lines use the same
 *  test as the list they open (`salesInvoiceState`, `shippedNotInvoiced`), so a
 *  count opens exactly that many rows. Each plan adds its own lines (decision
 *  0107 item 21), and each opens the plan.
 */
import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  getAllRuns,
  getInvoiceRegister,
  getKsefInbox,
  getPlansAttention,
  getReviewQueue,
  listOrders,
  listSalesInvoices,
  listShipments,
  type PlanAttention,
  type RunInfo,
} from "../api";
import { useAuth } from "../auth";
import { StatChip, type ChipTone } from "../components/FoldSection";
import { MiniBoard, nextUp } from "../components/process/ProcessBoard";
import { Spinner, salesInvoiceState, shippedNotInvoiced, waitsForReview } from "../components/Ui";
import { pln } from "../format";
import { useTodayRate } from "../useTodayRate";
import { useLoad } from "../components/useLoad";
import PageShell from "../components/PageShell";

interface Waiting {
  n: ReactNode;
  tone?: ChipTone;
  text: string;
  /** Whose line it is, printed muted after the text: a plan's name. */
  sub?: string;
  to: string;
}

/** One plan's lines: what blocks it and what waits for a person this week. */
function planLines(p: PlanAttention): Waiting[] {
  const to = `/sales/plans/${p.plan_id}`;
  const sub = `plan ${p.name}`;
  if (p.error) return [{ n: "!", tone: "err", text: `the plan could not be computed: ${p.error}`, sub, to }];
  const out: Waiting[] = [];
  const add = (n: number | undefined, tone: ChipTone, text: string) => {
    if (n) out.push({ n, tone, text, sub, to });
  };
  add(p.counts.block, "err", "problems block the plan");
  add(p.purchases_this_week, "warn", "purchases to place this week");
  add(p.late_advances, "err", "advances are not paid by their due date");
  add(p.conflicts, "err", "dates are in conflict");
  add(p.shortages, "warn", "parts are short");
  add(p.broken_reservations, "warn", "reservations fell short");
  add(p.public_only, "warn", "parts have only JLC public stock, which nobody reserves");
  return out;
}

export default function Home() {
  const rate = useTodayRate();
  const { user } = useAuth();
  const runs = useLoad(getAllRuns, []).data;
  const reviews = useLoad((s) => getReviewQueue(s), []).data;
  const shipments = useLoad((s) => listShipments("open", s), []).data;
  const ksef = useLoad(getKsefInbox, []).data;
  const orders = useLoad((s) => listOrders(s), []).data;
  const register = useLoad(getInvoiceRegister, []).data;
  const salesInvoices = useLoad(listSalesInvoices, []).data;
  const plans = useLoad(getPlansAttention, []).data;

  const inWork: RunInfo[] = (runs ?? []).filter((r) => r.process_board);
  const waiting: Waiting[] = [];
  if (reviews) {
    // The same test as the queue's badge and its default filter, so the link
    // opens a list of exactly this many rows.
    const n = reviews.components.filter((c) => waitsForReview(c.review_state)).length;
    if (n) waiting.push({ n, tone: "warn", text: "components wait for a review", to: "/reviews" });
  }
  if (shipments?.length) waiting.push({ n: shipments.length, text: "shipments are open, not sent", to: "/sales/shipments" });
  if (salesInvoices) {
    const n = salesInvoices.filter((r) => salesInvoiceState(r) === "overdue").length;
    if (n) waiting.push({ n, tone: "err", text: "sales invoices are past their due date and not paid", to: "/sales/invoices?state=overdue" });
  }
  if (orders) {
    const open = orders.filter((o) => o.status === "open" || o.status === "partial");
    if (open.length) waiting.push({ n: open.length, text: "orders are not fully shipped", to: "/sales/orders" });
    const n = orders.filter(shippedNotInvoiced).length;
    if (n) waiting.push({ n, tone: "warn", text: "orders shipped units that are not invoiced", to: "/sales/orders?narrow=uninvoiced" });
  }
  for (const p of plans ?? []) waiting.push(...planLines(p));
  if (ksef) {
    const n = ksef.filter((k) => k.status === "new").length;
    if (n) waiting.push({ n, tone: "warn", text: "KSeF purchases wait for an import", to: "/finance/ksef" });
  }
  if (register?.issues.unassigned.length) {
    const usdTotal = register.issues.unassigned.reduce((a, u) => a + (u.amount_usd ?? 0), 0);
    waiting.push({ n: pln(usdTotal, rate, 0), tone: "warn", text: `not assigned to anything, on ${register.issues.unassigned.length} documents`, to: "/finance/invoices" });
  }
  for (const r of inWork) {
    for (const s of r.process_board ?? []) {
      if (s.state === "short" || s.state === "blocked") {
        const part = s.inputs.find((i) => i.covers !== null && i.covers < s.still_to_do);
        if (part) {
          waiting.push({
            n: (s.still_to_do - (part.covers ?? 0)).toLocaleString(), tone: "warn",
            text: `short of ${part.name} for ${r.label}, ${s.label}`, to: `/stock?q=${encodeURIComponent(part.name)}`,
          });
        }
      }
    }
  }
  const loading = !runs || !reviews || !shipments || !orders || !ksef || !register || !salesInvoices || !plans;

  return (
    <PageShell>
      <div className="toolbar">
        <h1>Home</h1>
        {user ? <span className="toolbar-total">{user.display_name || user.username}</span> : null}
      </div>

      <div className="card pad">
        <h2 className="card-title">Batches in work</h2>
        {!runs ? <Spinner /> : inWork.length ? (
          <div className="attention-rows">
            {inWork.map((r) => {
              const up = nextUp(r.process_board ?? []);
              return (
                <div key={r.id} className="attention-row">
                  <span>
                    <Link className="comp-link" to={`/production/batches/${r.id}`}>{r.label}</Link>{" "}
                    <span className="muted">{r.project}</span>
                  </span>
                  <span className="stat-row">
                    <MiniBoard steps={r.process_board ?? []} />
                    {up ? <StatChip n={up.can_go.toLocaleString()} tone="acc">can go at {up.label}</StatChip> : <span className="muted">nothing can go now</span>}
                  </span>
                </div>
              );
            })}
          </div>
        ) : <p className="muted">No batch is in work. A batch starts from its project.</p>}
      </div>

      <div className="card pad">
        <h2 className="card-title">Waiting</h2>
        <div className="attention-rows">
          {waiting.map((w) => (
            <div key={`${w.text}|${w.sub ?? ""}`} className="attention-row">
              <span>
                <StatChip n={w.n} tone={w.tone} /> {w.text}
                {w.sub ? <span className="muted"> · {w.sub}</span> : null}
              </span>
              <Link className="btn btn-sm" to={w.to}>Open</Link>
            </div>
          ))}
        </div>
        {loading ? <Spinner /> : waiting.length ? null : <p className="muted">Nothing waits.</p>}
      </div>
    </PageShell>
  );
}
