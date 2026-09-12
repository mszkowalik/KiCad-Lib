/** Field solver: controlled-impedance geometry for a PCB stackup.
 *
 *  The flow is design-first, like a fab's calculator. Pick the stackup and the
 *  production rules, say which layer carries the signal and which layers are its
 *  references, state the target impedance — then "Find solutions" returns a table of
 *  buildable geometries and you take one. Single-parameter entry is the fine-tuning
 *  path, not the entry point.
 *
 *  Everything drawn is the solved 2D cross-section: potential, |E|, field lines,
 *  |H|, surface current. The solver is quasi-TEM and floored at 1 MHz.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  errorMessage,
  fsCheck,
  fsFinishes,
  fsGeometry,
  fsMaterials,
  fsRules,
  fsGetWorkspace,
  fsPutWorkspace,
  fsStackups,
  isAbortError,
  type FsFinish,
  type FsFrame,
  type FsGeometry,
  type FsMaterial,
  type FsResult,
  type FsRuleSet,
  type FsSearchResult,
  type FsSearchRow,
  type FsStackup,
} from "../../api";
import { ErrorBanner, Spinner } from "../../components/Ui";
import { useAuth } from "../../auth";
import ProjectPanel from "./ProjectPanel";
import type { FsBoardProfile } from "../../api";
import Chart from "./Chart";
import StackupTable, { StackupLegend } from "../../components/StackupTable";
import { useDialog } from "../../components/Dialog";
import { RulesEditor, StackupEditor } from "./Editors";
import { drawCrossSection, fitView, palette, type FieldView, type View } from "./draw";
import {
  cellOf,
  cellParams,
  copperLayers,
  fmt,
  fmtHz,
  isCpw,
  isPair,
  lineType,
  maskOn,
  minPitch,
  F_CEIL,
  F_FLOOR,
  newProfile,
  perDecade,
  refOptions,
  refreshName,
  sweepPoints,
  sweepRange,
  TYPE_LABEL,
  zKey,
  type Cell,
  type Profile,
} from "./model";
import { useSolverJob } from "./useSolverJob";
import { useWheel } from "../../useWheel";
import NumberInput from "../../components/NumberInput";
import SiInput from "../../components/SiInput";

const SOLVE_STEPS = [
  { key: "mesh", label: "Mesh the cross-section" },
  { key: "refine", label: "Refine the mesh adaptively" },
  { key: "solve", label: "Solve at the design frequency" },
  { key: "sweep", label: "Frequency sweep" },
];

const VIEWS: { value: FieldView; label: string }[] = [
  { value: "phi", label: "electric potential + equipotentials" },
  { value: "E", label: "|E| magnitude + equipotentials" },
  { value: "Elines", label: "E field lines (trace → reference)" },
  { value: "Ey", label: "Ey signed (vertical component)" },
  { value: "H", label: "|H| magnitude + magnetic field lines" },
  { value: "Hx", label: "Hx signed (horizontal component)" },
  { value: "Js", label: "surface current density on the copper" },
  { value: "none", label: "geometry only" },
];

/** One stackup's worth of work. */
interface Bench {
  profiles: Profile[];
  selProfile?: number;
  selLayer?: string;
}

/** What the workspace row holds. Deliberately the page's own state, not a second
 *  model of it: the solver page IS the document here.
 *
 *  Profiles are banked PER STACKUP. A profile's cells are keyed by copper layer name,
 *  so a geometry built on a six-layer board describes nothing on a two-layer one —
 *  carrying one across would keep a cell for a layer that no longer exists and quietly
 *  claim it was solved against the new stackup. Switching stackups therefore parks the
 *  current set and picks up whatever was left on the one being opened. */
interface SavedWorkspace {
  stackupId?: string;
  ruleId?: string;
  epsModel?: string;
  byStackup?: Record<string, Bench>;
  /** Read once from a workspace written before the bank existed, then dropped. */
  profiles?: Profile[];
  selProfile?: number;
  selLayer?: string;
}

/** A new bench: one profile, enabled on the top copper layer. */
function freshBench(st: FsStackup): Bench {
  const p = newProfile(0);
  const l = copperLayers(st)[0]?.name as string;
  if (l) cellOf(p, st, l).enabled = true;
  return { profiles: [p], selProfile: p.id, selLayer: l };
}

/** The selection a bench should open with, dropping one that names a layer or a
 *  profile the bench no longer has. */
function selFor(b: Bench, st: FsStackup): { profile: number; layer: string } {
  const first = copperLayers(st)[0]?.name as string;
  const layer = b.selLayer && copperLayers(st).some((c) => c.name === b.selLayer) ? b.selLayer : first;
  const profile = b.profiles.some((q) => q.id === b.selProfile) ? (b.selProfile as number) : b.profiles[0].id;
  return { profile, layer };
}

