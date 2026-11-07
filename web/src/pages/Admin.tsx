import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import {
  errorMessage,
  getSchemaHealth,
  isAbortError,
} from "../api";
import { useAuth } from "../auth";
import SettingsCard from "../components/SettingsCard";
import TabStrip from "../components/TabStrip";
import UsersCard from "../components/UsersCard";
import MqttCard from "../components/MqttCard";
import CompaniesCard, { StockSplitCard } from "../components/CompaniesCard";
import { CompanyBackfillCard, MaterialLedgerCard, RecomputeChecksCard } from "../components/DataJobCards";
import { ErrorBanner, Spinner } from "../components/Ui";

type Tab = "config" | "users" | "companies" | "fleet" | "jobs" | "system";

/** The tabs, in the order they are drawn. `admin` marks the ones the API
 *  refuses to a non-admin anyway — hiding them keeps the page from offering a
 *  control that can only fail. */
const TABS: { id: Tab; label: string; admin?: true; blurb: string }[] = [
  {
    id: "config",
    label: "Configuration",
    admin: true,
    blurb: "Runtime knobs. A stored value wins over the environment.",
  },
  {
    id: "users",
    label: "Users",
    admin: true,
    blurb: "Accounts, roles and password resets. There is no sign-up.",
  },
  {
    id: "companies",
    label: "Companies",
    admin: true,
    blurb: "The companies the books are kept for, what each prints as a seller, and their KSeF tokens.",
  },
  {
    id: "fleet",
    label: "Fleet broker",
    admin: true,
    blurb: "The read-only MQTT credential that watches customer devices.",
  },
  {
    id: "jobs",
    label: "Data jobs",
    admin: true,
    blurb: "The one-time and repair jobs. Each one checks before it writes.",
  },
  {
    id: "system",
    label: "System",
    blurb: "Schema health, and where the KiCad client links live.",
  },
];

/** Tabs that moved to the section of their job (decision 0103). Old links work. */
const MOVED: Record<string, string> = {
  activity: "/history/all",
  datasheets: "/library/datasheets",
  rates: "/finance/rates",
  suppliers: "/stock/suppliers",
};

/** Administration of the DEPLOYMENT: its shared configuration, other people's
 * accounts, and the jobs and health readouts nobody owns personally. It was
 * called "Setup" until 2026-09-12; anything that belongs to the signed-in user
 * rather than to the deployment lives on `/account` instead.
 *
 * One TAB per subject (2026-09-19). The six panels used to be stacked on one
 * scroll — Configuration alone is 24 settings — so the schema readout at the
 * bottom was four screens below the tab you arrived for. The active tab is in
 * the URL (`?tab=users`), the same rule every other tabbed page here follows,
 * so a link can point at one panel.
 *
 * Five tabs are ADMIN ONLY and the API says so first — `routers/settings.py`,
 * `routers/users.py`, `routers/mqtt.py`, the company edit in
 * `routers/companies.py` and the jobs all sit behind `require_admin` (decisions
 * 0045, 0063). `admin: true` here only stops the page offering a panel
 * that would answer 403. Never gate a panel here alone: the gate is the API's,
 * and a hidden tab is a courtesy, not a control.
 */
export default function Admin() {
  const { isAdmin } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const tabs = useMemo(() => TABS.filter((t) => isAdmin || !t.admin), [isAdmin]);
  // Never empty — System carries no `admin` flag, so every signed-in user has
  // at least one panel. The default is whatever comes first for THIS reader,
  // which is Configuration for an admin and System for everybody else.
  const home = tabs[0].id;
  const param = searchParams.get("tab");
  const movedTo = param ? MOVED[param] : undefined;
  // An unknown tab, or an admin one reached by a non-admin, falls back to that
  // default rather than rendering nothing.
  const tab: Tab = tabs.some((t) => t.id === param) ? (param as Tab) : home;
  const setTab = (t: Tab) =>
    setSearchParams(t === home ? {} : { tab: t }, { replace: true });

  if (movedTo) {
    const request = searchParams.get("request");
    return <Navigate to={`${movedTo}${request ? `?request=${encodeURIComponent(request)}` : ""}`} replace />;
  }

  return (
    <div className="main-solo">
      <div className="page admin-page">
        <div className="toolbar">
          <h1>Admin</h1>
          <span className="toolbar-total">
            {tabs.find((t) => t.id === tab)?.blurb}
          </span>
        </div>

        <TabStrip tabs={tabs} value={tab} onChange={setTab} label="Administration section" />

        {tab === "config" ? <SettingsCard /> : null}
        {tab === "users" ? <UsersCard /> : null}
        {tab === "companies" ? <CompaniesCard /> : null}
        {tab === "fleet" ? <MqttCard /> : null}
        {tab === "jobs" ? <DataJobs /> : null}
        {tab === "system" ? (
          <>
            <HealthCard />
            <div className="card pad">
              <h2 className="card-title">KiCad clients and your API token</h2>
              <p className="muted">
                The install links, the .kicad_httplib download, the MCP settings and the
                effective URLs are on your{" "}
                <Link className="comp-link" to="/account">Account</Link> page. They carry YOUR
                token, so they differ per person — this page is the deployment's shared
                configuration.
              </p>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

/** One place for the one-time and repair jobs nobody owns personally. */
function DataJobs() {
  return (
    <>
      <StockSplitCard />
      <MaterialLedgerCard />
      <CompanyBackfillCard />
      <RecomputeChecksCard />
    </>
  );
}

function HealthCard() {
  const [health, setHealth] = useState<Awaited<ReturnType<typeof getSchemaHealth>> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const ac = new AbortController();
    getSchemaHealth(ac.signal)
      .then(setHealth)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  const failedCount = health ? Object.keys(health.failed).length : 0;

  return (
    <div className="card pad">
      <h2 className="card-title">Schema health</h2>
      <p className="muted">
        Which additive startup migrations landed. A feature that depends on a missing column
        fails far from the cause — this is where to look first.
      </p>
      <ErrorBanner message={error} />
      {health === null ? (
        !error && <Spinner label="checking schema" />
      ) : (
        <>
          <div className="toolbar">
            <span className={`pill ${health.ok ? "ok" : "err"}`}>
              {health.ok ? "all statements applied" : `${failedCount} failed`}
            </span>
            <span className="muted">{Object.keys(health.statements).length} statements</span>
          </div>
          {failedCount > 0 && (
            <div className="table-wrap">
              <table className="data data-fixed schema-table">
                <thead>
                  <tr>
                    <th>statement</th>
                    <th>result</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(health.failed).map(([name, result]) => (
                    <tr key={name}>
                      <td className="mono" title={name}>
                        {name}
                      </td>
                      <td className="cell-desc" title={result}>
                        {result}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {health.note ? <p className="muted dim">{health.note}</p> : null}
        </>
      )}
    </div>
  );
}
