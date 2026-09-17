/** The marking bench: ONE station, because there is one laser.
 *
 *  Deliberately a separate page from the flashing bench rather than a fifth
 *  station on it. The two jobs have different shapes: flashing runs four
 *  devices at once and is started by hand; marking runs one device at a time,
 *  starts itself when the part arrives, and depends on a local agent that can
 *  be missing. Folding them together would mean four stations competing for
 *  one laser and an agent warning on a page that does not need one.
 *
 *  What runs here is an ordinary deployment version whose kind is "mark" — its
 *  own steps, its own pinned artwork, its own history rows. The laser is
 *  reached by `mark_laser`, the only op the bench hands to the agent.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  errorMessage,
  getProjects,
  isAbortError,
  listDeployments,
  benchAgentUrl,
  type DeploymentRow,
  type ProjectInfo,
  getFlasherMeta,
  type FlasherMeta,
} from "../api";
import BenchStation from "../components/flasher/BenchStation";
import Field, { FieldRow } from "../components/Field";
import { ErrorBanner } from "../components/Ui";
import {
  listPrinters,
  type AgentRoll,
  MarkAgent,
  NEEDS_PROTOCOL,
  type AgentPrinter,
} from "../flasher/benchAgent";
import { useStickyState } from "../useStickyState";

/** How often the bench asks whether the laser is reachable. Often enough that
 *  starting the agent feels instant, gentle enough to be a heartbeat: each poll
 *  is one HTTP request and one UDP PING. */
const AGENT_POLL_MS = 2000;

type AgentState =
  | { kind: "checking" }
  | { kind: "down"; error: string }
  | {
      kind: "up";
      /** True when this agent is too old to print. It still marks. */
      stale: boolean;
      lightburn: boolean;
      busy: boolean | null;
      /** the laser controller on the bench machine's USB; null = cannot tell */
      laserUsb: { present: boolean; name: string; ids: string } | null;
      host: string;
      /** The rolls that printer's PPD offers — the printer's own statement,
       *  never a list kept in the browser. */
      rolls: AgentRoll[];
      /** Every print queue on the bench machine. The station shows the one it
       *  is set to; the page only fetches, because it owns the heartbeat. */
      printers: AgentPrinter[];
    };

