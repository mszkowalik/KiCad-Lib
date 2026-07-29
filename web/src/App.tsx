import { createContext, useCallback, useEffect, useState } from "react";
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
import { getProposals } from "./api";
import { DialogProvider } from "./components/Dialog";
import Browse from "./pages/Browse";
import ComponentDetail from "./pages/ComponentDetail";
import DeviceDetail from "./pages/DeviceDetail";
import Devices from "./pages/Devices";
import FileViewer from "./pages/FileViewer";
import Deployments from "./pages/Deployments";
import FlashBench from "./pages/FlashBench";
import FlasherAdmin from "./pages/FlasherAdmin";
import FlashRunDetail from "./pages/FlashRunDetail";
import Invoices from "./pages/Invoices";
import Stock from "./pages/Stock";
import NewComponent from "./pages/NewComponent";
import ProductionJlc from "./pages/ProductionJlc";
import ProductionOverview from "./pages/ProductionOverview";
import ProductionWrites from "./pages/ProductionWrites";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import Proposals from "./pages/Proposals";
import RunDetail from "./pages/RunDetail";
import Setup from "./pages/Setup";
import Skills from "./pages/Skills";
import Templates from "./pages/Templates";
import TemplateDetail from "./pages/TemplateDetail";

/** Live pending-proposals count for the nav badge. `refresh()` after any
 *  approve/reject or when the agent reports new proposals. */
export const ProposalsBadge = createContext<{ count: number; refresh: () => void }>({
  count: 0,
  refresh: () => {},
});

function NotFound() {
  return (
    <div className="main-solo">
      <div className="page">
        <div className="card pad">
          <h1>Page not found</h1>
          <p className="muted">
            Nothing lives at this address. <Link to="/">Back to the component browser.</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

function navClass({ isActive }: { isActive: boolean }): string {
  return "topbar-link" + (isActive ? " active" : "");
}

/** Second-level nav for a section. Rendered above the section's pages.
 *  `end` keeps an index link (e.g. Production overview at /production) from
 *  claiming the active state on every sibling route. */
function SectionNav({ links }: { links: { to: string; label: string; end?: boolean }[] }) {
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

const LIBRARY_LINKS = [
  { to: "/library/components", label: "Components" },
  { to: "/library/templates", label: "Symbols & footprints" },
  { to: "/library/skills", label: "Skills" },
];

const PRODUCTION_LINKS = [
  { to: "/production", label: "Overview", end: true },
  { to: "/production/invoices", label: "Invoices" },
  { to: "/production/stock", label: "Stock" },
  { to: "/production/jlc", label: "JLC" },
  { to: "/production/deployments", label: "Deployments" },
  { to: "/production/bench", label: "Bench" },
  { to: "/production/devices", label: "Devices" },
  { to: "/production/artifacts", label: "Artifacts" },
  { to: "/production/writes", label: "Write log" },
];

/* Old addresses keep working — each redirect carries its params along. */
function RedirectBrowse() {
  const loc = useLocation();
  return <Navigate to={`/library/components${loc.search}`} replace />;
}
function RedirectComponent() {
  const { id } = useParams();
  return <Navigate to={`/library/components/${id}`} replace />;
}
function RedirectTemplate() {
  const { kind, id } = useParams();
  return <Navigate to={`/library/templates/${kind}/${id}`} replace />;
}

export default function App() {
  const [proposalCount, setProposalCount] = useState(0);

  const refresh = useCallback(() => {
    getProposals()
      .then((list) => setProposalCount(list.length))
      .catch(() => {
        /* nav badge only — never surface errors here */
      });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <DialogProvider>
      <ProposalsBadge.Provider value={{ count: proposalCount, refresh }}>
        <div className="app">
          <header className="topbar">
            <Link to="/" className="brand">
              Project Management Platform
            </Link>
            <nav className="topbar-nav">
              <NavLink to="/library" className={navClass}>
                Library
              </NavLink>
              <NavLink to="/projects" className={navClass}>
                Projects
              </NavLink>
              <NavLink to="/production" className={navClass}>
                Production
              </NavLink>
              <NavLink to="/proposals" className={navClass}>
                Proposals
                {proposalCount > 0 ? <span className="badge">{proposalCount}</span> : null}
              </NavLink>
              <NavLink to="/setup" className={navClass}>
                Setup
              </NavLink>
            </nav>
          </header>
          <Routes>
            <Route path="/" element={<RedirectBrowse />} />

            {/* Library */}
            <Route element={<SectionNav links={LIBRARY_LINKS} />}>
              <Route path="/library" element={<Navigate to="/library/components" replace />} />
              <Route path="/library/components" element={<Browse />} />
              <Route path="/library/components/new" element={<NewComponent />} />
              <Route path="/library/components/:id" element={<ComponentDetail />} />
              <Route path="/library/templates" element={<Templates />} />
              <Route path="/library/templates/:kind/:id" element={<TemplateDetail />} />
              <Route path="/library/skills/:id?" element={<Skills />} />
            </Route>

            {/* Projects */}
            <Route path="/projects" element={<Projects />} />
            <Route path="/projects/:id" element={<ProjectDetail />} />
            <Route path="/runs/:id" element={<RunDetail />} />

            {/* Production */}
            <Route element={<SectionNav links={PRODUCTION_LINKS} />}>
              <Route path="/production" element={<ProductionOverview />} />
              <Route path="/production/invoices" element={<Invoices />} />
              <Route path="/production/stock" element={<Stock />} />
              <Route path="/production/jlc" element={<ProductionJlc />} />
              <Route path="/production/deployments" element={<Deployments />} />
              <Route path="/production/artifacts" element={<FlasherAdmin />} />
              <Route path="/production/flasher" element={<Navigate to="/production/deployments" replace />} />
              <Route path="/production/bench" element={<FlashBench />} />
              <Route path="/production/devices" element={<Devices />} />
              <Route path="/production/devices/:id" element={<DeviceDetail />} />
              <Route path="/production/flash-runs/:id" element={<FlashRunDetail />} />
              <Route path="/production/writes" element={<ProductionWrites />} />
            </Route>

            <Route path="/proposals" element={<Proposals />} />
            <Route path="/setup" element={<Setup />} />
            <Route path="/view" element={<FileViewer />} />

            {/* Old addresses keep working */}
            <Route
              path="/components/new"
              element={<Navigate to="/library/components/new" replace />}
            />
            <Route path="/components/:id" element={<RedirectComponent />} />
            <Route path="/templates" element={<Navigate to="/library/templates" replace />} />
            <Route path="/templates/:kind/:id" element={<RedirectTemplate />} />
            <Route path="/skills" element={<Navigate to="/library/skills" replace />} />
            <Route path="/invoices" element={<Navigate to="/production/invoices" replace />} />
            <Route path="/parts-stock" element={<Navigate to="/production/stock" replace />} />
            <Route path="/jlc-stock" element={<Navigate to="/production/stock" replace />} />
            <Route path="/kicad" element={<Navigate to="/setup" replace />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
      </ProposalsBadge.Provider>
    </DialogProvider>
  );
}
