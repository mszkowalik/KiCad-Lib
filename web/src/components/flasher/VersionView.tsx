/** ONE deployment version: everything a device gets, in the order it gets it,
 *  plus where the version is used — and, on a DRAFT, the place you edit it.
 *
 *  **There is no separate composer.** A modal called `Composer` used to render
 *  the same four sections a second time, editable, over the top of this one
 *  (deleted 2026-09-17, user request). Two renderings of a procedure is two
 *  places a step op has to be understood, and they had already diverged on
 *  which controls a section carries. Now `New version` creates the draft and
 *  selects it, and the draft is edited exactly where it is read.
 *
 *  What is editable on a draft: the note, the procedure (with its transport
 *  and monitor baud), and the parameter set. **Firmware, berryware and
 *  artwork are not**, and never were — a `flash` step picks its images, a
 *  `download_files` step picks its bundle and a `mark_laser` step picks or
 *  uploads its artwork, inside `StepEditor` (user decision 2026-07-30,
 *  extended 2026-09-17). The Firmware and Files cards are summaries of what
 *  the procedure pinned.
 *
 *  **The procedure opens READ-ONLY and a button turns editing on** (user
 *  request 2026-09-17), on a draft. A published version offers `Edit as new
 *  version` instead, which mints the draft and opens it editing. Edits still
 *  commit as they are made — there is no Save to forget — but typing is
 *  debounced, because a PATCH per keystroke re-ran the whole validator.
 *
 *  Every edit PATCHes the draft and takes the server's validation back, so the
 *  errors under the header are the same ones the publish button will enforce —
 *  `validate.check()` is the one gate, and this never second-guesses it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ParamSetEditor from "./ParamSetEditor";
import { Link } from "react-router-dom";
import {
  errorMessage,
  firmwareBinPath,
  getDeploymentVersion,
  importDeviceFiles,
  isAbortError,
  listBerryBundles,
  listDeviceFiles,
  listFirmware,
  listParamSets,
  patchDeploymentVersion,
  deleteDeploymentVersion,
  publishDeploymentVersion,
  rejectDeploymentVersion,
  type BerryBundleRow,
  type ComposeBody,
  type DeploymentVersionDetail,
  type DeviceFileRow,
  type FirmwareAssetRow,
  type FlasherMeta,
  type ParamSetRow,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { listPrinters, type AgentRoll } from "../../flasher/benchAgent";
import StepEditor, { type ArtworkChoice } from "./StepEditor";
import { fmtBytes, fmtWhen, shortSha } from "./common";

/** One word for the files card, from what the version pins. */
const FILES_TITLE: Record<string, string> = {
  berryware: "Berryware", artwork: "Artwork", mixed: "Files", "": "Files",
};

/** Debounce for typed edits to the procedure — one PATCH per pause, not per
 *  keystroke, because each PATCH re-runs the whole validator. */
const STEPS_DEBOUNCE_MS = 600;

