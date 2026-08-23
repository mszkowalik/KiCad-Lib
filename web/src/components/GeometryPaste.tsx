import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  type GeometryProposalResult,
  isAbortError,
  proposeNewTemplate,
  proposeTemplateEdit,
  renderTemplateSource,
  type TemplateKind,
} from "../api";
import { ErrorBanner } from "./Ui";

/**
 * The clipboard door into symbol/footprint geometry — one widget for all four
 * cases (symbol|footprint x edit|create), because the flow is identical and a
 * second copy would drift.
 *
 * Editing passes `id`, which is how the server learns the name; creating omits
 * it and the server reads the name out of the pasted text. Either way this
 * PUBLISHES: the new version is live in the library, the mirror and KiCad as
 * soon as the server answers. Preview first — that render is the only look
 * before the fact, now that there is no approval step to look at it in.
 */
export default function GeometryPaste({
  kind,
  id,
  publishedSource,
  onFiled,
}: {
  kind: TemplateKind;
  /** omit to create a brand-new template */
  id?: number;
  /** prefill + the "Reset to published" target; absent when creating */
  publishedSource?: string | null;
  onFiled?: (res: GeometryProposalResult) => void;
}) {
  const noun = kind === "footprints" ? "footprint" : "symbol";
  const ext = kind === "footprints" ? ".kicad_mod" : ".kicad_sym";
  const creating = id === undefined;

  const [src, setSrc] = useState(publishedSource ?? "");
  const [newName, setNewName] = useState("");
  const [comment, setComment] = useState("");
  // The recheck waiver. Unticked = null (nobody was asked) and the server
  // decides by material fingerprint; ticked = "small change", which carries
  // sign-offs and verifications across the new drawing under the user's name.
  const [minorChange, setMinorChange] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<GeometryProposalResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewFor, setPreviewFor] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);

  useEffect(() => {
    setSrc(publishedSource ?? "");
  }, [publishedSource]);

  // an object URL is a live resource: drop the old one whenever it is replaced
  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const clearOutcome = () => {
    setResult(null);
    setError(null);
  };

  /** Render the pasted text through kicad-cli without saving anything, so a
   *  mistake is visible before it is published. */
  const preview = async () => {
    if (!src.trim() || rendering) return;
    const ctrl = new AbortController();
    setRendering(true);
    setPreviewError(null);
    try {
      const url = await renderTemplateSource(kind, src, ctrl.signal);
      setPreviewUrl((old) => {
        if (old) URL.revokeObjectURL(old);
        return url;
      });
      setPreviewFor(src);
    } catch (err) {
      if (!isAbortError(err)) setPreviewError(errorMessage(err));
    } finally {
      setRendering(false);
    }
  };

  const file = async () => {
    if (busy || !src.trim() || !comment.trim()) return;
    setBusy(true);
    clearOutcome();
    try {
      const res = creating
        ? await proposeNewTemplate(kind, src, comment, newName)
        : await proposeTemplateEdit(kind, id, src, comment, minorChange ? true : null);
      setResult(res);
      if (creating) {
        setSrc("");
        setComment("");
        setNewName("");
      }
      onFiled?.(res);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  /** Dropping a file loads it into the same box a paste lands in, so the file
   *  route needs no control of its own. */
  const drop = async (e: React.DragEvent<HTMLTextAreaElement>) => {
    const f = e.dataTransfer.files[0];
    if (!f) return;
    e.preventDefault();
    setSrc(await f.text());
    clearOutcome();
  };

  const stale = previewUrl !== null && previewFor !== src;

  return (
    <>
      <p className="muted">
        {creating
          ? `Paste a whole ${ext} body, or drop the file on the box. The name is read from the pasted text; type one below when it has none of its own.`
          : `Paste the ${noun} from the KiCad editor, or drop a ${ext} file on the box. The text is prefilled with the published source, so select all and paste over it.`}{" "}
        Saving <strong>publishes</strong> — the new version reaches the library, the file
        mirror and KiCad straight away. Versions are immutable, so the way back is to paste
        the old source and save again.
      </p>
      {!creating ? (
        <p className="muted">
          The name comes from this page, never from the pasted text, so an edit cannot rename
          the {noun}.
        </p>
      ) : null}
      <textarea
        className="text skill-textarea"
        value={src}
        spellCheck={false}
        aria-label={`${noun} source`}
        placeholder={`Paste the ${ext} text here`}
        onChange={(e) => {
          setSrc(e.target.value);
          clearOutcome();
        }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => void drop(e)}
      />
      {creating ? (
        <div className="skill-desc">
          <input
            className="text"
            value={newName}
            maxLength={200}
            spellCheck={false}
            placeholder={`${noun} name — leave blank to use the name in the pasted text`}
            aria-label={`New ${noun} name`}
            onChange={(e) => {
              setNewName(e.target.value);
              clearOutcome();
            }}
          />
          <span className="rail-hint">
            Required for a straight clipboard copy: KiCad names it after its own clipboard
            library (<span className="mono">clipboard:&lt;uuid&gt;</span>), which is not a name.
          </span>
        </div>
      ) : null}
      <div className="skill-desc">
        <input
          className="text"
          value={comment}
          maxLength={2000}
          placeholder="What changed and why — kept in the version history"
          aria-label="Version comment"
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
      {!creating ? (
        <div className="skill-desc">
          <label className="proj-inline-field proj-check">
            <input
              type="checkbox"
              checked={minorChange}
              onChange={(e) => setMinorChange(e.target.checked)}
            />
            Small change — keep the existing verifications and production sign-offs
          </label>
          <span className="rail-hint">
            Tick only for an edit that cannot change what reaches the board: silkscreen,
            fab, a description. A moved pad or a changed pin must drop them, and leaving
            this unticked lets the platform compare the pad and pin fingerprints itself.
          </span>
        </div>
      ) : null}
      <div className="btn-row">
        <button
          type="button"
          className="btn btn-accent"
          disabled={busy || !src.trim() || !comment.trim()}
          onClick={() => void file()}
        >
          {busy ? "Publishing…" : creating ? `Publish new ${noun}` : "Publish version"}
        </button>
        <button type="button" className="btn" disabled={rendering || !src.trim()} onClick={() => void preview()}>
          {rendering ? "Rendering…" : stale ? "Re-render preview" : "Preview"}
        </button>
        {!creating ? (
          <button
            type="button"
            className="btn"
            disabled={busy || src === (publishedSource ?? "")}
            onClick={() => {
              setSrc(publishedSource ?? "");
              clearOutcome();
            }}
          >
            Reset to published
          </button>
        ) : null}
        {src.trim() && !comment.trim() ? (
          <span className="muted rail-hint">A comment is required.</span>
        ) : null}
      </div>

      {previewError ? <ErrorBanner message={previewError} /> : null}
      {previewUrl ? (
        <div className="card pad">
          <h2 className="card-title">
            Preview of the pasted text{stale ? " (out of date — re-render)" : ""}
          </h2>
          <div className="preview-fill template-preview">
            <img src={previewUrl} alt={`${noun} preview`} />
          </div>
        </div>
      ) : null}

      {error ? <ErrorBanner message={error} /> : null}
      {result ? (
        <>
          <div className="banner-ok">
            Published v{result.version_no}. It is live in the library and the KiCad mirror;
            what still needs checking is in <Link to="/reviews">Reviews</Link>.
          </div>
          {result.warnings.length > 0 ? (
            <div className="banner-warn">
              {result.warnings.map((w) => (
                <div key={w}>{w}</div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </>
  );
}
