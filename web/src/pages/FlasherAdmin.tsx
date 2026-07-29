/** Flasher admin: firmware binaries, releases (the flash), device files (the
 *  downloads) and deployment scripts (the scenario), per project. */
import { useEffect, useState } from "react";
import {
  errorMessage,
  getFlasherMeta,
  getProjects,
  isAbortError,
  type FlasherMeta,
  type ProjectInfo,
} from "../api";
import { ErrorBanner, Spinner } from "../components/Ui";
import DeviceFilesPanel from "../components/flasher/DeviceFilesPanel";
import FirmwarePanel from "../components/flasher/FirmwarePanel";
import ParamSetsPanel from "../components/flasher/ParamSetsPanel";
import ReleasesPanel from "../components/flasher/ReleasesPanel";
import ScriptsPanel from "../components/flasher/ScriptsPanel";
import { useStickyState } from "../useStickyState";

export default function FlasherAdmin() {
  const [projects, setProjects] = useState<ProjectInfo[] | null>(null);
  const [meta, setMeta] = useState<FlasherMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("flasher.project", null);

  useEffect(() => {
    const ac = new AbortController();
    Promise.all([getProjects(ac.signal), getFlasherMeta(ac.signal)])
      .then(([p, m]) => {
        setProjects(p);
        setMeta(m);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  const valid = projects?.some((p) => p.id === projectId) ? projectId : projects?.[0]?.id ?? null;

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Flasher</h1>
          {projects ? (
            <select
              className="row-input"
              value={valid ?? ""}
              onChange={(e) => setProjectId(Number(e.target.value))}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          ) : null}
          <span className="toolbar-total">
            releases carry the flash · deployment scripts carry the steps · runs record both
          </span>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {projects === null ? (
          <Spinner label="Loading projects…" />
        ) : valid === null ? (
          <p className="muted">No projects.</p>
        ) : (
          <>
            <ScriptsPanel projectId={valid} meta={meta} />
            <ReleasesPanel projectId={valid} />
            <DeviceFilesPanel projectId={valid} />
            <FirmwarePanel projectId={valid} meta={meta} />
            <ParamSetsPanel projectId={valid} />
          </>
        )}
      </div>
    </div>
  );
}
