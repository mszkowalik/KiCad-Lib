/** Files — administration of everything a deployment version PINS.
 *
 *  Four sections, one at a time (user request 2026-07-30: a tab per kind is
 *  cleaner to administer than four stacked cards): berryware bundles,
 *  firmware, the individual-file pool, and parameter sets. Composing them
 *  into a version happens on the Deployments page.
 *
 *  The active section lives in the URL (?tab=), so any view is linkable.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  errorMessage,
  getFlasherMeta,
  getProjects,
  isAbortError,
  type FlasherMeta,
  type ProjectInfo,
} from "../api";
import { ErrorBanner, Spinner } from "../components/Ui";
import BundlesPanel from "../components/flasher/BundlesPanel";
import DeviceFilesPanel from "../components/flasher/DeviceFilesPanel";
import FirmwarePanel from "../components/flasher/FirmwarePanel";
import ParamSetsPanel from "../components/flasher/ParamSetsPanel";
import { useStickyState } from "../useStickyState";

const TABS = ["bundles", "firmware", "files", "parameters"] as const;
type Tab = (typeof TABS)[number];

const LABELS: Record<Tab, string> = {
  bundles: "Berryware bundles",
  firmware: "Firmware",
  files: "Individual files",
  parameters: "Parameters",
};

const BLURBS: Record<Tab, string> = {
  bundles: "the berryware sets a device downloads, named as the berry project releases them",
  firmware: "the .bin images, content-addressed by sha256",
  files: "the raw per-file pool behind the bundles — for a surgical edit to one script",
  parameters: "shared values a procedure interpolates: WiFi, MQTT host, credential salt, SIM PIN",
};

export default function FlasherAdmin() {
  const [projects, setProjects] = useState<ProjectInfo[] | null>(null);
  const [meta, setMeta] = useState<FlasherMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("flasher.project", null);
  const [searchParams, setSearchParams] = useSearchParams();

  const rawTab = searchParams.get("tab") ?? "bundles";
  const tab: Tab = (TABS as readonly string[]).includes(rawTab) ? (rawTab as Tab) : "bundles";
  const setTab = (t: Tab) =>
    setSearchParams(t === "bundles" ? {} : { tab: t }, { replace: true });

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
          <h1>Files</h1>
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
          <span className="toolbar-total">{BLURBS[tab]}</span>
        </div>

        <div className="seg proj-tabs" role="tablist" aria-label="File administration">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              className={tab === t ? "on" : ""}
              onClick={() => setTab(t)}
            >
              {LABELS[t]}
            </button>
          ))}
        </div>

        {error ? <ErrorBanner message={error} /> : null}
        {projects === null ? (
          <Spinner label="Loading projects…" />
        ) : valid === null ? (
          <p className="muted">No projects.</p>
        ) : tab === "bundles" ? (
          <BundlesPanel projectId={valid} />
        ) : tab === "firmware" ? (
          <FirmwarePanel projectId={valid} meta={meta} />
        ) : tab === "files" ? (
          <DeviceFilesPanel projectId={valid} />
        ) : (
          <ParamSetsPanel projectId={valid} />
        )}
      </div>
    </div>
  );
}
