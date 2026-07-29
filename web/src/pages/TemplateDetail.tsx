import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  deleteFootprint,
  errorMessage,
  getTemplate,
  isAbortError,
  saveFootprintDisplayName,
  templatePreviewUrl,
  type TemplateDetail as TemplateDetailT,
  type TemplateKind,
} from "../api";
import CommentsPanel from "../components/CommentsPanel";
import { useDialog } from "../components/Dialog";
import { ErrorBanner, Spinner } from "../components/Ui";

function isKind(k: string | undefined): k is TemplateKind {
  return k === "symbols" || k === "footprints";
}

/** Scalar parsed facts (skip the big pin/pad arrays), prettified keys. */
function scalarFacts(parsed: Record<string, unknown>): [string, string][] {
  const out: [string, string][] = [];
  for (const [k, v] of Object.entries(parsed ?? {})) {
    if (v === null || v === undefined || typeof v === "object") continue;
    const label = k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    out.push([label, typeof v === "boolean" ? (v ? "yes" : "no") : String(v)]);
  }
  return out;
}

export default function TemplateDetail() {
  const { kind, id: idParam } = useParams<{ kind: string; id: string }>();
  const id = Number(idParam);
  const [data, setData] = useState<TemplateDetailT | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameNotice, setNameNotice] = useState<string | null>(null);
  const [retiring, setRetiring] = useState(false);
  const navigate = useNavigate();
  const dialog = useDialog();

  /** Footprints only: retire it entirely. The server refuses (409) while any
   *  component version — current or historical — still pins a version of it,
   *  so history stays reproducible; that refusal is shown verbatim. */
  const retire = async () => {
    if (!data) return;
    const ok = await dialog.confirm(
      `Retire footprint ${data.name} — every version and its mirror file? ` +
        `There is no draft/approve path here and no version to roll back to.`,
      { title: "Retire footprint", confirmLabel: "Retire", tone: "danger" },
    );
    if (!ok) return;
    setRetiring(true);
    try {
      await deleteFootprint(id);
      navigate("/library/templates?tab=footprints");
    } catch (err) {
      setError(errorMessage(err));
      setRetiring(false);
    }
  };

  useEffect(() => {
    if (!isKind(kind) || !Number.isFinite(id)) {
      setError("Unknown template.");
      return;
    }
    const ctrl = new AbortController();
    setData(null);
    setError(null);
    setPreviewFailed(false);
    setNameNotice(null);
    getTemplate(kind, id, ctrl.signal)
      .then((d) => {
        setData(d);
        setNameDraft(d.display_name ?? "");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [kind, id]);

  const noun = kind === "footprints" ? "footprint" : "symbol";

  const saveName = async () => {
    if (data === null || savingName) return;
    setSavingName(true);
    setNameNotice(null);
    try {
      const res = await saveFootprintDisplayName(data.id, nameDraft);
      setData({ ...data, display_name: res.display_name });
      const rebuilt = res.rebuilt_libraries.length
        ? `rebuilt ${res.rebuilt_libraries.join(", ")}`
        : "no components use this footprint yet";
      setNameNotice(
        res.mirror_warnings.length
          ? `Saved — ${rebuilt}, with warnings: ${res.mirror_warnings.join("; ")}`
          : `Saved — ${rebuilt}.`,
      );
    } catch (err) {
      setNameNotice(errorMessage(err));
    } finally {
      setSavingName(false);
    }
  };

  if (error) {
    return (
      <div className="main-solo">
        <div className="page">
          <Link to="/library/templates" className="backlink">
            ← All templates
          </Link>
          <ErrorBanner message={error} />
        </div>
      </div>
    );
  }

  if (!isKind(kind) || data === null) {
    return (
      <div className="main-solo">
        <div className="page">
          <Link to="/library/templates" className="backlink">
            ← All templates
          </Link>
          <Spinner label="Loading template" />
        </div>
      </div>
    );
  }

  const facts = scalarFacts(data.parsed);

  return (
    <div className="main-solo">
      <div className="page">
        <Link to="/library/templates" className="backlink">
          ← All templates
        </Link>
        <div className="toolbar">
          <h1 className="mono">{data.name}</h1>
          <span className="pill neutral">{data.kind}</span>
          {data.version_no !== null ? (
            <span className="toolbar-total">v{data.version_no}</span>
          ) : null}
        </div>

        {noun === "footprint" ? (
          <div className="card pad">
            <h2 className="card-title">Package name</h2>
            <div className="skill-desc">
              <input
                className="text"
                value={nameDraft}
                maxLength={200}
                placeholder="Short package name, e.g. 0402 or SOT-23-6"
                onChange={(e) => setNameDraft(e.target.value)}
                aria-label="Footprint package name"
                spellCheck={false}
              />
              <span className="rail-hint">
                What <span className="mono">{"{Footprint_Name}"}</span> resolves to in a
                component's <span className="mono">ki_description</span>. Stored on the
                footprint, so every component using it stays in step — saving rebuilds the
                affected symbol libraries.
              </span>
            </div>
            <div className="btn-row">
              <button
                type="button"
                className="btn btn-accent"
                disabled={savingName || nameDraft === (data.display_name ?? "")}
                onClick={() => void saveName()}
              >
                {savingName ? "Saving…" : "Save name"}
              </button>
              {nameNotice ? <span className="muted rail-hint">{nameNotice}</span> : null}
            </div>
          </div>
        ) : null}

        <div className="card pad">
          <h2 className="card-title">Preview</h2>
          <div className="preview-fill template-preview">
            {previewFailed ? (
              <p className="placeholder">
                Preview unavailable — the render service (kicad-cli) is offline.
              </p>
            ) : (
              <img
                src={templatePreviewUrl(kind, id)}
                alt={`${data.name} preview`}
                onError={() => setPreviewFailed(true)}
              />
            )}
          </div>
        </div>

        <div className="card pad">
          <h2 className="card-title">Details</h2>
          <table className="kv">
            <tbody>
              {data.created_at ? (
                <tr>
                  <td>Published</td>
                  <td>{new Date(data.created_at).toLocaleString()}</td>
                </tr>
              ) : null}
              {data.created_by ? (
                <tr>
                  <td>Author</td>
                  <td>{data.created_by}</td>
                </tr>
              ) : null}
              {data.comment ? (
                <tr>
                  <td>Version note</td>
                  <td>{data.comment}</td>
                </tr>
              ) : null}
              {facts.map(([label, value]) => (
                <tr key={label}>
                  <td>{label}</td>
                  <td className="mono">{value}</td>
                </tr>
              ))}
              {data.models && data.models.length > 0 ? (
                <tr>
                  <td>3D models</td>
                  <td className="mono">{data.models.join(", ")}</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="card pad">
          <h2 className="card-title">
            Used by {data.used_by.length} component{data.used_by.length === 1 ? "" : "s"}
          </h2>
          {data.used_by.length === 0 ? (
            <p className="muted">Not used by any component yet.</p>
          ) : (
            <p>
              {data.used_by.map((u, i) => (
                <span key={u.id}>
                  {i > 0 ? ", " : ""}
                  <Link to={`/library/components/${u.id}`} className="comp-link">
                    {u.name}
                  </Link>
                </span>
              ))}
            </p>
          )}
        </div>

        {data.source_text ? (
          <details className="card pad">
            <summary>Source ({noun === "footprint" ? ".kicad_mod" : ".kicad_sym"})</summary>
            <pre className="code-block">{data.source_text}</pre>
          </details>
        ) : null}

        {kind === "footprints" ? (
          <div className="card pad danger-card">
            <h2>Retire this footprint</h2>
            <p className="muted">
              Deletes the footprint, all its versions and its file in the mirror. The server
              refuses while any component version — including historical ones — still pins it,
              and names the count.
            </p>
            <button className="btn btn-danger" disabled={retiring} onClick={() => void retire()}>
              {retiring ? "Retiring…" : "Retire footprint"}
            </button>
          </div>
        ) : null}

        <CommentsPanel kind={kind} id={id} noun={noun} />
      </div>
    </div>
  );
}
