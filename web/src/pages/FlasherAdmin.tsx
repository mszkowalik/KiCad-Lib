/** Files — administration of everything a deployment version PINS.
 *
 *  Three sections, one at a time: berryware releases, artwork drawings and
 *  firmware. Releases and drawings are file SETS (decision 0029) and are
 *  platform wide — the same driver JSON in three projects is one row — so
 *  those two tabs have no project selector. Firmware is still project-scoped
 *  and keeps it. Composing any of them into a version happens on the
 *  Deployments page.
 *
 *  The active section lives in the URL (`?tab=`), and `?open=<set id>` opens
 *  one release on arrival, which is how the version card links here.
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
import FileSetsPanel from "../components/flasher/FileSetsPanel";
import FirmwarePanel from "../components/flasher/FirmwarePanel";
import { useStickyState } from "../useStickyState";

const TABS = ["releases", "artwork", "firmware"] as const;
type Tab = (typeof TABS)[number];

const LABELS: Record<Tab, string> = {
  releases: "Berryware releases",
  artwork: "Artwork",
  firmware: "Firmware",
};

const BLURBS: Record<Tab, string> = {
  releases: "the file sets a device downloads, named as the berry project releases them — platform wide",
  artwork: "the LightBurn drawings a mark version engraves, one per set — platform wide",
  firmware: "the .bin images, content-addressed by sha256, per project",
};

/** Old links: the tabs were `bundles` and `files` until 2026-09-18. */
const ALIASES: Record<string, Tab> = { bundles: "releases", files: "releases" };

export default function FlasherAdmin() {
  const [projects, setProjects] = useState<ProjectInfo[] | null>(null);
  const [meta, setMeta] = useState<FlasherMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("flasher.project", null);
  const [searchParams, setSearchParams] = useSearchParams();

  const rawTab = searchParams.get("tab") ?? "releases";
  const tab: Tab = (TABS as readonly string[]).includes(rawTab)
    ? (rawTab as Tab)
    : ALIASES[rawTab] ?? "releases";
  const openId = Number(searchParams.get("open") ?? "") || null;
  const setTab = (t: Tab) =>
    setSearchParams(t === "releases" ? {} : { tab: t }, { replace: true });

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
          {tab === "firmware" && projects ? (
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
        {tab === "releases" ? (
          <FileSetsPanel kind="berryware" openId={openId} />
        ) : tab === "artwork" ? (
          <FileSetsPanel kind="artwork" openId={openId} />
        ) : projects === null ? (
          <Spinner label="Loading projects…" />
        ) : valid === null ? (
          <p className="muted">No projects.</p>
        ) : (
          <FirmwarePanel projectId={valid} meta={meta} />
        )}
      </div>
    </div>
  );
}
