/** Files — administration of everything a deployment version PINS.
 *
 *  Three sections, one at a time: berryware releases, artwork drawings and
 *  firmware. Releases and drawings are file SETS (decision 0029) and are
 *  platform wide — the same driver JSON in three projects is one row — so
 *  those two tabs have no project selector. Firmware is still project-scoped
 *  and keeps it. Composing any of them into a version happens on the
 *  Procedures page.
 *
 *  The active section lives in the URL (`?tab=`), and `?open=<set id>` opens
 *  one release on arrival, which is how the version card links here.
 */
import { useSearchParams } from "react-router-dom";
import {
  getFlasherMeta,
  getProjects,
} from "../api";
import { ErrorBanner, Spinner } from "../components/Ui";
import FileSetsPanel from "../components/flasher/FileSetsPanel";
import FirmwarePanel from "../components/flasher/FirmwarePanel";
import TabStrip from "../components/TabStrip";
import { useStickyState } from "../useStickyState";
import { useLoad } from "../components/useLoad";
import PageShell from "../components/PageShell";

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
  const { data, error } = useLoad((signal) => Promise.all([getProjects(signal), getFlasherMeta(signal)]), []);
  const projects = data?.[0] ?? null;
  const meta = data?.[1] ?? null;
  const [projectId, setProjectId] = useStickyState<number | null>("flasher.project", null);
  const [searchParams, setSearchParams] = useSearchParams();

  const rawTab = searchParams.get("tab") ?? "releases";
  const tab: Tab = (TABS as readonly string[]).includes(rawTab)
    ? (rawTab as Tab)
    : ALIASES[rawTab] ?? "releases";
  const openId = Number(searchParams.get("open") ?? "") || null;
  const setTab = (t: Tab) =>
    setSearchParams(t === "releases" ? {} : { tab: t }, { replace: true });

  const valid = projects?.some((p) => p.id === projectId) ? projectId : projects?.[0]?.id ?? null;

  return (
    <PageShell>
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

      <TabStrip
        tabs={TABS.map((t) => ({ id: t, label: LABELS[t] }))}
        value={tab}
        onChange={setTab}
        label="File administration"
      />

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
    </PageShell>
  );
}
