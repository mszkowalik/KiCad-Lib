import { useEffect, useRef, useState } from "react";
import {
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";
import { AuthGate, useAuth } from "./auth";
import { DialogProvider } from "./components/Dialog";
import Browse from "./pages/Browse";
import Checklists from "./pages/Checklists";
import ComponentDetail from "./pages/ComponentDetail";
import Datasheets from "./pages/Datasheets";
import DeviceDetail from "./pages/DeviceDetail";
import Devices from "./pages/Devices";
import ExchangeRates from "./pages/ExchangeRates";
import FileViewer from "./pages/FileViewer";
import FinishedDevices from "./pages/FinishedDevices";
import Deployments from "./pages/Deployments";
import Bench from "./pages/Bench";
import FlasherAdmin from "./pages/FlasherAdmin";
import History, { Everyone } from "./pages/History";
import Home from "./pages/Home";
import Parameters from "./pages/Parameters";
import FlashRunDetail from "./pages/FlashRunDetail";
import Invoices from "./pages/Invoices";
import Stock from "./pages/Stock";
import Suppliers from "./pages/Suppliers";
import Transfers from "./pages/Transfers";
import SalesInvoices from "./pages/SalesInvoices";
import KsefInbox from "./pages/KsefInbox";
import CompanyBooks from "./pages/CompanyBooks";
import Customers from "./pages/Customers";
import NewComponent from "./pages/NewComponent";
import Orders from "./pages/Orders";
import Organizers from "./pages/Organizers";
import Runs from "./pages/Runs";
import OrderDetail from "./pages/OrderDetail";
import ProductionJlc from "./pages/ProductionJlc";
import ProductionOverview from "./pages/ProductionOverview";
import ProductionWrites from "./pages/ProductionWrites";
import ShipmentDetail from "./pages/ShipmentDetail";
import Shipments from "./pages/Shipments";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import Reviews from "./pages/Reviews";
import RunDetail from "./pages/RunDetail";
import Account from "./pages/Account";
import Admin from "./pages/Admin";
import Simulator from "./pages/Simulator";
import { readOpen, writeOpen } from "./scrollRestore";
import useScrollRestore from "./scrollRestore";
import Skills from "./pages/Skills";
import Templates from "./pages/Templates";
import TemplateDetail from "./pages/TemplateDetail";
import SimModelDetail from "./pages/SimModelDetail";
import PageShell from "./components/PageShell";

function NotFound() {
  return (
    <PageShell>
      <div className="card pad">
        <h1>Page not found</h1>
        <p className="muted">
          Nothing lives at this address. <Link to="/">Back to Home.</Link>
        </p>
      </div>
    </PageShell>
  );
}

function navClass({ isActive }: { isActive: boolean }): string {
  return "topbar-link" + (isActive ? " active" : "");
}

interface TabLink {
  to: string;
  label: string;
  end?: boolean;
}

/** Second-level nav for a section. Rendered above the section's pages.
 *  `end` keeps an index link from claiming the active state on every sibling
 *  route. With `section` it remembers the tab in use, so the section's link in
 *  the top bar goes back to it (decision 0103). */
function SectionNav({ links, section }: { links: TabLink[]; section?: string }) {
  const { pathname } = useLocation();
  useEffect(() => {
    if (!section) return;
    // The longest link that holds this address: /sales/orders/12 is /sales/orders.
    const tab = links
      .filter((l) => pathname === l.to || pathname.startsWith(`${l.to}/`))
      .sort((a, b) => b.to.length - a.to.length)[0];
    if (tab) writeOpen(`section:${section}`, tab.to);
  }, [pathname, links, section]);
  return (
    <>
      <nav className="subnav">
        {links.map((l) => (
          <NavLink key={l.to} to={l.to} end={l.end} className={navClass}>
            {l.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </>
  );
}

const LIBRARY_LINKS: TabLink[] = [
  { to: "/library/components", label: "Components" },
  { to: "/library/templates", label: "Templates" },
  { to: "/library/datasheets", label: "Datasheets" },
  { to: "/library/skills", label: "Skills" },
];

const REVIEW_LINKS: TabLink[] = [
  { to: "/reviews", label: "Queue", end: true },
  { to: "/reviews/checklists", label: "Checklists" },
];

const PRODUCTION_LINKS: TabLink[] = [
  { to: "/production/batches", label: "Batches" },
  { to: "/production/bench", label: "Bench" },
  { to: "/production/devices", label: "Devices" },
  { to: "/production/procedures", label: "Procedures" },
];

const PROCEDURE_LINKS: TabLink[] = [
  { to: "/production/procedures", label: "Procedures", end: true },
  { to: "/production/procedures/parameters", label: "Parameter sets" },
  { to: "/production/procedures/files", label: "Files" },
];

const STOCK_LINKS: TabLink[] = [
  { to: "/stock", label: "Parts", end: true },
  { to: "/stock/organizers", label: "Organizers" },
  { to: "/stock/finished", label: "Finished devices" },
  { to: "/stock/transfers", label: "Transfers" },
  { to: "/stock/suppliers", label: "Suppliers" },
  { to: "/stock/jlc", label: "JLCPCB" },
];

const SALES_LINKS: TabLink[] = [
  { to: "/sales/orders", label: "Orders" },
  { to: "/sales/shipments", label: "Shipments" },
  { to: "/sales/invoices", label: "Sales invoices" },
  { to: "/sales/customers", label: "Customers" },
];

const FINANCE_LINKS: TabLink[] = [
  { to: "/finance", label: "Cost overview", end: true },
  { to: "/finance/invoices", label: "Purchase invoices" },
  { to: "/finance/ksef", label: "KSeF" },
  { to: "/finance/books", label: "Company books" },
  { to: "/finance/rates", label: "Exchange rates" },
];

const HISTORY_LINKS: TabLink[] = [
  { to: "/history", label: "My changes", end: true },
  { to: "/history/writes", label: "Write batches" },
];

/** An old address. It keeps its parameters, so every saved link still works. */
function Moved({ to }: { to: string }) {
  const { search } = useLocation();
  const params = useParams();
  const path = to.replace(/:(\w+)/g, (_m, k: string) => params[k] ?? "");
  return <Navigate to={`${path}${search}`} replace />;
}

/** `/` is Home. A link from before Home searched the components, and still does. */
function HomeOrBrowse() {
  const { search } = useLocation();
  const q = new URLSearchParams(search);
  return q.has("q") || q.has("cat") ? <Navigate to={`/library/components${search}`} replace /> : <Home />;
}

/** A section in the top bar: it opens the tab last used there. */
function SectionLink({ section, prefix, to, children }: {
  section: string;
  prefix: string;
  to: string;
  children: React.ReactNode;
}) {
  const { pathname } = useLocation();
  const active = pathname === prefix || pathname.startsWith(`${prefix}/`);
  return (
    <Link className={navClass({ isActive: active })} to={readOpen(`section:${section}`) ?? to}>
      {children}
    </Link>
  );
}

/** Which company the screens show: one of the user's companies, or all of
 *  them (decision 0063). Hidden when the user belongs to one company only. */
function CompanySwitcher() {
  const { companies, scope, setScope } = useAuth();
  if (companies.length < 2) {
    return companies.length === 1 ? <span className="topbar-company muted">{companies[0].name}</span> : null;
  }
  return (
    <select className="topbar-company" value={scope} aria-label="Company"
      title="The company the screens show" onChange={(e) => setScope(e.target.value)}>
      <option value="all">All companies</option>
      {companies.map((c) => <option key={c.id} value={String(c.id)}>{c.name}</option>)}
    </select>
  );
}

/** The signed-in identity, and what belongs to it rather than to a job: the
 *  account, the history of its changes, the deployment and the way out. */
function UserMenu() {
  const { user, authEnabled, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  const links = (
    <>
      <Link className="topbar-link" to="/account">Account</Link>
      <Link className="topbar-link" to="/history">History</Link>
      <Link className="topbar-link" to="/admin">Admin</Link>
    </>
  );
  if (!authEnabled || user === null) {
    return (
      <span className="topbar-user">
        <CompanySwitcher />
        {links}
      </span>
    );
  }
  return (
    <span className="topbar-user">
      <CompanySwitcher />
      <div className="user-menu" ref={box}>
        <button type="button" className="topbar-username" aria-expanded={open} aria-haspopup="menu"
          title={`${user.username} (${user.role})`} onClick={() => setOpen(!open)}>
          {user.display_name || user.username} ▾
        </button>
        {open ? (
          <div className="user-menu-list" role="menu">
            {links}
            <button type="button" className="topbar-link" onClick={() => void signOut()}>Log out</button>
          </div>
        ) : null}
      </div>
    </span>
  );
}

/** The app itself. Rendered only AFTER the gate has a signed-in user, so no
 *  screen and no background fetch here ever runs anonymously. */
function Shell() {
  // Sitewide: every scroll position survives a reload and back/forward. The
  // browser cannot do it here — it restores the WINDOW, and this layout scrolls
  // `.main` / `.main-solo` inside a full-height shell. See `scrollRestore.ts`.
  useScrollRestore();
  return (
    <DialogProvider>
      <div className="app">
        <header className="topbar">
          <Link to="/" className="brand">
            Henry
          </Link>
          <nav className="topbar-nav">
            <span className="topbar-group">Engineering</span>
            <SectionLink section="library" prefix="/library" to="/library/components">Library</SectionLink>
            <NavLink to="/projects" className={navClass}>Projects</NavLink>
            <NavLink to="/sim" className={navClass}>Simulator</NavLink>
            <SectionLink section="reviews" prefix="/reviews" to="/reviews">Reviews</SectionLink>
            <span className="topbar-group">Operations</span>
            <SectionLink section="production" prefix="/production" to="/production/batches">Production</SectionLink>
            <SectionLink section="stock" prefix="/stock" to="/stock">Stock</SectionLink>
            <SectionLink section="sales" prefix="/sales" to="/sales/orders">Sales</SectionLink>
            <SectionLink section="finance" prefix="/finance" to="/finance">Finance</SectionLink>
            <UserMenu />
          </nav>
        </header>
        <Routes>
          <Route path="/" element={<HomeOrBrowse />} />

          {/* Library */}
          <Route element={<SectionNav links={LIBRARY_LINKS} section="library" />}>
            <Route path="/library" element={<Navigate to="/library/components" replace />} />
            <Route path="/library/components" element={<Browse />} />
            <Route path="/library/components/new" element={<NewComponent />} />
            <Route path="/library/components/:id" element={<ComponentDetail />} />
            <Route path="/library/templates" element={<Templates />} />
            {/* Static segment outranks :kind/:id in v6 route ranking. */}
            <Route path="/library/templates/sim/:id" element={<SimModelDetail />} />
            <Route path="/library/templates/:kind/:id" element={<TemplateDetail />} />
            <Route path="/library/datasheets" element={<Datasheets />} />
            <Route path="/library/skills/:id?" element={<Skills />} />
          </Route>

          {/* Projects */}
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />

          {/* Simulator — its own section in the top nav, and also reached
              from a project's schematic tab, or on its
              own with an uploaded sheet set. */}
          <Route path="/sim" element={<Simulator />} />

          {/* Production: making the devices */}
          <Route element={<SectionNav links={PRODUCTION_LINKS} section="production" />}>
            <Route path="/production" element={<Navigate to="/production/batches" replace />} />
            <Route path="/production/batches" element={<Runs />} />
            <Route path="/production/batches/:id" element={<RunDetail />} />
            <Route path="/production/bench" element={<Bench />} />
            <Route path="/production/devices" element={<Devices />} />
            <Route path="/production/devices/:id" element={<DeviceDetail />} />
            <Route path="/production/flash-runs/:id" element={<FlashRunDetail />} />
            <Route element={<SectionNav links={PROCEDURE_LINKS} />}>
              <Route path="/production/procedures" element={<Deployments />} />
              <Route path="/production/procedures/parameters" element={<Parameters />} />
              <Route path="/production/procedures/files" element={<FlasherAdmin />} />
            </Route>
          </Route>

          {/* Stock: parts, finished devices and who supplies them */}
          <Route element={<SectionNav links={STOCK_LINKS} section="stock" />}>
            <Route path="/stock" element={<Stock />} />
            <Route path="/stock/organizers" element={<Organizers />} />
            <Route path="/stock/finished" element={<FinishedDevices />} />
            <Route path="/stock/transfers" element={<Transfers />} />
            <Route path="/stock/suppliers" element={<Suppliers />} />
            <Route path="/stock/jlc" element={<ProductionJlc />} />
          </Route>

          {/* Sales: orders, what leaves the building, and the invoices for it */}
          <Route element={<SectionNav links={SALES_LINKS} section="sales" />}>
            <Route path="/sales" element={<Navigate to="/sales/orders" replace />} />
            <Route path="/sales/orders" element={<Orders />} />
            <Route path="/sales/orders/:id" element={<OrderDetail />} />
            <Route path="/sales/shipments" element={<Shipments />} />
            <Route path="/sales/shipments/:id" element={<ShipmentDetail />} />
            <Route path="/sales/invoices" element={<SalesInvoices />} />
            <Route path="/sales/customers" element={<Customers />} />
          </Route>

          {/* Finance: what it all cost, and the books */}
          <Route element={<SectionNav links={FINANCE_LINKS} section="finance" />}>
            <Route path="/finance" element={<ProductionOverview />} />
            <Route path="/finance/invoices" element={<Invoices />} />
            <Route path="/finance/ksef" element={<KsefInbox />} />
            <Route path="/finance/books" element={<CompanyBooks />} />
            <Route path="/finance/rates" element={<ExchangeRates />} />
          </Route>

          <Route element={<SectionNav links={REVIEW_LINKS} section="reviews" />}>
            <Route path="/reviews" element={<Reviews />} />
            <Route path="/reviews/checklists" element={<Checklists />} />
          </Route>

          {/* The user menu */}
          <Route element={<HistoryNav />}>
            <Route path="/history" element={<History />} />
            <Route path="/history/writes" element={<ProductionWrites />} />
            <Route path="/history/all" element={<Everyone />} />
          </Route>
          <Route path="/admin" element={<Admin />} />
          <Route path="/account" element={<Account />} />
          <Route path="/view" element={<FileViewer />} />

          {/* Old addresses keep working, with their parameters (decision 0103). */}
          <Route path="/runs/:id" element={<Moved to="/production/batches/:id" />} />
          <Route path="/production/runs" element={<Moved to="/production/batches" />} />
          <Route path="/production/orders" element={<Moved to="/sales/orders" />} />
          <Route path="/production/orders/:id" element={<Moved to="/sales/orders/:id" />} />
          <Route path="/production/shipments" element={<Moved to="/sales/shipments" />} />
          <Route path="/production/shipments/:id" element={<Moved to="/sales/shipments/:id" />} />
          <Route path="/production/sales-invoices" element={<Moved to="/sales/invoices" />} />
          <Route path="/production/invoices" element={<Moved to="/finance/invoices" />} />
          <Route path="/production/ksef" element={<Moved to="/finance/ksef" />} />
          <Route path="/production/company" element={<Moved to="/finance/books" />} />
          <Route path="/production/stock" element={<Moved to="/stock" />} />
          <Route path="/production/transfers" element={<Moved to="/stock/transfers" />} />
          <Route path="/production/jlc" element={<Moved to="/stock/jlc" />} />
          <Route path="/production/deployments" element={<Moved to="/production/procedures" />} />
          <Route path="/production/parameters" element={<Moved to="/production/procedures/parameters" />} />
          <Route path="/production/files" element={<Moved to="/production/procedures/files" />} />
          <Route path="/production/files/parameters" element={<Moved to="/production/procedures/parameters" />} />
          <Route path="/production/artifacts" element={<Moved to="/production/procedures/files" />} />
          <Route path="/production/flasher" element={<Moved to="/production/procedures" />} />
          {/* Marking is a selection on the one bench now (decision 0076). */}
          <Route path="/production/marking" element={<Moved to="/production/bench" />} />
          <Route path="/production/writes" element={<Moved to="/history/writes" />} />
          <Route path="/components/new" element={<Moved to="/library/components/new" />} />
          <Route path="/components/:id" element={<Moved to="/library/components/:id" />} />
          <Route path="/templates" element={<Moved to="/library/templates" />} />
          <Route path="/templates/:kind/:id" element={<Moved to="/library/templates/:kind/:id" />} />
          <Route path="/skills" element={<Moved to="/library/skills" />} />
          <Route path="/invoices" element={<Moved to="/finance/invoices" />} />
          <Route path="/parts-stock" element={<Moved to="/stock" />} />
          <Route path="/jlc-stock" element={<Moved to="/stock" />} />
          {/* Renamed 2026-09-12 — the page administers the deployment, and the
              per-user half moved to /account. Both old paths still resolve. */}
          <Route path="/setup" element={<Moved to="/admin" />} />
          <Route path="/kicad" element={<Moved to="/admin" />} />
          {/* The approval queue is gone (2026-08-24) — every write publishes.
              Reviews is where a published version is judged now. */}
          <Route path="/proposals" element={<Moved to="/reviews" />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
    </DialogProvider>
  );
}

/** Everyone's activity is an administrator's tab: the API refuses it to others. */
function HistoryNav() {
  const { isAdmin } = useAuth();
  return (
    <SectionNav links={isAdmin ? [...HISTORY_LINKS, { to: "/history/all", label: "Everyone" }] : HISTORY_LINKS} />
  );
}

export default function App() {
  // The gate is the outermost thing in the app: until it has an answer, the
  // router does not exist. See auth.tsx.
  return (
    <AuthGate>
      <Shell />
    </AuthGate>
  );
}
