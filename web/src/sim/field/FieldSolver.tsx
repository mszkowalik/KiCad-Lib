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
import {
  errorMessage,
  fsCheck,
  fsFinishes,
  fsGeometry,
  fsMaterials,
  fsRules,
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
  newProfile,
  parseFreq,
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
  const [viewport, setViewport] = useState<View | null>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const job = useSolverJob();
  const { isAdmin } = useAuth();

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
    ])
      .then(([st, ru, ma, fi]) => {
        setStackups(st);
        setRules(ru);
        setMaterials(ma);
        setFinishes(fi);
        const first = st.find((s) => s.id === "JLC04161H-7628") ?? st[0];
        if (first) setStackupId(first.id);
        setRuleId(ru[0]?.id ?? "");
        const p = newProfile(0);
        setProfiles([p]);
        if (first) {
          const l = copperLayers(first)[0]?.name as string;
          cellOf(p, first, l).enabled = true;
          setSel({ profile: p.id, layer: l });
        }
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
    const onResize = () => setViewport((v) => (v ? { ...v } : v));
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
  const onWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    if (locked || !viewport) return;
    e.preventDefault();
    const f = Math.exp(e.deltaY * 0.0015);
    setViewport({ ...viewport, halfw: Math.max(0.02, Math.min(200, viewport.halfw * f)) });
  };
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
          <label className="fs-field">
            <span>Stackup</span>
            <span className="fs-inline">
              <select className="text" value={stackupId} onChange={(e) => { setStackupId(e.target.value); invalidate(); }}>
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
          <label className="fs-field">
            <span>Production rules</span>
            <span className="fs-inline">
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

        <div className="fs-gridwrap">
          <table className="data fs-grid">
            <thead>
              <tr>
                <th>Layer</th>
                <th>Material</th>
                <th>Type</th>
                <th>Thickness mm</th>
                {profiles.map((p) => (
                  <th key={p.id} className="fs-prof">
                    {p.name}
                    <span className="muted fs-note">
                      {TYPE_LABEL[p.type]} · {p.target} Ω ±{p.tolerance}% · {fmtHz(p.f)}
                    </span>
                    {profiles.length > 1 ? (
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => {
                          setProfiles((ps) => ps.filter((q) => q.id !== p.id));
                          if (sel.profile === p.id) setSel({ profile: profiles[0].id, layer: sel.layer });
                        }}
                      >
                        ×
                      </button>
                    ) : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stackup.layers.map((l, i) => (
                <tr key={`${l.type}${i}`} className={l.type === "copper" ? "" : "fs-diel"}>
                  <td>{l.type === "copper" ? l.name : l.label}</td>
                  <td className="muted">{l.material ? materials.find((m) => m.id === l.material)?.name ?? l.material : "—"}</td>
                  <td className="muted">{l.type}</td>
                  <td>{l.thickness_mm.toFixed(4)}</td>
                  {profiles.map((p) => {
                    if (l.type !== "copper") return <td key={p.id} />;
                    const name = l.name as string;
                    const c = cellOf(p, stackup, name);
                    const selected = sel.profile === p.id && sel.layer === name;
                    const r = c.result as Record<string, number> | null | undefined;
                    const z = r ? (r.Z0 ?? r.Zdiff) : null;
                    return (
                      <td
                        key={p.id}
                        className={`fs-cell${selected ? " on" : ""}`}
                        onClick={() => {
                          setSel({ profile: p.id, layer: name });
                          setResult(null);
                          setFrames([]);
                          setSearch(null);
                        }}
                      >
                        <label className="fs-check">
                          <input
                            type="checkbox"
                            checked={c.enabled}
                            onChange={(e) => {
                              c.enabled = e.target.checked;
                              touch();
                            }}
                          />
                          W1 {fmt(c.w, 3)} mm
                        </label>
                        <span className="muted fs-note">
                          {c.top_ref}/{c.bottom_ref} · {c.mask_mode === "both" ? "mask?" : maskOn(c) ? "mask" : "no mask"}
                          {c.via_fence ? " · fence" : ""}
                        </span>
                        {z != null ? (
                          <span className="fs-z">
                            {zKey(p)} {fmt(z, 1)} Ω
                          </span>
                        ) : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => {
            const p = newProfile(profiles.length);
            setProfiles((ps) => [...ps, p]);
            setSel({ profile: p.id, layer: cu[0].name as string });
          }}
        >
          + Add impedance profile
        </button>
      </section>

      <div className="fs-lower">
        {/* ------------------------------------------------------ properties */}
        <aside className="card pad fs-props">
          <h2 className="card-title">
            {profile.name} · {sel.layer}
          </h2>

          <fieldset className="fs-fieldset">
            <legend>1 · Profile</legend>
            <label className="fs-field">
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
            <label className="fs-field">
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
            <label className="fs-check">
              <input
                type="checkbox"
                checked={isCpw(profile)}
                onChange={(e) => setProfile({ type: lineType(pair ? "diff" : "single", e.target.checked) })}
              />
              Side ground on the signal layer (coplanar)
            </label>
            <div className="fs-row">
              <label className="fs-field">
                <span>Target Z</span>
                <input
                  className="text fs-num"
                  type="number"
                  value={profile.target}
                  onChange={(e) => setProfile({ target: Number(e.target.value) }, false)}
                />
              </label>
              <label className="fs-field">
                <span>Tolerance %</span>
                <input
                  className="text fs-num"
                  type="number"
                  value={profile.tolerance}
                  onChange={(e) => setProfile({ tolerance: Number(e.target.value) }, false)}
                />
              </label>
              <label className="fs-field">
                <span>Design f</span>
                <input
                  className="text fs-num"
                  defaultValue={fmtHz(profile.f)}
                  key={profile.f}
                  onBlur={(e) => {
                    const hz = parseFreq(e.target.value);
                    if (hz) setProfile({ f: Math.max(1e6, hz) });
                    else e.target.value = fmtHz(profile.f);
                  }}
                />
              </label>
            </div>
            <details className="fs-details">
              <summary>Frequency sweep range and resolution</summary>
              <div className="fs-row">
                <label className="fs-field">
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
                    <label className="fs-field">
                      <span>from</span>
                      <input
                        className="text fs-num"
                        defaultValue={fmtHz(profile.fr0)}
                        onBlur={(e) => {
                          const hz = parseFreq(e.target.value);
                          if (hz) setProfile({ fr0: hz }, false);
                          else e.target.value = fmtHz(profile.fr0);
                        }}
                      />
                    </label>
                    <label className="fs-field">
                      <span>to</span>
                      <input
                        className="text fs-num"
                        defaultValue={fmtHz(profile.fr1)}
                        onBlur={(e) => {
                          const hz = parseFreq(e.target.value);
                          if (hz) setProfile({ fr1: hz }, false);
                          else e.target.value = fmtHz(profile.fr1);
                        }}
                      />
                    </label>
                  </>
                ) : null}
                <label className="fs-field">
                  <span>points / decade</span>
                  <input
                    className="text fs-num"
                    type="number"
                    min={2}
                    max={20}
                    value={perDecade(profile)}
                    onChange={(e) => setProfile({ ppd: Number(e.target.value) }, false)}
                  />
                </label>
              </div>
              <p className="muted fs-note">
                {fmtHz(rlo)} … {fmtHz(rhi)} · {sweepPoints(profile)} points. The solver is quasi-TEM, so nothing below
                1 MHz is offered.
              </p>
            </details>
          </fieldset>

          <fieldset className="fs-fieldset">
            <legend>2 · Layer {sel.layer} and references</legend>
            <div className="fs-row">
              <label className="fs-field">
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
              <label className="fs-field">
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

          <fieldset className="fs-fieldset">
            <legend>3 · Structure</legend>
            <table className="data fs-dims">
              <thead>
                <tr>
                  <th />
                  <th>min</th>
                  <th>max</th>
                  <th />
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
                        <input
                          className="text fs-num"
                          type="number"
                          step="0.05"
                          value={profile.ranges[k]?.[j] ?? 0}
                          onChange={(e) => {
                            const r = profile.ranges[k] ?? [0, 1];
                            r[j] = Number(e.target.value);
                            profile.ranges[k] = r as [number, number];
                            touch();
                          }}
                        />
                      </td>
                    ))}
                    <td className="muted">mm</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <label className="fs-field">
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

            <label className="fs-check">
              <input type="checkbox" checked={cell.via_fence} onChange={(e) => setCell({ via_fence: e.target.checked })} />
              Fence vias along the structure
            </label>
            {cell.via_fence ? (
              <div className="fs-sub">
                <div className="fs-row">
                  <label className="fs-field">
                    <span>hole mm</span>
                    <input
                      className="text fs-num"
                      type="number"
                      step="0.05"
                      value={cell.via_hole}
                      onChange={(e) => setCell({ via_hole: Number(e.target.value) })}
                    />
                  </label>
                  <label className="fs-field">
                    <span>pad ⌀ mm</span>
                    <input
                      className="text fs-num"
                      type="number"
                      step="0.05"
                      value={cell.via_pad}
                      onChange={(e) => setCell({ via_pad: Number(e.target.value) })}
                    />
                  </label>
                  <label className="fs-field">
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
                    <label className="fs-field">
                      <span>distance mm</span>
                      <input
                        className="text fs-num"
                        type="number"
                        step="0.05"
                        value={cell.fence_distance}
                        onChange={(e) => setCell({ fence_distance: Number(e.target.value) })}
                      />
                    </label>
                  ) : null}
                </div>
                <div className="fs-row">
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setCell({ via_rows: [...cell.via_rows, { mode: "rel", pitch: minPitch(cell, ruleset) }] })}
                  >
                    + extra via row
                  </button>
                  {cell.via_rows.map((r, i) => (
                    <label key={i} className="fs-field">
                      <span>row {i + 2} pitch mm</span>
                      <input
                        className="text fs-num"
                        type="number"
                        step="0.05"
                        value={r.pitch}
                        onChange={(e) => {
                          cell.via_rows[i] = { ...r, pitch: Number(e.target.value) };
                          invalidate();
                        }}
                      />
                    </label>
                  ))}
                </div>
              </div>
            ) : null}

            <label className="fs-check">
              <input type="checkbox" checked={cell.use_w2} onChange={(e) => setCell({ use_w2: e.target.checked })} />
              Etched trapezoid (top narrower than W1)
            </label>
            {cell.use_w2 ? (
              <label className="fs-field fs-sub">
                <span>undercut per side µm</span>
                <input
                  className="text fs-num"
                  type="number"
                  step="0.5"
                  value={cell.etch_um ?? Number(ruleset?.etch_outer_um ?? 12.5)}
                  onChange={(e) => setCell({ etch_um: Number(e.target.value) })}
                />
              </label>
            ) : null}

            <label className="fs-check">
              <input type="checkbox" checked={cell.use_rough} onChange={(e) => setCell({ use_rough: e.target.checked })} />
              Copper roughness (Hammerstad)
            </label>
            {cell.use_rough ? (
              <label className="fs-field fs-sub">
                <span>RMS µm</span>
                <input
                  className="text fs-num"
                  type="number"
                  step="0.1"
                  value={cell.roughness_um}
                  onChange={(e) => setCell({ roughness_um: Number(e.target.value) })}
                />
              </label>
            ) : null}
          </fieldset>

          <fieldset className="fs-fieldset">
            <legend>4 · Find solutions</legend>
            <div className="fs-row">
              <label className="fs-field">
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
              <label className="fs-field">
                <span>Dk model</span>
                <select className="text" value={epsModel} onChange={(e) => setEpsModel(e.target.value)}>
                  <option value="djordjevic">Djordjevic-Sarkar</option>
                  <option value="constant">constant</option>
                </select>
              </label>
            </div>
            <div className="fs-row">
              <button type="button" className="btn btn-accent" onClick={runSearch} disabled={job.state.running}>
                Find solutions
              </button>
              <button type="button" className="btn" onClick={forward} disabled={job.state.running}>
                Exact width for the target
              </button>
            </div>
          </fieldset>

          <fieldset className="fs-fieldset">
            <legend>5 · Resulting dimensions</legend>
            <div className="fs-row">
              <label className="fs-field">
                <span>Width W1 mm</span>
                <input
                  className="text fs-num"
                  type="number"
                  step="0.005"
                  value={cell.w}
                  onChange={(e) => setCell({ w: Number(e.target.value) })}
                />
              </label>
              {pair ? (
                <label className="fs-field">
                  <span>Spacing S mm</span>
                  <input
                    className="text fs-num"
                    type="number"
                    step="0.005"
                    value={cell.s}
                    onChange={(e) => setCell({ s: Number(e.target.value) })}
                  />
                </label>
              ) : null}
              {isCpw(profile) ? (
                <label className="fs-field">
                  <span>Gap mm</span>
                  <input
                    className="text fs-num"
                    type="number"
                    step="0.005"
                    value={cell.gap}
                    onChange={(e) => setCell({ gap: Number(e.target.value) })}
                  />
                </label>
              ) : null}
            </div>
            <button type="button" className="btn" onClick={reverse} disabled={job.state.running}>
              Calculate Z from these dimensions
            </button>
          </fieldset>

          <fieldset className="fs-fieldset">
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
              <label className="fs-check">
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
                ref={canvasRef}
                className={`fs-canvas${locked ? "" : " fs-unlocked"}`}
                onWheel={onWheel}
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
        profileName={profile.name}
        profileConfig={profile as unknown as Record<string, unknown>}
        profileResult={
          result
            ? {
                // numbers only: a solved mesh is tens of megabytes and is cheap
                // to redraw only by solving again
                summary: result.summary,
                design: result.design,
                sweep: result.sweep,
                C0: result.C0,
                mesh: result.mesh,
                notes: result.notes,
                geometry: result.geometry,
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