export default function MarkBench() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [deployments, setDeployments] = useState<DeploymentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useStickyState<number | null>("mark.project", null);
  const [versionId, setVersionId] = useStickyState<number | null>("mark.version", null);

  /** `/meta`: the marking placeholders and the serial bounds the station needs.
   *  It keeps none of its own (decision 2026-09-17). */
  const [meta, setMeta] = useState<FlasherMeta | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    getFlasherMeta(ac.signal).then(setMeta).catch(() => setMeta(null));
    return () => ac.abort();
  }, []);

  const [agent, setAgent] = useState<AgentState>({ kind: "checking" });
  /** When the answer below was taken. A re-check that finds the same state
   *  changes nothing on screen, which reads as a dead button — the time is the
   *  only proof the button did anything. */
  const [checkedAt, setCheckedAt] = useState<string | null>(null);


  useEffect(() => {
    const ac = new AbortController();
    getProjects(ac.signal)
      .then(setProjects)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  const validProject = projects.some((p) => p.id === projectId) ? projectId : projects[0]?.id ?? null;

  useEffect(() => {
    if (!validProject) return;
    const ac = new AbortController();
    listDeployments(validProject, ac.signal)
      .then(setDeployments)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [validProject]);

  /** Marking procedures only. Read from `kind`, never from the name — the
   *  flashing bench learned that when renaming a deployment took its Test
   *  button away. */
  const markVersions = useMemo(
    () =>
      deployments
        .filter((d) => d.kind === "mark")
        .map((d) => ({
          name: d.name,
          versions: d.versions.map((v) => {
            const chans = d.channels
              .filter((c) => c.deployment_version_id === v.id)
              .map((c) => c.name);
            return { id: v.id, label: `v${v.version_no} (${[v.status, ...chans].join(", ")})` };
          }),
        })),
    [deployments],
  );

  const anyVersion = markVersions.some((d) => d.versions.length > 0);
  const chosen = deployments
    .flatMap((d) => d.versions.map((v) => ({ d, v })))
    .find((x) => x.v.id === versionId);

  /** The project's marking procedure, current version — what the bench marks
   *  with all day, so the page opens on it (user decision 2026-09-17). Applied
   *  once per project: a version picked by hand afterwards sticks, and a
   *  remembered one that still belongs to this project wins. */
  const defaultedFor = useRef<number | null>(null);
  useEffect(() => {
    if (!validProject || deployments[0]?.project_id !== validProject) return;
    if (defaultedFor.current === validProject) return;
    defaultedFor.current = validProject;
    const known = deployments.some((d) => d.kind === "mark" && d.versions.some((v) => v.id === versionId));
    if (known) return;
    const mark = deployments.find((d) => d.kind === "mark" && d.current_version_id);
    setVersionId(mark?.current_version_id ?? null);
  }, [validProject, deployments, versionId, setVersionId]);

  const checkAgent = useCallback(async (quiet = false) => {
    // Only the FIRST check says "checking…". A poll that flickered the pill
    // twice a second would be harder to read than no status at all.
    if (!quiet) setAgent({ kind: "checking" });
    const a = new MarkAgent();
    try {
      const hello = await a.hello();
      const health = await a.health();
      // One heartbeat for both machines. The printer list is three subprocess
      // calls on the agent and the laser probe is a UDP round trip, so asking
      // for them together costs one poll rather than two.
      let printers: AgentPrinter[] = [];
      // The rolls come with them: they are the PPD's own statement about the
      // printer, and the bench must not keep a list of its own (decision
      // 2026-09-17).
      let rolls: AgentRoll[] = [];
      try {
        const got = await listPrinters();
        printers = got.printers;
        rolls = got.rolls;
      } catch {
        // An agent from before labels existed answers 404 here. That is not a
        // reason to report the whole bench as down — it still marks.
        printers = [];
        rolls = [];
      }
      setAgent({
        kind: "up",
        stale: (hello.protocol ?? 0) < NEEDS_PROTOCOL,
        rolls,
        lightburn: health.responsive,
        busy: health.busy,
        laserUsb: health.laserUsb,
        host: hello.lightburn_host,
        printers,
      });
    } catch (e) {
      setAgent({ kind: "down", error: errorMessage(e) });
    } finally {
      setCheckedAt(new Date().toLocaleTimeString());
      a.close();
    }
  }, []);

  // Watched, not asked for. The operator starts the agent, or LightBurn, or
  // fixes a dialog, and the bench notices on its own — a button meant standing
  // at the machine and clicking a page.
  //
  // Sequential rather than an interval: a slow answer must not pile checks up
  // behind it. Paused while the tab is hidden, because this pings the laser
  // machine and nobody is reading the answer.
  useEffect(() => {
    let alive = true;
    let timer = 0;
    const tick = async () => {
      if (!alive) return;
      try {
        if (document.visibilityState === "visible") await checkAgent(true);
      } finally {
        // ALWAYS re-arm. A throw anywhere above used to end the watch for good,
        // and the symptom is the worst kind: a status that was true once and is
        // now just old.
        if (alive) timer = window.setTimeout(tick, AGENT_POLL_MS);
      }
    };
    // Chrome throttles timers in a background tab to about once a minute, and
    // freezes them entirely after a while. Coming back to the tab must not mean
    // waiting for that timer: check at once, and reset the cadence.
    const wake = () => {
      if (document.visibilityState !== "visible") return;
      clearTimeout(timer);
      void tick();
    };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("focus", wake);
    void checkAgent();
    timer = window.setTimeout(tick, AGENT_POLL_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("focus", wake);
    };
  }, [checkAgent]);

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Marking bench</h1>
          <span className="toolbar-total">
            one device at a time · the agent on this machine drives LightBurn and the label printer
          </span>
        </div>
        {error ? <ErrorBanner message={error} /> : null}


        <div className="card pad stack">
          <FieldRow>
            <Field label="Project">
              <select
                value={validProject ?? ""}
                onChange={(e) => {
                  setProjectId(Number(e.target.value) || null);
                  setVersionId(null);
                  // Picking a project asks for its marking procedure back.
                  defaultedFor.current = null;
                }}
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Marking procedure">
              <select
                value={versionId ?? ""}
                onChange={(e) => setVersionId(Number(e.target.value) || null)}
              >
                <option value="">— pick one —</option>
                {markVersions.map((d) => (
                  <optgroup key={d.name} label={d.name}>
                    {d.versions.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.label}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </Field>
          </FieldRow>

          {!anyVersion ? (
            <p className="muted">
              This project has no marking procedure yet. Create a deployment with kind{" "}
              <code>mark</code>, pin the <code>.lbrn2</code> artwork to a version as a device file,
              and give it a step that engraves.
            </p>
          ) : null}
          {chosen ? (
            <p className="muted">
              {chosen.d.name} v{chosen.v.version_no} · {chosen.v.file_count} pinned file(s) ·{" "}
              {chosen.v.step_count} steps
            </p>
          ) : null}

          {/* Automatic is now TWO choices, and they live on the station beside
              the machine each one starts: a bench may engrave all day and print
              nothing, or print while the laser is down. */}
          <AgentPanel state={agent} checkedAt={checkedAt} />
        </div>

        <div className="bench-grid bench-grid-one">
          <BenchStation
            index={0}
            mode="mark"
            agentUp={agent.kind === "up"}
            laser={
              agent.kind === "up"
                ? { responsive: agent.lightburn, busy: agent.busy, laserUsb: agent.laserUsb }
                : { responsive: false, busy: null, laserUsb: null }
            }
            printers={agent.kind === "up" ? agent.printers : []}
            rolls={agent.kind === "up" ? agent.rolls : []}
            meta={meta}
            productionRunId={null}
            deploymentVersionId={versionId}
            overrideReason=""
            simPin=""
            projectId={validProject}
          />
        </div>
      </div>
    </div>
  );
}

/** The bench agent's reachability, in ONE line.
 *
 *  A row inside the bench's one settings card, not a card of its own: what the
 *  bench is set to and whether it can reach the laser are one question at the
 *  top of the page, and two boxes made the second look like a second subject.
 *  It is a status strip, not a report: two hops, four possible states, and a
 *  sentence. It used to be a card with a banner inside it and the same advice
 *  written twice, which took a sixth of the page to say "not running". It is
 *  WATCHED rather than asked for, so it carries no button.
 *
 *  The two hops stay distinguishable, because they are fixed in different
 *  places: "agent not running" is the bench machine, "LightBurn not answering"
 *  is LightBurn — and the third cause of that one, a Core licence, is named,
 *  because it fails as silence rather than as an error.
 */
function AgentPanel({ state, checkedAt }: { state: AgentState; checkedAt: string | null }) {
  const [pill, tone, note] =
    state.kind === "checking"
      ? ["checking…", "neutral", ""]
      : state.kind === "down"
        ? [
            "agent not running",
            "err",
            "Download it, open the zip and double-click 7Sigma Agent. If it is already " +
              "running, allow local network access when Chrome asks.",
          ]
        : state.stale
          ? [
              "out of date",
              "warn",
              "This agent was downloaded before label printing existed, so it marks but " +
                "cannot print. Download it again and open the new one.",
            ]
          : [
            "running",
            "ok",
            `Driving LightBurn at ${state.host}` +
              (state.printers.length
                ? ` and ${state.printers.length} printer(s) on this machine.`
                : ". It reports no printer on this machine."),
          ];

  return (
    <div className="bench-agent">
      <strong>Bench agent</strong>
      <span className={`pill ${tone}`}>{pill}</span>
      {note ? <span className="muted bench-agent-note">{note}</span> : null}
      {/* The time is the proof that the WATCH is alive: it moves on its own,
          and a stale one says the polling stopped. */}
      {checkedAt ? <span className="muted dim">{checkedAt}</span> : null}
      {/* Always offered: the agent is set up BEFORE anything is wrong, and
          hiding it until the bench breaks is how it gets found at the worst
          moment. */}
      <a className="btn btn-sm" href={benchAgentUrl()} download>
        Download the bench agent
      </a>
    </div>
  );
}
