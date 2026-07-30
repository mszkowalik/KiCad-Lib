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
 * only ever files a DRAFT: approval, and the published before/after, live in
 * the Proposals view.
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
  const [comment, setComment] = useState("");
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
   *  mistake is visible before it becomes a proposal. */
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
        ? await proposeNewTemplate(kind, src, comment)
        : await proposeTemplateEdit(kind, id, src, comment);
      setResult(res);
      if (creating) {
        setSrc("");
        setComment("");
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
          ? `Paste a whole ${ext} body, or drop the file on the box. The name is read from the pasted text — there is no name field to disagree with it.`
          : `Paste the ${noun} from the KiCad editor, or drop a ${ext} file on the box. The text is prefilled with the published source, so select all and paste over it.`}{" "}
        Filing creates a <strong>draft</strong>. Nothing changes until you approve it in
        Proposals, where you get the visual before/after.
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
      <div className="skill-desc">
        <input
          className="text"
          value={comment}
          maxLength={2000}
          placeholder="What changed and why — shown in the proposal review"
          aria-label="Proposal comment"
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
      <div className="btn-row">
        <button
          type="button"
          className="btn btn-accent"
          disabled={busy || !src.trim() || !comment.trim()}
          onClick={() => void file()}
        >
          {busy ? "Filing…" : creating ? `File new ${noun}` : "File draft"}
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
            Draft v{result.version_no} filed. <Link to="/proposals">Review it in Proposals</Link> to
            see the before/after and approve it.
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