export default function FieldSolver() {
  const [stackups, setStackups] = useState<FsStackup[]>([]);
  const [rules, setRules] = useState<FsRuleSet[]>([]);
  const [materials, setMaterials] = useState<FsMaterial[]>([]);
  const [finishes, setFinishes] = useState<FsFinish[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [stackupId, setStackupId] = useState("");
  const [ruleId, setRuleId] = useState("");
  const [epsModel, setEpsModel] = useState("djordjevic");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [sel, setSel] = useState<{ profile: number; layer: string } | null>(null);
  const [editStackup, setEditStackup] = useState(false);
  const [editRules, setEditRules] = useState(false);

  const [geometry, setGeometry] = useState<FsGeometry | null>(null);
  const [result, setResult] = useState<FsResult | null>(null);
  const [frames, setFrames] = useState<FsFrame[]>([]);
  const [frameIdx, setFrameIdx] = useState(0);
  const [search, setSearch] = useState<FsSearchResult | null>(null);
  const [searchSort, setSearchSort] = useState<{ col: string; dir: 1 | -1 } | null>(null);
  const [searchFolded, setSearchFolded] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [view, setView] = useState<FieldView>("phi");
  const [locked, setLocked] = useState(true);
  /* The viewport is PER PROFILE, keyed by profile id and copper layer.
   *
   *  It used to be one shared `View`, set once and then kept: switching to
   *  another profile therefore reused the previous one's zoom and centre, and
   *  a narrower or thicker cross-section was drawn cropped with no indication
   *  that the view, not the geometry, was wrong. Keeping "lock view" ticked
   *  made it permanent, since a locked view refuses wheel and drag.
   *
   *  Storing one per profile does the two things asked of it at once: a
   *  profile that has never been looked at is FITTED when it is opened, and a
   *  profile you have zoomed into is exactly where you left it when you come
   *  back. `lock view` is untouched by any of this — it stays ticked. */
  const [viewports, setViewports] = useState<Record<string, View>>({});
  const vpKey = sel ? `${sel.profile}:${sel.layer}` : "";
  const viewport = viewports[vpKey] ?? null;
  const setViewport = useCallback(
    (v: View | null) =>
      setViewports((prev) => {
        if (v === null) {
          const next = { ...prev };
          delete next[vpKey];
          return next;
        }
        return { ...prev, [vpKey]: v };
      }),
    [vpKey],
  );

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const job = useSolverJob();
  const { isAdmin } = useAuth();
  const dialog = useDialog();
  const [params] = useSearchParams();

  // The workspace is this person's scratch space, restored on mount and written back
  // debounced. `restored` gates the writer: without it the first render would save the
  // blank starting page over whatever was stored before the GET came back.
  const restored = useRef(false);
  const saveTimer = useRef<number | null>(null);
  /** Work parked on the stackups that are not open. */
  const [bank, setBank] = useState<Record<string, Bench>>({});

  const stackup = useMemo(() => stackups.find((s) => s.id === stackupId), [stackups, stackupId]);
  const ruleset = useMemo(() => rules.find((r) => r.id === ruleId), [rules, ruleId]);
  const profile = useMemo(() => profiles.find((p) => p.id === sel?.profile), [profiles, sel]);
  const cell = profile && stackup && sel ? cellOf(profile, stackup, sel.layer) : null;

  // ------------------------------------------------------------------ load
  useEffect(() => {
    const ctrl = new AbortController();
    Promise.all([
      fsStackups(ctrl.signal),
      fsRules(ctrl.signal),
      fsMaterials(ctrl.signal),
      fsFinishes(ctrl.signal),
      fsGetWorkspace(ctrl.signal).catch(() => ({ data: null, updated_at: null })),
    ])
      .then(([st, ru, ma, fi, ws]) => {
        setStackups(st);
        setRules(ru);
        setMaterials(ma);
        setFinishes(fi);

        // A ?stackup= in the URL wins over the stored workspace: it is what the
        // project page just asked for, and it is the whole point of the deep link.
        const wanted = params.get("stackup");
        const saved = (ws?.data ?? null) as SavedWorkspace | null;
        const known = (id: string | null | undefined) => (id && st.some((x) => x.id === id) ? id : "");
        const stackKey = known(wanted) || known(saved?.stackupId) || (st.find((s) => s.id === "JLC04161H-7628") ?? st[0])?.id || "";
        const first = st.find((s) => s.id === stackKey);
        setStackupId(stackKey);
        setRuleId((saved?.ruleId && ru.some((r) => r.id === saved.ruleId) ? saved.ruleId : ru[0]?.id) ?? "");
        if (saved?.epsModel) setEpsModel(saved.epsModel);

        // A workspace written before the bank existed holds one set tagged with the
        // stackup it belonged to; it becomes that stackup's bench and nothing else.
        const banked: Record<string, Bench> = { ...(saved?.byStackup ?? {}) };
        if (!saved?.byStackup && saved?.profiles?.length && saved.stackupId) {
          banked[saved.stackupId] = {
            profiles: saved.profiles,
            selProfile: saved.selProfile,
            selLayer: saved.selLayer,
          };
        }
        setBank(banked);
        const bench = banked[stackKey];
        if (bench?.profiles?.length && first) {
          setProfiles(bench.profiles);
          setSel(selFor(bench, first));
        } else if (first) {
          const b = freshBench(first);
          setProfiles(b.profiles);
          setSel(selFor(b, first));
        }
        restored.current = true;
        setLoading(false);
      })
      .catch((e) => {
        if (!isAbortError(e)) {
          setError(errorMessage(e));
          setLoading(false);
        }
      });
    return () => ctrl.abort();
  }, []);

  const touch = useCallback(() => setProfiles((ps) => [...ps]), []);

  /** Move to another stackup without losing either side's work.
   *
   *  The open set is parked under the stackup it was built on, and whatever was left
   *  on the stackup being opened comes back. Carrying the profiles across instead
   *  would keep cells for copper layers the new stackup does not have, and the next
   *  save would claim they had been solved against it. */
  const switchStackup = useCallback(
    (id: string) => {
      if (id === stackupId) return;
      const target = stackups.find((s) => s.id === id);
      if (!target) return;
      setBank((old) => {
        const next = { ...old };
        if (stackupId && profiles.length)
          next[stackupId] = { profiles, selProfile: sel?.profile, selLayer: sel?.layer };
        return next;
      });
      const bench = bank[id]?.profiles?.length ? bank[id] : freshBench(target);
      setProfiles(bench.profiles);
      setSel(selFor(bench, target));
      setStackupId(id);
      invalidate();
    },
    // `invalidate` is declared below and is stable; profiles/sel are read, not tracked
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stackupId, stackups, profiles, sel, bank],
  );

  // ------------------------------------------------------------- workspace
  // Written back debounced, the same 700 ms the sketch editor autosaves at. A solve
  // result travels with its profile's cells, so reopening the page shows the numbers
  // again without re-solving — only the field picture needs a run.
  useEffect(() => {
    if (!restored.current || loading) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      const body: SavedWorkspace = {
        stackupId,
        ruleId,
        epsModel,
        byStackup: {
          ...bank,
          ...(stackupId && profiles.length
            ? { [stackupId]: { profiles, selProfile: sel?.profile, selLayer: sel?.layer } }
            : {}),
        },
      };
      fsPutWorkspace(body).catch(() => {
        /* losing scratch space must never interrupt the work on screen */
      });
    }, 700);
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
  }, [stackupId, ruleId, epsModel, profiles, sel, bank, loading]);

  /** Anything that changes the geometry invalidates the result shown for it. */
  const invalidate = useCallback(() => {
    setResult(null);
    setFrames([]);
    setSearch(null);
    if (profile && sel) {
      const c = profile.cells[sel.layer];
      if (c) c.result = null;
    }
    touch();
  }, [profile, sel, touch]);

  // -------------------------------------------------------------- preview
  useEffect(() => {
    if (!profile || !stackup || !sel) return;
    const ctrl = new AbortController();
    const params = cellParams(profile, stackup, sel.layer);
    const t = window.setTimeout(() => {
      fsGeometry(params, ctrl.signal)
        .then((g) => setGeometry(g))
        .catch((e) => {
          if (!isAbortError(e)) setError(errorMessage(e));
        });
      if (ruleId) {
        fsCheck(params, ruleId, ctrl.signal)
          .then(setWarnings)
          .catch(() => undefined);
      }
    }, 200);
    return () => {
      window.clearTimeout(t);
      ctrl.abort();
    };
    // profiles is in the deps so edits to the selected cell re-run the preview
  }, [profile, stackup, sel, ruleId, profiles]);

  // ----------------------------------------------------------------- paint
  useEffect(() => {
    const cv = canvasRef.current;
    const g = result?.geometry ?? geometry;
    if (!cv || !g) return;
    const vp = viewport ?? fitView(g);
    if (!viewport) setViewport(vp);
    const field = result?.field ?? null;
    const shown = frames[frameIdx];
    const patched =
      field && shown ? { ...field, phi: shown.phi, i_signal: shown.i_signal } : field;
    drawCrossSection({
      canvas: cv,
      geometry: g,
      field: patched,
      view,
      viewport: vp,
      label: result ? undefined : "Configured geometry, not solved.",
    });
  }, [geometry, result, frames, frameIdx, view, viewport]);

  useEffect(() => {
    // Nudge every stored viewport so the paint effect re-runs at the new size.
    const onResize = () =>
      setViewports((prev) =>
        Object.fromEntries(Object.entries(prev).map(([k, v]) => [k, { ...v }])),
      );
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // ------------------------------------------------------------------ runs
  const solveCell = useCallback(
    async (p: Profile, st: FsStackup, layer: string) => {
      const [lo, hi] = sweepRange(p);
      setFrames([]);
      const r = await job.run<FsResult>(
        "solve",
        {
          params: cellParams(p, st, layer),
          f_design: p.f,
          f_min: lo,
          f_max: hi,
          n_freq: sweepPoints(p),
          eps_model: epsModel,
        },
        {
          steps: SOLVE_STEPS,
          onPartial: (res) => {
            setResult(res);
            if (res.field) {
              setFrames([
                {
                  f: p.f,
                  phi: res.field.phi,
                  i_signal: res.field.i_signal,
                  z: res.summary.Z0 ?? res.summary.Zodd,
                  eps_eff: res.summary.eps_eff ?? res.summary.eps_eff_odd,
                },
              ]);
            }
          },
          onFrame: (f) =>
            setFrames((old) => {
              const i = old.findIndex((x) => Math.abs(x.f - f.f) < 1);
              const next = i >= 0 ? old.map((x, k) => (k === i ? f : x)) : [...old, f];
              return next.sort((a, b) => a.f - b.f);
            }),
        },
      );
      if (!r) return null;
      const c = cellOf(p, st, layer);
      c.result = { ...r.summary, Cm: r.design.C, Lm: r.design.L, C0m: r.C0 };
      setResult(r);
      setFrames((old) => {
        const i = old.findIndex((x) => Math.abs(x.f - p.f) < 1);
        setFrameIdx(Math.max(0, i));
        return old;
      });
      touch();
      return r;
    },
    [epsModel, job, touch],
  );

  const reverse = useCallback(async () => {
    if (!profile || !stackup || !sel) return;
    setError("");
    try {
      await solveCell(profile, stackup, sel.layer);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [profile, stackup, sel, solveCell]);

  const forward = useCallback(async () => {
    if (!profile || !stackup || !sel || !cell) return;
    setError("");
    setSearch(null);
    const v = profile.type === "single" ? "w" : cell.lock === "w" ? (profile.type === "diff" ? "s" : "gap") : "w";
    const [glo, ghi] = profile.ranges[v] ?? [0.05, 3];
    try {
      const r = await job.run<Record<string, number> & { ok: boolean; reason?: string }>(
        "goal-seek",
        {
          params: cellParams(profile, stackup, sel.layer),
          f_design: profile.f,
          key: zKey(profile),
          target: profile.target,
          var: v,
          lo: glo,
          hi: ghi,
        },
        { steps: [{ key: "seek", label: `Find ${v} for ${profile.target} Ω` }, ...SOLVE_STEPS] },
      );
      if (!r) return;
      if (!r.ok) {
        setError(r.reason ?? "no solution in range");
        return;
      }
      (cell as unknown as Record<string, number>)[v] = Number(r[v].toFixed(4));
      touch();
      await solveCell(profile, stackup, sel.layer);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [profile, stackup, sel, cell, job, solveCell, touch]);

  const runSearch = useCallback(async () => {
    if (!profile || !stackup || !sel || !cell) return;
    setError("");
    setSearch(null);
    setSearchFolded(false);
    cell.enabled = true;
    const outer = copperLayers(stackup)[0]?.name === sel.layer;
    const masks = cell.mask_mode === "both" ? [true, false] : [maskOn(cell)];
    try {
      const r = await job.run<FsSearchResult>(
        "search",
        {
          params: cellParams(profile, stackup, sel.layer, true),
          f_design: profile.f,
          target: profile.target,
          tolerance_pct: profile.tolerance,
          ranges: profile.ranges,
          step: profile.step,
          masks: outer ? masks : [false],
        },
        { steps: [{ key: "variants", label: "Solve the candidate grid" }] },
      );
      if (r) setSearch(r);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [profile, stackup, sel, cell, job]);

  const applyRow = useCallback(
    async (row: FsSearchRow) => {
      if (!profile || !stackup || !sel || !cell) return;
      cell.w = row.w;
      if (row.gap != null) cell.gap = row.gap;
      if (row.s != null) cell.s = row.s;
      if (row.fence_distance != null) cell.fence_distance = row.fence_distance;
      if (row.via_rows) row.via_rows.forEach((v, i) => cell.via_rows[i] && (cell.via_rows[i].pitch = v));
      cell.mask_mode = row.soldermask ? "on" : "off";
      cell.enabled = true;
      setSearchFolded(true);
      touch();
      await reverse();
    },
    [profile, stackup, sel, cell, touch, reverse],
  );

  // ---------------------------------------------------------------- canvas
  // A locked view returns without cancelling the event, so the wheel scrolls
  // the page as usual. An unlocked one cancels it, or the page scrolls under
  // the cross-section and a touchpad pinch zooms the browser as well.
  const onWheel = (e: WheelEvent) => {
    if (locked || !viewport) return;
    e.preventDefault();
    const f = Math.exp(e.deltaY * 0.0015);
    setViewport({ ...viewport, halfw: Math.max(0.02, Math.min(200, viewport.halfw * f)) });
  };
  const canvasCb = useWheel(canvasRef, onWheel);
  const drag = useRef<{ x: number; y: number; vp: View } | null>(null);
  const onDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (locked || !viewport) return;
    drag.current = { x: e.clientX, y: e.clientY, vp: viewport };
  };
  const onMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    const cv = canvasRef.current;
    if (!d || !cv) return;
    const box = cv.getBoundingClientRect();
    const per = (2 * d.vp.halfw) / box.width;
    setViewport({ ...d.vp, cx: d.vp.cx - (e.clientX - d.x) * per, cy: d.vp.cy + (e.clientY - d.y) * per });
  };
  const endDrag = () => {
    drag.current = null;
  };

  if (loading) return <Spinner label="Loading the stackup library" />;
  if (!stackup || !profile || !sel || !cell) return <ErrorBanner message={error || "No stackup available."} />;

  const cu = copperLayers(stackup);
  const { above, below } = refOptions(stackup, sel.layer);
  const summary = result?.summary;
  const pair = isPair(profile);
  const [rlo, rhi] = sweepRange(profile);

  const setProfile = (patch: Partial<Profile>, invalidateResult = true) => {
    Object.assign(profile, patch);
    refreshName(profile);
    if (invalidateResult) invalidate();
    else touch();
  };
  const setCell = (patch: Partial<Cell>) => {
    Object.assign(cell, patch);
    invalidate();
  };

  const searchRows = (() => {
    if (!search) return [];
    const rows = search.rows.map((r, i) => ({ r, i }));
    if (!searchSort) return rows;
    const key = searchSort.col;
    const val = (r: FsSearchRow): number => {
      if (key === "mask") return r.soldermask ? 1 : 0;
      if (key === "dev") return Math.abs(r.dev_pct);
      if (key === "loss") return (r.alpha_db_m ?? r.alpha_odd_db_m ?? 0) / 10;
      if (key === "rows") return r.via_rows?.[0] ?? 0;
      return Number(r[key] ?? -Infinity);
    };
    return rows.sort((a, b) => (val(a.r) - val(b.r)) * searchSort.dir);
  })();

  const toggleSort = (col: string) =>
    setSearchSort((s) => (s && s.col === col ? (s.dir > 0 ? { col, dir: -1 } : null) : { col, dir: 1 }));

  const shownFrame = frames[frameIdx];

  return (
    <div className="fs-page">
      {error ? <ErrorBanner message={error} /> : null}

      {/* ---------------------------------------------------------- board */}
      <section className="card pad fs-board">
        <div className="fs-board-cards">
          <label className="field">
            <span>Stackup</span>
            <span className="field-inline">
              <select className="text" value={stackupId} onChange={(e) => switchStackup(e.target.value)}>
                {stackups.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.builtin ? "" : "★ "}
                    {s.manufacturer} {s.name}
                  </option>
                ))}
              </select>
              {isAdmin ? (
                <button type="button" className="btn btn-sm" onClick={() => setEditStackup(true)}>
                  edit
                </button>
              ) : null}
            </span>
            <span className="muted fs-note">
              {cu.length} layers · {stackup.total_mm.toFixed(3)} mm ·{" "}
              {stackup.soldermask ? "mask" : "no mask"} ·{" "}
              {stackup.finish ? `${stackup.finish.type} ${stackup.finish.thickness_um} µm` : "no finish"}
              {stackup.verified ? "" : " · not published by the fab"}
            </span>
          </label>
          <label className="field">
            <span>Production rules</span>
            <span className="field-inline">
              <select className="text" value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
                {rules.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.builtin ? "" : "★ "}
                    {r.name}
                  </option>
                ))}
              </select>
              <button type="button" className="btn btn-sm" onClick={() => setEditRules(true)}>
                edit
              </button>
            </span>
            {warnings.length ? <span className="fs-warn">{warnings.join(" · ")}</span> : null}
          </label>
        </div>

        {/* The stackup, drawn by the SAME visualiser the project page compares one
            with (components/StackupTable.tsx). One picture of a stackup across the
            platform: a layer that reads as core here reads as core there. The
            impedance profiles ride along as extra columns, and a click on a copper
            row picks the layer the properties panel edits. */}
        <StackupTable
          rows={stackup.stack}
          mode="single"
          side="stackup"
          selectedCopper={sel.layer}
          onSelectCopper={(name) => {
            setSel({ profile: sel.profile, layer: name });
            setResult(null);
            setFrames([]);
            setSearch(null);
          }}
          extraColumns={profiles.map((p) => ({
            key: String(p.id),
            // Remove sits on the LEFT of the header: the profile's own summary is as
            // long as the column allows and truncates, so a button after it is the
            // first thing the ellipsis eats.
            header: (
              <span className="fs-prof">
                {profiles.length > 1 ? (
                  <button
                    type="button"
                    className="btn btn-sm fs-prof-del"
                    title={`Remove ${p.name}`}
                    aria-label={`Remove ${p.name}`}
                    onClick={async (e) => {
                      e.stopPropagation();
                      // A profile is a target, a geometry per copper layer and, often,
                      // a solve that took minutes. Removing one on a single click is
                      // not proportionate to what it costs to rebuild.
                      const solved = Object.values(p.cells ?? {}).filter((c) => c?.result).length;
                      if (
                        !(await dialog.confirm(
                          `Remove the impedance profile “${p.name}”? Its target, the geometry on every ` +
                            `copper layer and ${solved ? `${solved} solved result${solved === 1 ? "" : "s"}` : "any work on it"} ` +
                            `go with it, and nothing here can bring them back.`,
                          { title: "Remove profile", confirmLabel: "Remove", tone: "danger" },
                        ))
                      )
                        return;
                      setProfiles((ps) => ps.filter((q) => q.id !== p.id));
                      if (sel.profile === p.id) setSel({ profile: profiles[0].id, layer: sel.layer });
                    }}
                  >
                    ×
                  </button>
                ) : null}
                <span className="fs-prof-text" title={`${p.name} · ${TYPE_LABEL[p.type]} · ${p.target} Ω ±${p.tolerance}% · ${fmtHz(p.f)}`}>
                  {p.name}
                  <span className="muted">
                    {" · "}
                    {TYPE_LABEL[p.type]} · {p.target} Ω ±{p.tolerance}% · {fmtHz(p.f)}
                  </span>
                </span>
              </span>
            ),
            cell: (row) => {
              if (row.kind !== "copper") return null;
              const name = row.stackup?.name ?? "";
              if (!name) return null;
              const c = cellOf(p, stackup, name);
              const selected = sel.profile === p.id && sel.layer === name;
              const r = c.result as Record<string, number> | null | undefined;
              const z = r ? (r.Z0 ?? r.Zdiff) : null;
              // One line, like every other row in the table: checkbox, width, the
              // reference pair and the mask, then the solved impedance. It stacked
              // onto two lines before, which made every copper row twice as tall as
              // the dielectric rows between them and broke the stackup's rhythm.
              const refs = `${c.top_ref}/${c.bottom_ref}`;
              const mask = c.mask_mode === "both" ? "mask?" : maskOn(c) ? "mask" : "no mask";
              const summary = `W1 ${fmt(c.w, 3)} mm · ${refs} · ${mask}${c.via_fence ? " · fence" : ""}${
                z != null ? ` · ${zKey(p)} ${fmt(z, 1)} Ω` : ""
              }`;
              return (
                <span
                  className={`fs-cell${selected ? " on" : ""}`}
                  title={summary}
                  onClick={() => {
                    setSel({ profile: p.id, layer: name });
                    setResult(null);
                    setFrames([]);
                    setSearch(null);
                  }}
                >
                  <input
                    type="checkbox"
                    checked={c.enabled}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => {
                      c.enabled = e.target.checked;
                      touch();
                    }}
                  />
                  <b>W1 {fmt(c.w, 3)} mm</b>
                  <span className="muted">
                    {" · "}
                    {refs} · {mask}
                    {c.via_fence ? " · fence" : ""}
                  </span>
                  {z != null ? (
                    <span className="fs-z">
                      {" · "}
                      {zKey(p)} {fmt(z, 1)} Ω
                    </span>
                  ) : null}
                </span>
              );
            },
          }))}
          trailingColumn={{
            cell: (
              <button
                type="button"
                className="btn btn-sm stk-add-btn"
                title="Add an impedance profile"
                onClick={() => {
                  const p = newProfile(profiles.length);
                  setProfiles((ps) => [...ps, p]);
                  setSel({ profile: p.id, layer: cu[0].name as string });
                }}
              >
                <span className="stk-add-plus" aria-hidden="true">
                  +
                </span>
                <span className="stk-add-label">add profile</span>
              </button>
            ),
          }}
        />
        <StackupLegend />
      </section>

      <div className="fs-lower">
        {/* ------------------------------------------------------ properties */}
        <aside className="card pad fs-props">
          <h2 className="card-title">
            {profile.name} · {sel.layer}
          </h2>

          <fieldset className="fieldset">
            <legend>1 · Profile</legend>
            <label className="field">
              <span>Name</span>
              <input
                className="text"
                value={profile.name}
                onChange={(e) => {
                  profile.name = e.target.value;
                  profile.autoName = false;
                  touch();
                }}
              />
            </label>
            <label className="field">
              <span>Signal</span>
              <span className="seg" role="group" aria-label="Signal type">
                {(["single", "diff"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    className={(pair ? "diff" : "single") === m ? "on" : ""}
                    onClick={() => setProfile({ type: lineType(m, isCpw(profile)) })}
                  >
                    {m === "single" ? "Single-ended" : "Differential"}
                  </button>
                ))}
              </span>
            </label>
            {/* A segmented pair, not a checkbox: it sits directly under Signal,
                which is the same kind of choice about the same geometry, and two
                controls that decide what the cross-section IS should not be two
                different shapes. */}
            <label className="field">
              <span>Coplanar</span>
              <span className="seg" role="group" aria-label="Coplanar">
                {([false, true] as const).map((on) => (
                  <button
                    key={String(on)}
                    type="button"
                    className={isCpw(profile) === on ? "on" : ""}
                    title={
                      on
                        ? "Ground pour beside the trace on the signal layer"
                        : "No side ground on the signal layer"
                    }
                    onClick={() => setProfile({ type: lineType(pair ? "diff" : "single", on) })}
                  >
                    {on ? "On" : "Off"}
                  </button>
                ))}
              </span>
            </label>
            <div className="field-row">
              <label className="field">
                <span>Target Z</span>
                <SiInput
                  className="fs-num"
                  quantity="resistance"
                  value={profile.target}
                  onChange={(v) => setProfile({ target: v }, false)}
                  help={
                    <>
                      A bare number is ohms. Prefixes only — <b>10M</b> is 10 MΩ, <b>4.7k</b> is 4700 Ω.
                      Case matters here: <b>m</b> is milli.
                    </>
                  }
                />
              </label>
              <label className="field">
                <span>Tolerance</span>
                <SiInput
                  className="fs-num"
                  quantity="percent"
                  value={profile.tolerance}
                  min={0}
                  max={100}
                  onChange={(v) => setProfile({ tolerance: v }, false)}
                  help={<>A bare number is percent. ±3% of the target is the usual fab window.</>}
                />
              </label>
              <label className="field">
                <span>Design f</span>
                <SiInput
                  className="fs-num"
                  quantity="frequency"
                  value={profile.f}
                  min={F_FLOOR}
                  max={F_CEIL}
                  onChange={(v) => setProfile({ f: Math.min(F_CEIL, Math.max(F_FLOOR, v)) })}
                  help={
                    <>
                      Type any unit: 2.4GHz, 2400MHz, 2.4e9. A bare number means Hz. The solver is quasi-TEM and is
                      floored at 1 MHz.
                    </>
                  }
                />
              </label>
            </div>
            <details className="fs-details">
              <summary>Frequency sweep range and resolution</summary>
              <div className="field-row">
                <label className="field">
                  <span>Range</span>
                  <select
                    className="text"
                    value={profile.frange}
                    onChange={(e) => setProfile({ frange: e.target.value as Profile["frange"] }, false)}
                  >
                    <option value="auto">auto</option>
                    <option value="custom">manual</option>
                  </select>
                </label>
                {profile.frange === "custom" ? (
                  <>
                    <label className="field">
                      <span>from</span>
                      <SiInput
                        className="fs-num"
                        quantity="frequency"
                        value={profile.fr0}
                        min={F_FLOOR}
                        max={F_CEIL}
                        onChange={(v) => setProfile({ fr0: v }, false)}
                        help={<>Type any unit: 100MHz, 1e8, 0.1GHz. A bare number means Hz.</>}
                      />
                    </label>
                    <label className="field">
                      <span>to</span>
                      <SiInput
                        className="fs-num"
                        quantity="frequency"
                        value={profile.fr1}
                        min={F_FLOOR}
                        max={F_CEIL}
                        onChange={(v) => setProfile({ fr1: v }, false)}
                        help={<>Type any unit: 100MHz, 1e8, 0.1GHz. A bare number means Hz.</>}
                      />
                    </label>
                  </>
                ) : null}
                <label className="field">
                  <span>points / decade</span>
                  <NumberInput
                    className="text fs-num"
                    min={2}
                    max={20}
                    value={perDecade(profile)}
                    onChange={(v) => setProfile({ ppd: v }, false)}
                  />
                </label>
              </div>
              <p className="muted fs-note">
                {fmtHz(rlo)} … {fmtHz(rhi)} · {sweepPoints(profile)} points. The solver is quasi-TEM, so nothing below
                1 MHz is offered.
              </p>
            </details>
          </fieldset>

          <fieldset className="fieldset">
            <legend>2 · Layer {sel.layer} and references</legend>
            <div className="field-row">
              <label className="field">
                <span>Top Ref</span>
                <select
                  className="text"
                  value={above.some((l) => l.name === cell.top_ref) ? cell.top_ref : "none"}
                  disabled={!above.length}
                  onChange={(e) => setCell({ top_ref: e.target.value })}
                >
                  <option value="none">none</option>
                  {above.map((l) => (
                    <option key={l.name} value={l.name as string}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Bottom Ref</span>
                <select
                  className="text"
                  value={below.some((l) => l.name === cell.bottom_ref) ? cell.bottom_ref : "none"}
                  disabled={!below.length}
                  onChange={(e) => setCell({ bottom_ref: e.target.value })}
                >
                  <option value="none">none</option>
                  {below.map((l) => (
                    <option key={l.name} value={l.name as string}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </fieldset>

          <fieldset className="fieldset">
            <legend>3 · Structure</legend>
            <table className="data fs-dims">
              {/* No trailing "mm" column: each SiInput prints the unit it is
                  showing INSIDE the box (and switches to um under 50 um), so a
                  fixed column saying mm was both redundant and wrong at small
                  values — and it was taking 26 px from the label column, which
                  is what clipped "Gap to coplanar GND" in this narrow panel. */}
              <thead>
                <tr>
                  <th />
                  <th>min</th>
                  <th>max</th>
                </tr>
              </thead>
              <tbody>
                {(
                  [
                    ["w", "Trace width W1"],
                    ...(pair ? ([["s", "Pair spacing S"]] as [string, string][]) : []),
                    ...(isCpw(profile) ? ([["gap", "Gap to coplanar GND"]] as [string, string][]) : []),
                    ...(cell.via_fence && cell.fence_mode === "range"
                      ? ([["fence", "Fence distance"]] as [string, string][])
                      : []),
                  ] as [string, string][]
                ).map(([k, label]) => (
                  <tr key={k}>
                    <td>{label}</td>
                    {[0, 1].map((j) => (
                      <td key={j}>
                        <SiInput
                          className="fs-num"
                          min={0}
                          value={profile.ranges[k]?.[j] ?? 0}
                          help={<>Type any unit: 0.2, 200um, 7.9mil. A bare number means mm.</>}
                          onChange={(v) => {
                            const r = profile.ranges[k] ?? [0, 1];
                            r[j] = v;
                            profile.ranges[k] = r as [number, number];
                            touch();
                          }}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>

            <label className="field">
              <span>Solder mask over the structure</span>
              <select
                className="text"
                value={cell.mask_mode}
                onChange={(e) => setCell({ mask_mode: e.target.value as Cell["mask_mode"] })}
                disabled={cu[0]?.name !== sel.layer || !stackup.soldermask}
              >
                <option value="on">on — structure covered by mask</option>
                <option value="off">off — mask opening, finish on the copper</option>
                <option value="both">check both</option>
              </select>
            </label>

            <label className="field-check">
              <input type="checkbox" checked={cell.via_fence} onChange={(e) => setCell({ via_fence: e.target.checked })} />
              Fence vias along the structure
            </label>
            {cell.via_fence ? (
              <div className="fs-sub">
                <div className="field-row">
                  <label className="field">
                    <span>hole</span>
                    <SiInput
                      className="fs-num"
                      value={cell.via_hole}
                      min={0}
                      onChange={(v) => setCell({ via_hole: v })}
                      help={<>Type any unit: 0.2, 200um, 7.9mil. A bare number means mm.</>}
                    />
                  </label>
                  <label className="field">
                    <span>pad ⌀</span>
                    <SiInput
                      className="fs-num"
                      value={cell.via_pad}
                      min={0}
                      onChange={(v) => setCell({ via_pad: v })}
                      help={<>Type any unit: 0.2, 200um, 7.9mil. A bare number means mm.</>}
                    />
                  </label>
                  <label className="field">
                    <span>position</span>
                    <select
                      className="text"
                      value={cell.fence_mode}
                      onChange={(e) => setCell({ fence_mode: e.target.value as Cell["fence_mode"] })}
                    >
                      <option value="range">from range</option>
                      <option value="exact">exact</option>
                    </select>
                  </label>
                  {cell.fence_mode === "exact" ? (
                    <label className="field">
                      <span>distance</span>
                      <SiInput
                        className="fs-num"
                        value={cell.fence_distance}
                        min={0}
                        onChange={(v) => setCell({ fence_distance: v })}
                        help={<>Type any unit: 0.2, 200um, 7.9mil. A bare number means mm.</>}
                      />
                    </label>
                  ) : null}
                </div>
                <div className="field-row">
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setCell({ via_rows: [...cell.via_rows, { mode: "rel", pitch: minPitch(cell, ruleset) }] })}
                  >
                    + extra via row
                  </button>
                  {cell.via_rows.map((r, i) => (
                    <label key={i} className="field">
                      <span>row {i + 2} pitch</span>
                      <SiInput
                        className="fs-num"
                        min={0}
                        value={r.pitch}
                        help={<>Type any unit: 0.6, 600um, 23.6mil. A bare number means mm.</>}
                        onChange={(v) => {
                          cell.via_rows[i] = { ...r, pitch: v };
                          invalidate();
                        }}
                      />
                    </label>
                  ))}
                </div>
              </div>
            ) : null}

            <label className="field-check">
              <input type="checkbox" checked={cell.use_w2} onChange={(e) => setCell({ use_w2: e.target.checked })} />
              Etched trapezoid (top narrower than W1)
            </label>
            {cell.use_w2 ? (
              <label className="field fs-sub">
                <span>undercut per side</span>
                <SiInput
                  className="fs-num"
                  assume="um"
                  fixedUnit="um"
                  min={0}
                  value={(cell.etch_um ?? Number(ruleset?.etch_outer_um ?? 12.5)) / 1000}
                  onChange={(v) => {
                    const um = v * 1000;
                    setCell({ etch_um: um });
                  }}
                  help={<>Type any unit: 12.5, 12.5um, 0.0125mm. A bare number means um here.</>}
                />
              </label>
            ) : null}

            <label className="field-check">
              <input type="checkbox" checked={cell.use_rough} onChange={(e) => setCell({ use_rough: e.target.checked })} />
              Copper roughness (Hammerstad)
            </label>
            {cell.use_rough ? (
              <label className="field fs-sub">
                <span>RMS</span>
                <SiInput
                  className="fs-num"
                  assume="um"
                  fixedUnit="um"
                  min={0}
                  value={(cell.roughness_um) / 1000}
                  onChange={(v) => {
                    const um = v * 1000;
                    setCell({ roughness_um: um });
                  }}
                  help={<>Type any unit: 12.5, 12.5um, 0.0125mm. A bare number means um here.</>}
                />
              </label>
            ) : null}
          </fieldset>

          <fieldset className="fieldset">
            <legend>4 · Find solutions</legend>
            <div className="field-row">
              <label className="field">
                <span>Snap drawn features to</span>
                <select
                  className="text"
                  value={profile.step == null ? "" : String(profile.step)}
                  onChange={(e) => setProfile({ step: e.target.value ? Number(e.target.value) : null }, false)}
                >
                  <option value="0.1">0.1 mm grid</option>
                  <option value="0.05">0.05 mm grid</option>
                  <option value="0.025">0.025 mm grid</option>
                  <option value="">no grid (exact)</option>
                </select>
              </label>
              <label className="field">
                <span>Dk model</span>
                <select className="text" value={epsModel} onChange={(e) => setEpsModel(e.target.value)}>
                  <option value="djordjevic">Djordjevic-Sarkar</option>
                  <option value="constant">constant</option>
                </select>
              </label>
            </div>
            <div className="field-row">
              <button type="button" className="btn btn-accent" onClick={runSearch} disabled={job.state.running}>
                Find solutions
              </button>
              <button type="button" className="btn" onClick={forward} disabled={job.state.running}>
                Exact width for the target
              </button>
            </div>
          </fieldset>

          <fieldset className="fieldset">
            <legend>5 · Resulting dimensions</legend>
            <div className="field-row">
              <label className="field">
                <span>Width W1</span>
                <SiInput
                  className="fs-num"
                  value={cell.w}
                  min={0}
                  onChange={(v) => setCell({ w: v })}
                  help={<>Type any unit: 0.2, 200um, 7.9mil. A bare number means mm.</>}
                />
              </label>
              {pair ? (
                <label className="field">
                  <span>Spacing S</span>
                  <SiInput
                    className="fs-num"
                    value={cell.s}
                    min={0}
                    onChange={(v) => setCell({ s: v })}
                    help={<>Type any unit: 0.2, 200um, 7.9mil. A bare number means mm.</>}
                  />
                </label>
              ) : null}
              {isCpw(profile) ? (
                <label className="field">
                  <span>Gap</span>
                  <SiInput
                    className="fs-num"
                    value={cell.gap}
                    min={0}
                    onChange={(v) => setCell({ gap: v })}
                    help={<>Type any unit: 0.2, 200um, 7.9mil. A bare number means mm.</>}
                  />
                </label>
              ) : null}
            </div>
            <button type="button" className="btn" onClick={reverse} disabled={job.state.running}>
              Calculate Z from these dimensions
            </button>
          </fieldset>

          <fieldset className="fieldset">
            <legend>Result: transmission line</legend>
            <table className="data fs-kv">
              <tbody>
                {(pair
                  ? [
                      ["Zdiff", summary?.Zdiff, "Ω", 2],
                      ["Zodd", summary?.Zodd, "Ω", 2],
                      ["Zeven", summary?.Zeven, "Ω", 2],
                      ["Zcomm", summary?.Zcomm, "Ω", 2],
                      ["Z0 single", summary?.Z0_single, "Ω", 2],
                      ["Coupling k", summary?.coupling_k, "", 3],
                      ["εeff odd", summary?.eps_eff_odd, "", 3],
                      ["Tp odd", summary?.delay_odd_ps_per_mm, "ps/mm", 3],
                      ["Loss odd at f", (summary?.alpha_odd_db_m ?? NaN) / 10, "dB/cm", 4],
                    ]
                  : [
                      ["Impedance Z", summary?.Z0, "Ω", 2],
                      ["Z deviation", summary?.Z0 != null ? ((summary.Z0 - profile.target) / profile.target) * 100 : null, "%", 1],
                      ["εeff", summary?.eps_eff, "", 3],
                      ["Propagation delay", summary?.delay_ps_per_mm, "ps/mm", 3],
                      ["Loss at f", (summary?.alpha_db_m ?? NaN) / 10, "dB/cm", 4],
                      ["  conductor", (summary?.alpha_c_db_m ?? NaN) / 10, "dB/cm", 4],
                      ["  dielectric", (summary?.alpha_d_db_m ?? NaN) / 10, "dB/cm", 4],
                    ]
                ).map(([label, v, unit, dec]) => (
                  <tr key={String(label)} className={summary ? "" : "fs-empty"}>
                    <td>{label as string}</td>
                    <td>
                      {fmt(v as number, dec as number)} {unit as string}
                    </td>
                  </tr>
                ))}
                {result ? (
                  <>
                    <tr>
                      <td>C p.u.l.</td>
                      <td>{fmt(result.design.C[0][0] * 1e12, 1)} pF/m</td>
                    </tr>
                    <tr>
                      <td>L p.u.l.</td>
                      <td>{fmt(result.design.L[0][0] * 1e9, 1)} nH/m</td>
                    </tr>
                    <tr>
                      <td>C0 p.u.l. (air)</td>
                      <td>{fmt(result.C0[0][0] * 1e12, 1)} pF/m</td>
                    </tr>
                  </>
                ) : null}
              </tbody>
            </table>
          </fieldset>
        </aside>

        {/* --------------------------------------------------------- results */}
        <div className="fs-results">
          <section className="card pad">
            <h2 className="card-title fs-foldh" onClick={() => setSearchFolded((f) => !f)}>
              {searchFolded ? "▸" : "▾"} Solutions
            </h2>
            {!searchFolded ? (
              search ? (
                <>
                  <table className="data fs-solutions">
                    <thead>
                      <tr>
                        {[
                          ["mask", "mask"],
                          ...(search.rows.some((r) => r.gap != null) ? [["gap", "gap"]] : []),
                          ...(search.rows.some((r) => r.s != null) ? [["s", "S"]] : []),
                          ...(search.rows.some((r) => r.fence_distance != null) ? [["fence_distance", "fence"]] : []),
                          ["w", "W1"],
                          [search.key, search.key],
                          ["dev", "dev"],
                          ["loss", "loss dB/cm"],
                        ].map(([col, label]) => (
                          <th key={col} className="fs-sortable" onClick={() => toggleSort(col)}>
                            {label}
                            {searchSort?.col === col ? (searchSort.dir > 0 ? " ▲" : " ▼") : ""}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {searchRows.map(({ r, i }) => (
                        <tr
                          key={i}
                          className={r.within ? "fs-pick" : "fs-bad"}
                          onClick={() => (r.within ? applyRow(r) : undefined)}
                        >
                          <td>{r.soldermask ? "yes" : "no"}</td>
                          {search.rows.some((x) => x.gap != null) ? <td>{fmt(r.gap, 3)}</td> : null}
                          {search.rows.some((x) => x.s != null) ? <td>{fmt(r.s, 3)}</td> : null}
                          {search.rows.some((x) => x.fence_distance != null) ? <td>{fmt(r.fence_distance, 3)}</td> : null}
                          <td>{fmt(r.w, 3)}</td>
                          <td>{fmt(r[search.key] as number)}</td>
                          <td>
                            {r.dev_pct >= 0 ? "+" : ""}
                            {fmt(r.dev_pct, 1)} %
                          </td>
                          <td>{fmt((r.alpha_db_m ?? r.alpha_odd_db_m ?? NaN) / 10, 4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="muted fs-note">
                    {search.rows.filter((r) => r.within).length} of {search.rows.length} candidates inside ±
                    {search.tolerance_pct} %. {search.note} Click a row to use it.
                  </p>
                </>
              ) : (
                <p className="muted fs-note">
                  No search run yet — press <b>Find solutions</b> to list candidate geometries for the target. The view
                  below shows the one geometry that is currently applied.
                </p>
              )
            ) : null}
          </section>

          <section className="cards fs-summary">
            {(pair
              ? [
                  ["Zdiff", summary?.Zdiff, "Ω", 2],
                  ["Zodd", summary?.Zodd, "Ω", 2],
                  ["Zeven", summary?.Zeven, "Ω", 2],
                  ["εeff odd", summary?.eps_eff_odd, "", 3],
                  ["loss odd", (summary?.alpha_odd_db_m ?? NaN) / 10, "dB/cm", 4],
                ]
              : [
                  ["Z0", summary?.Z0, "Ω", 2],
                  ["εeff", summary?.eps_eff, "", 3],
                  ["delay", summary?.delay_ps_per_mm, "ps/mm", 3],
                  ["loss", (summary?.alpha_db_m ?? NaN) / 10, "dB/cm", 4],
                  ["conductor", (summary?.alpha_c_db_m ?? NaN) / 10, "dB/cm", 4],
                ]
            ).map(([k, v, u, d]) => (
              <div key={String(k)} className={`card fs-card${summary ? "" : " fs-empty"}`}>
                <div className="fs-card-k">{k as string}</div>
                <div className="fs-card-v">{fmt(v as number, d as number)}</div>
                <div className="fs-card-u">{u as string}</div>
              </div>
            ))}
            <div className={`card fs-card${result ? "" : " fs-empty"}`}>
              <div className="fs-card-k">mesh</div>
              <div className="fs-card-v">{result ? result.mesh.nodes : "–"}</div>
              <div className="fs-card-u">nodes</div>
            </div>
          </section>

          <section className="card pad">
            <h2 className="card-title fs-xs-head">
              Cross-section
              <select className="text" value={view} onChange={(e) => setView(e.target.value as FieldView)}>
                {VIEWS.map((v) => (
                  <option key={v.value} value={v.value}>
                    {v.label}
                  </option>
                ))}
              </select>
              <label className="field-check">
                <input type="checkbox" checked={locked} onChange={(e) => setLocked(e.target.checked)} />
                lock view
              </label>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setViewport(result?.geometry || geometry ? fitView((result?.geometry ?? geometry) as FsGeometry) : null)}
              >
                reset view
              </button>
            </h2>
            <div className="fs-xs-wrap">
              {frames.length > 1 ? (
                <div className="fs-slider">
                  <span>field at</span>
                  <input
                    type="range"
                    min={0}
                    max={frames.length - 1}
                    value={Math.min(frameIdx, frames.length - 1)}
                    onChange={(e) => setFrameIdx(Number(e.target.value))}
                  />
                  <b>
                    {shownFrame ? fmtHz(shownFrame.f) : ""}
                    {shownFrame?.z != null ? ` · Z ${fmt(shownFrame.z, 1)} Ω` : ""}
                    {shownFrame?.eps_eff != null ? ` · εeff ${fmt(shownFrame.eps_eff, 3)}` : ""} ({frames.length} solved)
                  </b>
                </div>
              ) : null}
              <canvas
                ref={canvasCb}
                className={`fs-canvas${locked ? "" : " fs-unlocked"}`}
                onMouseDown={onDown}
                onMouseMove={onMove}
                onMouseUp={endDrag}
                onMouseLeave={endDrag}
              />
              {job.state.running ? (
                <div className="fs-progress">
                  <ul className="fs-steps">
                    {job.state.steps.map((s, i) => (
                      <li key={s.key} className={i < job.state.current ? "done" : i === job.state.current ? "active" : "wait"}>
                        <span className="fs-ico">{i < job.state.current ? "✔" : i === job.state.current ? "▶" : "⏳"}</span>
                        {s.label}
                      </li>
                    ))}
                  </ul>
                  <div className="fs-msg">{job.state.message}</div>
                  <div className="fs-bar">
                    <i style={{ width: `${Math.round(job.state.fraction * 100)}%` }} />
                  </div>
                  <button type="button" className="btn btn-sm" onClick={job.cancel}>
                    Cancel
                  </button>
                </div>
              ) : null}
            </div>
            <p className="muted fs-note">
              {result
                ? "Solved mode (odd mode for a pair). Orange: signal. Grey: reference. Dashed: dielectric outlines."
                : "Configured geometry, not solved. Press 'Calculate Z from these dimensions' or 'Find solutions'."}
              {locked ? " Untick 'lock view' to zoom and pan." : " Wheel zooms, drag pans."}
            </p>
          </section>

          <section className="card pad">
            <h2 className="card-title">Loss and εeff against frequency</h2>
            {result && result.sweep.length > 1 ? (
              <>
                <Chart
                  series={[
                    {
                      name: pair ? "α total (odd)" : "α total",
                      x: result.sweep.map((s) => s.f),
                      y: result.sweep.map((s) => pickMode(s, pair).alpha_db_m / 10),
                      axis: "l",
                      color: "var(--sim-cold)",
                    },
                    {
                      name: "α conductor",
                      x: result.sweep.map((s) => s.f),
                      y: result.sweep.map((s) => pickMode(s, pair).alpha_c_db_m / 10),
                      axis: "l",
                      color: "var(--sim-cold)",
                      dash: "6 4",
                    },
                    {
                      name: "α dielectric",
                      x: result.sweep.map((s) => s.f),
                      y: result.sweep.map((s) => pickMode(s, pair).alpha_d_db_m / 10),
                      axis: "l",
                      color: "var(--sim-cold)",
                      dash: "2 3",
                    },
                    {
                      name: pair ? "εeff odd" : "εeff",
                      x: result.sweep.map((s) => s.f),
                      y: result.sweep.map((s) => pickMode(s, pair).eps_eff),
                      axis: "r",
                      color: "var(--sim-hot)",
                    },
                  ]}
                  xlabel="frequency, log scale"
                  ylabel="attenuation α (dB/cm)"
                  y2label="effective permittivity εeff (–)"
                  xfmt={fmtHz}
                  marks={[{ x: profile.f, label: `design ${fmtHz(profile.f)}` }]}
                />
                <table className="data fs-sweep">
                  <thead>
                    <tr>
                      <th>frequency</th>
                      <th>{pair ? "Zodd" : "Z0"} (Ω)</th>
                      <th>εeff</th>
                      <th>α (dB/cm)</th>
                      <th>α conductor</th>
                      <th>α dielectric</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.sweep.map((s) => {
                      const m = pickMode(s, pair);
                      return (
                        <tr key={s.f}>
                          <td>{fmtHz(s.f)}</td>
                          <td>{fmt(Object.values(m.z)[0] as number)}</td>
                          <td>{fmt(m.eps_eff, 3)}</td>
                          <td>{fmt(m.alpha_db_m / 10, 4)}</td>
                          <td>{fmt(m.alpha_c_db_m / 10, 4)}</td>
                          <td>{fmt(m.alpha_d_db_m / 10, 4)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </>
            ) : (
              <p className="muted fs-note">Loss and εeff appear after a calculation.</p>
            )}
          </section>

          {(result?.notes ?? geometry?.notes ?? []).length ? (
            <section className="card pad">
              <h2 className="card-title">Notes</h2>
              <ul className="fs-notes">
                {(result?.notes ?? geometry?.notes ?? []).map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </div>

      <ProjectPanel
        stackupKey={stackupId}
        profiles={profiles}
        initial={{
          projectId: params.get("project") ? Number(params.get("project")) : null,
          snapshotId: params.get("snapshot") ? Number(params.get("snapshot")) : null,
          board: params.get("board") ?? "",
        }}
        liveResult={
          result
            ? {
                profileId: profile.id,
                payload: {
                  // numbers only: a solved mesh is tens of megabytes and is cheap
                  // to redraw only by solving again
                  summary: result.summary,
                  design: result.design,
                  sweep: result.sweep,
                  C0: result.C0,
                  mesh: result.mesh,
                  notes: result.notes,
                  geometry: result.geometry,
                },
              }
            : null
        }
        onLoadProfile={(p: FsBoardProfile) => {
          const cfg = p.config as unknown as Profile;
          const restored: Profile = { ...cfg, id: profile.id, cells: cfg.cells ?? {} };
          setProfiles((ps) => ps.map((q) => (q.id === profile.id ? restored : q)));
          setResult(null);
          setFrames([]);
          setSearch(null);
          if (p.outdated) {
            setError(
              `“${p.name}” was solved against stackup ${p.stackup_key}, which is not what this board uses now — its numbers are kept for reference, but recalculate before trusting them.`,
            );
          }
        }}
      />

      {editStackup ? (
        <StackupEditor
          stackup={stackup}
          materials={materials}
          finishes={finishes}
          rules={ruleset}
          onClose={() => setEditStackup(false)}
          onSaved={(s) => {
            setStackups((old) => [...old.filter((x) => x.id !== s.id), s]);
            setStackupId(s.id);
            invalidate();
          }}
          onDeleted={(id) => {
            setStackups((old) => old.filter((x) => x.id !== id));
            if (stackupId === id) setStackupId(stackups.find((x) => x.id !== id)?.id ?? "");
          }}
        />
      ) : null}
      {editRules && ruleset ? (
        <RulesEditor
          ruleset={ruleset}
          finishes={finishes}
          onClose={() => setEditRules(false)}
          onSaved={(r) => {
            setRules((old) => [...old.filter((x) => x.id !== r.id), r]);
            setRuleId(r.id);
          }}
          onDeleted={(id) => {
            setRules((old) => old.filter((x) => x.id !== id));
            if (ruleId === id) setRuleId(rules.find((x) => x.id !== id)?.id ?? "");
          }}
        />
      ) : null}
    </div>
  );
}

/** The odd mode for a pair, the only mode otherwise. */
function pickMode(s: { modes: { v: number[]; [k: string]: unknown }[] }, pair: boolean) {
  const m = pair ? s.modes.reduce((a, b) => (a.v[0] * a.v[1] < b.v[0] * b.v[1] ? a : b)) : s.modes[0];
  return m as unknown as {
    eps_eff: number;
    alpha_db_m: number;
    alpha_c_db_m: number;
    alpha_d_db_m: number;
    z: Record<string, number | null>;
  };
}

// The palette helper is imported for its side-effect-free colour resolution in draw.ts;
// re-exported here so tests can check the theme wiring without pulling the canvas in.
export { palette };
