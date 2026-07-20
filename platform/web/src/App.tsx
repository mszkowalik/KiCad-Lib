import { createContext, useCallback, useEffect, useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { getProposals } from "./api";
import { DialogProvider } from "./components/Dialog";
import Browse from "./pages/Browse";
import ComponentDetail from "./pages/ComponentDetail";
import FileViewer from "./pages/FileViewer";
import ImportStation from "./pages/ImportStation";
import Jaravis from "./pages/Jaravis";
import JlcStock from "./pages/JlcStock";
import KicadPage from "./pages/KicadPage";
import NewComponent from "./pages/NewComponent";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import Proposals from "./pages/Proposals";
import Skills from "./pages/Skills";

/** Live pending-proposals count for the nav badge. `refresh()` after any
 *  approve/reject or when Jaravis reports new proposals. */
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
              <NavLink to="/projects" className={navClass}>
                Projects
              </NavLink>
              <NavLink to="/jlc-stock" className={navClass}>
                JLC Stock
              </NavLink>
              <NavLink to="/jaravis" className={navClass}>
                Jaravis
              </NavLink>
              <NavLink to="/proposals" className={navClass}>
                Proposals
                {proposalCount > 0 ? <span className="badge">{proposalCount}</span> : null}
              </NavLink>
              <NavLink to="/skills" className={navClass}>
                Skills
              </NavLink>
              <NavLink to="/import" className={navClass}>
                Import
              </NavLink>
              <NavLink to="/kicad" className={navClass}>
                KiCad
              </NavLink>
            </nav>
          </header>
          <Routes>
            <Route path="/" element={<Browse />} />
            <Route path="/components/new" element={<NewComponent />} />
            <Route path="/components/:id" element={<ComponentDetail />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/projects/:id" element={<ProjectDetail />} />
            <Route path="/jlc-stock" element={<JlcStock />} />
            <Route path="/jaravis" element={<Jaravis />} />
            <Route path="/proposals" element={<Proposals />} />
            <Route path="/skills" element={<Skills />} />
            <Route path="/import" element={<ImportStation />} />
            <Route path="/kicad" element={<KicadPage />} />
            <Route path="/view" element={<FileViewer />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
      </ProposalsBadge.Provider>
    </DialogProvider>
  );
}
