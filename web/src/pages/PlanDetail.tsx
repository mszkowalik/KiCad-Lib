/** One plan of a customer contract (decision 0107): its blockers and timeline,
 *  its deliveries and cash, the parts it needs, the week-by-week agenda, and
 *  the setup where its orders, batches, lots and dates are written.
 *
 *  The server computes every date and figure on read, and every write answers
 *  the whole plan again, so the page replaces its state with the answer and
 *  never adds anything up itself. A write names where it is undone. */
import { useCallback, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { errorMessage, getPlan, getProjects, type ProjectInfo as ApiProject } from "../api";
import { useDialog } from "../components/Dialog";
import PageShell, { PageLoading } from "../components/PageShell";
import TabStrip from "../components/TabStrip";
import { BackLink, ErrorBanner, StatusPill } from "../components/Ui";
import { useLoad } from "../components/useLoad";
import PlanAgenda from "../components/plan/PlanAgenda";
import PlanMoney from "../components/plan/PlanMoney";
import { OrderDialog } from "../components/plan/PlanOrders";
import PlanOverview from "../components/plan/PlanOverview";
import PlanParts from "../components/plan/PlanParts";
import PlanSetup from "../components/plan/PlanSetup";
import { Declined, planProjects, type Apply, type PlanLink } from "../components/plan/planUtil";

const TABS = ["overview", "money", "parts", "agenda", "setup"] as const;
type Tab = (typeof TABS)[number];

/** One identity, because the setup cards have `projects` in their deps. */
const NO_PROJECTS: ApiProject[] = [];

export default function PlanDetail() {
  const params = useParams();
  const planId = Number(params.id);
  const [search, setSearch] = useSearchParams();
  const raw = search.get("tab") ?? "overview";
  const tab: Tab = (TABS as readonly string[]).includes(raw) ? (raw as Tab) : "overview";
  const part = tab === "parts" ? search.get("part") : null;
  const navigate = useNavigate();
  const dialog = useDialog();

  const { data: full, setData, error } = useLoad((signal) => getPlan(planId, signal), [planId], { keep: true });
  const allProjects = useLoad(getProjects, []).data ?? NO_PROJECTS;
  const [notice, setNotice] = useState<string | null>(null);
  const [orderId, setOrderId] = useState<number | null>(null);

  const go = useCallback((t: Tab, partKey?: string | null) => {
    const next: Record<string, string> = {};
    if (t !== "overview") next.tab = t;
    if (t === "parts" && partKey) next.part = partKey;
    setSearch(next, { replace: true });
  }, [setSearch]);

  const apply: Apply = useCallback(async (what, work) => {
    try {
      setData(await work());
      setNotice(what);
      return true;
    } catch (err) {
      if (err instanceof Declined) return false;
      await dialog.alert(errorMessage(err), { title: "That did not work" });
      return false;
    }
  }, [setData, dialog]);

  const onLink = useCallback((link: PlanLink) => {
    if (!link) return;
    if (link.kind === "part") go("parts", link.key);
    else if (link.kind === "parts") go("parts");
    else if (link.kind === "tab") go(link.tab);
    else navigate(link.to);
  }, [go, navigate]);

  if (!full) return <PageLoading error={error} label="Loading the plan…" />;
  const plan = full.plan;
  const s = full.schedule;
  const projects = planProjects(full);
  const short = s.parts.filter((p) => p.status === "short").length;
  const blocking = s.blockers.filter((b) => b.severity === "block").length;

  return (
    <PageShell>
      <div className="toolbar">
        <BackLink to="/sales/plans">← Plans</BackLink>
        <h1>{plan.name}</h1>
        <StatusPill status={plan.status} title={plan.status === "sent" ? `sent ${plan.sent_on}` : plan.status === "agreed" ? `agreed ${plan.agreed_on}` : "not sent to the customer"} />
        <span className="toolbar-total">
          {[plan.customer || "no customer", projects.map((p) => p.name).join(", "), `${s.orders.length} orders`]
            .filter(Boolean).join(" · ")}
        </span>
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      {notice ? (
        <div className="banner-ok plan-notice" role="status">
          <span>
            Saved: {notice}. To undo it, open <Link to="/history/writes">History → Write batches</Link>.
          </span>
          <button type="button" className="icon-btn" aria-label="Hide this message" onClick={() => setNotice(null)}>&#x2715;</button>
        </div>
      ) : null}

      <TabStrip
        label="Plan sections"
        value={tab}
        onChange={(t) => go(t)}
        tabs={[
          { id: "overview", label: blocking ? `Overview (${blocking} blocking)` : "Overview" },
          { id: "money", label: "Deliveries & cash" },
          { id: "parts", label: short ? `Parts (${short} short)` : "Parts" },
          { id: "agenda", label: "Agenda" },
          { id: "setup", label: "Setup" },
        ]}
      />

      {tab === "overview" ? (
        <PlanOverview full={full} projects={projects} apply={apply} onLink={onLink} onOrder={setOrderId} />
      ) : null}
      {tab === "money" ? <PlanMoney full={full} projects={projects} /> : null}
      {tab === "parts" ? (
        <PlanParts full={full} apply={apply} selected={part} onSelect={(k) => go("parts", k)} />
      ) : null}
      {tab === "agenda" ? (
        <PlanAgenda events={s.agenda} today={s.today} projects={projects} currency={plan.currency} onLink={onLink} />
      ) : null}
      {tab === "setup" ? (
        <PlanSetup full={full} projects={allProjects} apply={apply} onOrder={setOrderId} />
      ) : null}

      {orderId != null ? (
        <OrderDialog full={full} orderId={orderId} onClose={() => setOrderId(null)} apply={apply} />
      ) : null}
    </PageShell>
  );
}