export default function VersionView({
  versionId,
  onDiff,
  reloadKey = 0,
  meta,
  onChanged,
  onGone,
  onEditAsNew,
  autoEdit = false,
}: {
  versionId: number;
  onDiff?: (versionId: number) => void;
  reloadKey?: number;
  /** `/meta`: transport profiles, the check vocabulary, default flash offsets.
   *  Absent = the draft controls fall back to what they can name themselves. */
  meta?: FlasherMeta | null;
  /** A draft was edited or published — the page's timeline is now stale. */
  onChanged?: () => void;
  /** A draft was discarded; there is nothing here to select any more. */
  onGone?: () => void;
  /** On a published version: mint a draft from it and open that one editing.
   *  The page owns version creation, so the button here only asks. */
  onEditAsNew?: () => void;
  /** Open this version in edit mode straight away — set by the page for the
   *  draft it just minted, so `New version` lands on an editable procedure. */
  autoEdit?: boolean;
}) {
  const dialog = useDialog();
  /** The param-set editor, open on this set's id. */
  const [editingParams, setEditingParams] = useState<number | null>(null);
  const [v, setV] = useState<DeploymentVersionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSteps, setShowSteps] = useState(true);
  // The BUNDLE is what you see; the file list is detail behind a toggle
  // (user feedback 2026-07-30: "I still see the files listed instead of the bundle").
  const [showFiles, setShowFiles] = useState(false);

  /** Draft editing. `note` is local because it is typed; everything else
   *  commits on change, so there is no Save button and nothing to forget. */
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [rawJson, setRawJson] = useState(false);
  const [stepsText, setStepsText] = useState("");
  const [assets, setAssets] = useState<FirmwareAssetRow[]>([]);
  const [bundles, setBundles] = useState<BerryBundleRow[]>([]);
  const [paramSets, setParamSets] = useState<ParamSetRow[]>([]);
  const [pool, setPool] = useState<DeviceFileRow[]>([]);
  /** The bench printer's rolls, when this browser sits on the bench machine
   *  and the agent answers on loopback. Away from it: none, and the label
   *  preview draws the roll's nominal size and says so. */
  const [rolls, setRolls] = useState<AgentRoll[]>([]);
  const noteTimer = useRef<number | null>(null);
  /** Edit mode for the procedure. Off by default even on a draft: the card
   *  opens as a document, and the button turns it into a form. */
  const [editing, setEditing] = useState(false);
  const stepsTimer = useRef<number | null>(null);
  const pendingSteps = useRef<Record<string, unknown>[] | null>(null);

  const load = useCallback(() => {
    const ac = new AbortController();
    setV(null);
    getDeploymentVersion(versionId, ac.signal)
      .then(setV)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [versionId, reloadKey]);

  useEffect(() => load(), [load]);

  // One ask, only when a step prints: the agent is a loopback call that
  // fails fast off the bench, and a procedure with no label has no use for it.
  const printsLabel = (v?.steps ?? []).some((s) => (s as { op?: string }).op === "print_label");
  useEffect(() => {
    if (!printsLabel) return;
    let live = true;
    listPrinters()
      .then((got) => { if (live) setRolls(got.rolls); })
      .catch(() => { if (live) setRolls([]); });
    return () => { live = false; };
  }, [printsLabel]);

  // The note and the JSON box follow whichever version is on screen.
  useEffect(() => {
    if (!v) return;
    setNote(v.comment);
    setStepsText(JSON.stringify(v.steps ?? [], null, 2));
    setRawJson(false);
    setEditing(autoEdit && v.status === "draft");
  }, [v?.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  // The pools a draft edits FROM. Fetched only for a draft: a published
  // version needs none of them and this renders on every row click.
  const draftMode = v?.status === "draft";
  const projectId = v?.deployment.project_id;
  useEffect(() => {
    if (!draftMode || !projectId) return;
    const ac = new AbortController();
    Promise.all([
      listFirmware(projectId, ac.signal),
      listBerryBundles(projectId, ac.signal),
      listParamSets(projectId, ac.signal),
      listDeviceFiles(projectId, ac.signal),
    ])
      .then(([a, b, p, files]) => {
        setAssets(a);
        setBundles(b);
        setParamSets(p);
        setPool(files);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [draftMode, projectId]);

  /** The artwork a marking step may pick: the newest published version of
   *  every `.lbrn2` in the project pool. */
  const artworkPool = useMemo<ArtworkChoice[]>(() =>
    pool
      .filter((f) => f.kind === "artwork")
      .map((f) => {
        const published = f.versions.filter((x) => x.status === "published");
        const live = published[published.length - 1];
        return live ? {
          device_file_version_id: live.id, filename: f.filename,
          version_no: live.version_no, size_bytes: live.size_bytes,
        } : null;
      })
      .filter((x): x is ArtworkChoice => x !== null),
  [pool]);

  /** The ONE write path for a draft. Takes the server's answer back whole, so
   *  the validation under the header is always the publish button's own. */
  const patch = useCallback(async (body: ComposeBody) => {
    if (!v) return;
    setBusy(true);
    setError(null);
    try {
      await patchDeploymentVersion(v.id, body);
      const fresh = await getDeploymentVersion(v.id);
      setV(fresh);
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }, [v, onChanged]);

  const parsedSteps = useMemo(() => {
    try {
      const parsed = JSON.parse(stepsText || "[]");
      return Array.isArray(parsed) ? (parsed as Record<string, unknown>[]) : null;
    } catch {
      return null;
    }
  }, [stepsText]);

  /** A procedure edit: the screen follows at once, the PATCH after a pause.
   *  `flushSteps` sends whatever is pending now — before a pin change, before
   *  publishing, before leaving edit mode — so nothing typed is lost. */
  const editSteps = useCallback((next: Record<string, unknown>[]) => {
    setStepsText(JSON.stringify(next, null, 2));
    pendingSteps.current = next;
    if (stepsTimer.current) window.clearTimeout(stepsTimer.current);
    stepsTimer.current = window.setTimeout(() => {
      const steps = pendingSteps.current;
      pendingSteps.current = null;
      if (steps) void patch({ steps });
    }, STEPS_DEBOUNCE_MS);
  }, [patch]);
  const flushSteps = useCallback(async () => {
    if (stepsTimer.current) window.clearTimeout(stepsTimer.current);
    const steps = pendingSteps.current;
    pendingSteps.current = null;
    if (steps) await patch({ steps });
  }, [patch]);
  useEffect(() => () => {
    if (stepsTimer.current) window.clearTimeout(stepsTimer.current);
  }, []);

  if (error && !v) return <ErrorBanner message={error} />;
  if (!v) return <Spinner label="Loading version…" />;

  const val = v.validation;
  const isDraft = v.status === "draft";
  /** A version can be removed until it is PUBLISHED — that is what a device
   *  was given. A rejected row is removable for the same reason a draft is:
   *  it is a decision nobody needs to keep reading (user question
   *  2026-09-17: "how do I remove a version from the UI?"). */
  const removable = v.status !== "published";
  /** Names a step may interpolate. The server validates for real; this only
   *  fills the dropdowns in the step editor. */
  const paramKeys = paramSets.find((p) => p.id === v.param_set_id)?.keys ?? [];

  const typeNote = (text: string) => {
    setNote(text);
    if (noteTimer.current) window.clearTimeout(noteTimer.current);
    // Debounced: a PATCH per keystroke would re-run the whole validator.
    noteTimer.current = window.setTimeout(() => void patch({ comment: text }), 700);
  };

  /** A marking step picked or uploaded its artwork: the step and the pin move
   *  in ONE patch. The new file replaces whatever artwork the step named
   *  before, and every other pinned file — berryware, another step's artwork
   *  — stays exactly as it was. */
  const changeArtwork = (index: number, step: Record<string, unknown>, file: ArtworkChoice) => {
    const steps = (pendingSteps.current ?? parsedSteps ?? v.steps ?? []).map((s, j) =>
      j === index ? step : s);
    const previous = String((parsedSteps ?? v.steps ?? [])[index]?.template ?? "");
    const keep = (v.files ?? []).filter((f) =>
      f.filename !== file.filename
      && !(previous ? f.filename === previous
           : f.kind === "artwork" && (v.files ?? []).filter((x) => x.kind === "artwork").length === 1));
    if (stepsTimer.current) window.clearTimeout(stepsTimer.current);
    pendingSteps.current = null;
    setStepsText(JSON.stringify(steps, null, 2));
    void patch({
      steps,
      file_version_ids: [...keep.map((f) => f.device_file_version_id), file.device_file_version_id],
    });
  };

  /** Upload a .lbrn2 into the project pool as ARTWORK, published, and hand
   *  back what to pin. The server refuses anything that is not a LightBurn
   *  file, and `make_bundle: false` keeps it out of the berryware bundles. */
  const uploadArtwork = async (file: File): Promise<ArtworkChoice> => {
    const res = await importDeviceFiles(v.deployment.project_id, [file],
      { kind: "artwork", make_bundle: false });
    const made = res.files[0];
    if (!made) throw new Error("the upload returned no file");
    listDeviceFiles(v.deployment.project_id).then(setPool).catch(() => undefined);
    return {
      device_file_version_id: made.device_file_version_id, filename: made.filename,
      version_no: made.version_no, size_bytes: made.size_bytes,
    };
  };

  const publish = async () => {
    if (!note.trim()) {
      setError("Say what changed and why — it is stored with the version.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await flushSteps();
      // The note may still be inside the debounce, so send it with the PATCH
      // rather than racing the timer.
      const synced = await patchDeploymentVersion(v.id, { comment: note });
      if (!synced.validation.ok) {
        setV(await getDeploymentVersion(v.id));
        setError("Validation failed — fix the errors above.");
        return;
      }
      await publishDeploymentVersion(v.id);
      setV(await getDeploymentVersion(v.id));
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  /** Discard a draft. DELETE first — a version minted by one click and looked
   *  at must not leave a rejected row behind forever. The server refuses when
   *  a programming run records it (a draft runs as a bench trial), and then
   *  `reject` is the right answer: the row stays as history. */
  const discard = async () => {
    // Every delete in this app asks first — project rule, no exceptions.
    if (!(await dialog.confirm(
      `Delete ${v.deployment.name} v${v.version_no}?`
      + (v.status === "draft"
         ? " The draft and everything in it go; nothing else is touched."
         : " It was rejected, so nothing runs it.")
      + " Refused if any programming run records it.",
      { title: `Delete v${v.version_no}`, tone: "danger", confirmLabel: "Delete" },
    ))) return;
    setBusy(true);
    try {
      try {
        await deleteDeploymentVersion(v.id);
      } catch {
        await rejectDeploymentVersion(v.id);
      }
      onGone?.();
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <>
      <div className="card pad">
        <div className="toolbar">
          <h2 className="card-title">
            {v.deployment.name} v{v.version_no}
          </h2>
          <StatusPill status={v.status} />
          {v.where_used.channels.map((c) => (
            <span key={c} className="pill ok">{c}</span>
          ))}
          {onDiff ? (
            <button type="button" className="btn btn-sm" onClick={() => onDiff(v.id)}>
              Compare
            </button>
          ) : null}
        </div>
        {/* Two lines, and which is which used to be the problem. The
            version's publish NOTE was rendered in `.card-subtitle` — uppercase
            11px mono with letter-spacing — run together with the author and
            the date. That style is right for a short caption and unreadable
            for a five-line paragraph, and it made the note look like a heading
            nobody could place ("I don't know where it comes from", bench
            2026-09-17). So the caption keeps the caption style, and the note is
            ordinary prose under its own label. */}
        <p className="card-subtitle">
          {v.created_by || "unknown author"} · {fmtWhen(v.created_at)}
          {/* A retro-imported version was written and published by the same
              name, and printing both read as two facts about two people. */}
          {v.approved_by && v.approved_by !== v.created_by ? ` · published by ${v.approved_by}` : ""}
          {v.changes.summary ? ` · changed: ${v.changes.summary}` : ""}
        </p>
        {isDraft ? (
          <div className="version-note">
            <span className="version-note-label">
              Note on this version — required to publish
            </span>
            <input
              className="text"
              placeholder="what changed and why"
              value={note}
              onChange={(e) => typeNote(e.target.value)}
            />
            <div className="btn-row">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => void publish()}
                disabled={busy || !val.ok || !note.trim()}
                title={val.ok ? "" : "Fix the errors above first"}
              >
                Publish
              </button>
              {busy ? <span className="muted dim">saving…</span> : null}
            </div>
          </div>
        ) : v.comment ? (
          <div className="version-note">
            <span className="version-note-label">Note on this version</span>
            <p>{v.comment}</p>
          </div>
        ) : null}
        {/* Parameters, as ONE LINE inside the header — not a card of its own
            (user request 2026-09-17: "move parameters higher, not keep it on
            the bottom"). It is a single fact, and a card for it cost three
            lines of chrome and pushed the procedure 170 px down the page. The
            values, their history and who needs each key are the Parameters
            page; this says which set the version is wired to. */}
        <p className="version-params muted">
          <span className="version-note-label">Parameters</span>
          {isDraft ? (
            <select
              className="row-input"
              value={v.param_set_id ?? ""}
              onChange={(e) =>
                void patch({ param_set_id: e.target.value === "" ? null : Number(e.target.value) })
              }
            >
              <option value="">— none —</option>
              {paramSets.map((ps) => (
                <option key={ps.id} value={ps.id}>{ps.name} ({ps.keys.length} keys)</option>
              ))}
            </select>
          ) : (
            <strong>{v.param_set_name ?? "none"}</strong>
          )}
          {v.param_defaults && Object.keys(v.param_defaults).length ? (
            <span className="muted dim">
              · own defaults: {Object.keys(v.param_defaults).join(", ")}
            </span>
          ) : null}
          {/* A version keeps the set it was MADE with. Saying so when the
              deployment has since moved on is the whole reason the pin is
              per-version — otherwise the two look like one field that
              disagrees with itself. */}
          {!isDraft && v.deployment.param_set_id !== v.param_set_id ? (
            <span
              className="pill warn"
              title="This version was published against its own set. The deployment now defaults to a different one, which only affects versions made from here on."
            >
              deployment now defaults elsewhere
            </span>
          ) : null}
          {v.param_set_id ? (
            /* Editable from a PUBLISHED version too, on purpose: the values are
               not versioned, so changing the WiFi is a settings change rather
               than a new version. */
            <button
              type="button"
              className="btn btn-sm"
              title="Values resolve at run time and are snapshotted on every run — rotating a password never mints a version"
              onClick={() => setEditingParams(v.param_set_id)}
            >
              Edit values…
            </button>
          ) : null}
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        {val.errors.length ? (
          <div className="banner-error">
            <strong>Would not publish:</strong>
            <ul className="val-list">
              {val.errors.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          </div>
        ) : null}
        {val.warnings.length ? (
          <div className="banner-warn">
            <ul className="val-list">
              {val.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          </div>
        ) : null}
        {/* The one destructive control, alone at the foot of the box and on
            the right — the same shape the deployment card uses for its own
            Delete (user request 2026-09-17). A draft's Discard used to sit
            beside Publish, where the primary action and the one that throws
            the work away were a pixel apart. */}
        {removable ? (
          <div className="version-danger">
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => void discard()}
              disabled={busy}
              title="Delete this version. Refused once a programming run records it — that one is rejected instead, and stays as history."
            >
              Delete this version
            </button>
          </div>
        ) : null}
      </div>

      {/* The PROCEDURE comes first, straight after the version it belongs
          to. It is what the bench will actually do — 28 steps on a V2 —
          and it sat below the firmware and berryware cards, off the bottom
          of the window (user request 2026-09-17). Firmware and berryware
          are one row and one pill; they read fine further down. */}
      <div className="card pad">
        <div className="toolbar">
          <h3 className="card-title">Procedure — {v.steps?.length ?? 0} steps</h3>
          <span className="muted dim mono">
            {v.transport_profile} @ {v.monitor_baud}
          </span>
          {isDraft && editing ? (
            <>
              {/* Two compact controls on the toolbar line. `.row-input` is
                  width: 100%, which as a bare flex item takes the whole row;
                  the wrap gives each a box of its own. */}
              <span className="field-inline">
                <select
                  className="row-input transport-pick"
                  value={v.transport_profile}
                  title="uart_bridge = external USB-UART; usb_serial_jtag = native USB (never touches DTR/RTS in monitor mode)"
                  onChange={(e) => void patch({ transport_profile: e.target.value })}
                >
                  {(meta?.transport_profiles ?? ["uart_bridge", "usb_serial_jtag"]).map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                <input
                  className="row-input num-input"
                  defaultValue={v.monitor_baud}
                  title="monitor baud"
                  onBlur={(e) => {
                    const n = Number(e.target.value) || 115200;
                    if (n !== v.monitor_baud) void patch({ monitor_baud: n });
                  }}
                />
              </span>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setRawJson((x) => !x)}
                title="the same steps as JSON, for a bulk edit or a paste"
              >
                {rawJson ? "Visual editor" : "Edit as JSON"}
              </button>
            </>
          ) : null}
          {/* The one control that changes what the card IS. A draft opens as
              a document and this makes it a form; a published version cannot
              change, so the same place offers the draft that can. */}
          {isDraft ? (
            <button
              type="button"
              className={`btn btn-sm${editing ? " btn-primary" : ""}`}
              disabled={busy}
              title={editing
                ? "Every change is saved as you make it. This closes the form."
                : "Open every step for editing — fields, order, firmware and artwork pins"}
              onClick={() => {
                if (editing) {
                  void flushSteps();
                  setRawJson(false);
                }
                setEditing((x) => !x);
                setShowSteps(true);
              }}
            >
              {editing ? "Done editing" : "Edit procedure"}
            </button>
          ) : onEditAsNew ? (
            <button
              type="button"
              className="btn btn-sm"
              onClick={onEditAsNew}
              title="A published version is immutable. This mints a draft from it and opens the draft for editing."
            >
              Edit as new version
            </button>
          ) : null}
          {editing ? <span className="muted dim">changes save as you make them</span> : null}
          <button type="button" className="btn btn-sm" onClick={() => setShowSteps((s) => !s)}>
            {showSteps ? "Hide" : "Show"}
          </button>
        </div>
        {!showSteps ? null : rawJson && isDraft && editing ? (
          <>
            <textarea
              className="note-textarea mono file-editor"
              spellCheck={false}
              value={stepsText}
              onChange={(e) => setStepsText(e.target.value)}
              onBlur={() => {
                if (parsedSteps) void patch({ steps: parsedSteps });
              }}
            />
            {parsedSteps === null ? <p className="banner-error">Not valid JSON.</p> : null}
          </>
        ) : (
          /* ONE rendering of a procedure, read-only or not. `readOnly` is a
             flag, never a second component — the composer's copy is deleted. */
          <StepEditor
            readOnly={!(isDraft && editing)}
            steps={(isDraft ? parsedSteps ?? [] : (v.steps ?? [])) as Record<string, unknown>[]}
            onChange={editSteps}
            pinnedFiles={v.files ?? []}
            rolls={rolls}
            artworkPool={isDraft ? artworkPool : []}
            onArtworkChange={isDraft ? changeArtwork : undefined}
            onArtworkUpload={isDraft ? uploadArtwork : undefined}
            paramKeys={isDraft ? paramKeys : []}
            images={(v.images ?? []).map((i) => ({
              firmware_asset_id: i.firmware_asset_id, address: i.address,
            }))}
            assets={isDraft ? assets : assetsOf(v)}
            onImagesChange={(next) => void patch({ images: next })}
            bundleId={v.berry_bundle_id ?? -1}
            bundles={isDraft ? bundles : bundlesOf(v)}
            onBundleChange={(id) => {
              const b = bundles.find((x) => x.id === id);
              if (!b) return;
              void patch({
                berry_bundle_id: id,
                file_version_ids: b.files.map((f) => f.device_file_version_id),
                files_label: b.label,
              });
            }}
            defaultOffsets={isDraft ? meta?.default_offsets : undefined}
            checkNames={isDraft ? meta?.checks : undefined}
          />
        )}
      </div>

      <div className="card pad">
        <h3 className="card-title">
          Firmware{" "}
          <span className="muted dim mono">
            {v.firmware_fingerprint ? shortSha(v.firmware_fingerprint) : "none"}
          </span>
        </h3>
        {v.images?.length ? (
          <div className="table-wrap">
            <table className="data data-fixed dv-images-table">
              <thead>
                <tr>
                  <th>Offset</th>
                  <th>Image</th>
                  <th>Kind</th>
                  <th>Chip</th>
                  <th className="num">Size</th>
                  <th>Build</th>
                  <th>sha256</th>
                </tr>
              </thead>
              <tbody>
                {v.images.map((img) => (
                  <tr key={img.address}>
                    <td className="mono">{img.address}</td>
                    <td className="mono" title={img.filename}>
                      <a className="comp-link" href={firmwareBinPath(img.firmware_asset_id)}>
                        {img.filename}
                      </a>
                    </td>
                    <td>{img.kind}</td>
                    <td className="mono dim">{img.chip || "—"}</td>
                    <td className="num">{fmtBytes(img.size_bytes)}</td>
                    <td title={img.build_label}>{img.build_label || "—"}</td>
                    <td className="mono dim" title={img.sha256}>{shortSha(img.sha256)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No firmware — this version flashes nothing.</p>
        )}
      </div>

      {/* Named by what the version PINS — berryware, artwork, or both — because
          a mark version pins a LightBurn drawing and calling that "berryware"
          was reported as wrong (2026-09-17). Only berryware has a bundle to
          name; artwork is one file per marking step. */}
      <div className="card pad">
        <div className="toolbar">
          <h3 className="card-title">{FILES_TITLE[v.files_kind] ?? "Files"}</h3>
          {v.files?.length && v.files_kind !== "artwork" ? (
            <span className={`pill ${v.berry_bundle_id ? "ok" : "warn"}`}
                  title={v.berry_bundle_id
                    ? "a named bundle — the same set everywhere it appears"
                    : "an ad-hoc file set nobody has named"}>
              {v.files_label || "unnamed set"} · {v.files.length} files
            </span>
          ) : v.files?.length ? (
            <span className="pill info">{v.files.length} {v.files.length === 1 ? "drawing" : "drawings"}</span>
          ) : null}
          <span className="muted dim mono">
            {v.files_fingerprint ? shortSha(v.files_fingerprint) : ""}
          </span>
          {v.files?.length ? (
            <button type="button" className="btn btn-sm" onClick={() => setShowFiles((x) => !x)}>
              {showFiles ? "Hide files" : "Show files"}
            </button>
          ) : null}
        </div>
        {!v.files?.length ? (
          <p className="muted">
            {v.deployment.kind === "mark" ? "No artwork pinned." : "No files pinned."}
          </p>
        ) : !showFiles ? null : (
          <div className="table-wrap">
            <table className="data data-fixed dv-files-table">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>File</th>
                  <th>Version</th>
                  <th className="num">Size</th>
                  <th>sha256</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {v.files.map((f, i) => (
                  <tr key={f.device_file_version_id}>
                    <td className="num">{i + 1}</td>
                    <td className="mono" title={`${f.filename} — ${f.kind}`}>
                      {f.filename}
                      {v.files_kind === "mixed" ? (
                        <span className={`pill ${f.kind === "artwork" ? "info" : "neutral"}`}> {f.kind}</span>
                      ) : null}
                    </td>
                    <td>
                      v{f.version_no} <StatusPill status={f.status} />
                    </td>
                    <td className="num">{fmtBytes(f.size_bytes)}</td>
                    <td className="mono dim" title={f.sha256}>{shortSha(f.sha256)}</td>
                    <td className="muted" title={f.comment}>{f.comment || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editingParams ? (
        <ParamSetEditor
          projectId={v.deployment.project_id}
          paramSetId={editingParams}
          onClose={() => setEditingParams(null)}
        />
      ) : null}

      <div className="card pad">
        <h3 className="card-title">Where used</h3>
        <p className="muted">
          {v.where_used.runs} programming runs · {v.where_used.devices} devices
          {v.where_used.channels.length ? ` · channels: ${v.where_used.channels.join(", ")}` : ""}
        </p>
        {v.where_used.batches.length ? (
          <p className="muted">
            Batches:{" "}
            {v.where_used.batches.map((b, i) => (
              <span key={b.id}>
                {i ? ", " : ""}
                <Link className="val-link" to={`/runs/${b.id}`}>{b.label}</Link>
              </span>
            ))}
          </p>
        ) : null}
        {v.where_used.runs > 0 ? (
          <Link className="val-link" to={`/production/devices?deployment_version=${v.id}`}>
            See the devices programmed with this version
          </Link>
        ) : null}
      </div>
    </>
  );
}


/** The version's own payload is enough context for the read-only rows — no
 *  extra fetches: its images already carry filename/kind, and its pinned files
 *  describe the bundle. */
function assetsOf(v: DeploymentVersionDetail): FirmwareAssetRow[] {
  return (v.images ?? []).map((i) => ({
    id: i.firmware_asset_id, filename: i.filename, sha256: i.sha256,
    size_bytes: i.size_bytes, chip: i.chip, kind: i.kind,
    default_address: i.address, build_label: i.build_label, notes: "",
    uploaded_by: "", uploaded_at: null, flashable: true,
  }));
}

function bundlesOf(v: DeploymentVersionDetail): BerryBundleRow[] {
  if (!v.files?.length) return [];
  return [{
    id: v.berry_bundle_id ?? -1,
    label: v.files_label || "unnamed set",
    files_fingerprint: v.files_fingerprint,
    comment: "", created_by: "", created_at: null,
    file_count: v.files.length, used_by: 0,
    files: v.files.map((f) => ({
      device_file_version_id: f.device_file_version_id,
      filename: f.filename, version_no: f.version_no,
      size_bytes: f.size_bytes, sha256: f.sha256,
    })),
  }];
}
