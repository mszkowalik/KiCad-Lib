import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  deleteSimModel,
  errorMessage,
  getSimModel,
  isAbortError,
  proposeSimModelEdit,
  type SimModelDetail as SimModelDetailT,
} from "../api";
import { useDialog } from "../components/Dialog";
import { BackLink, ErrorBanner, Spinner } from "../components/Ui";

/** A sim model: the .subckt source, its interface, who links to it, and the
 *  paste box that PUBLISHES the next version. No preview — there is nothing
 *  to draw; the "look before the fact" here is the parsed port/param echo. */
export default function SimModelDetail() {
  const { id: idParam } = useParams<{ id: string }>();
  const id = Number(idParam);
  const [data, setData] = useState<SimModelDetailT | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [comment, setComment] = useState("");
  const [filing, setFiling] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const dialog = useDialog();
  const navigate = useNavigate();
  const generated = data?.kind === "composed";

  useEffect(() => {
    if (!Number.isFinite(id)) {
      setError("Unknown sim model.");
      return;
    }
    const ctrl = new AbortController();
    setData(null);
    setError(null);
    setNotice(null);
    getSimModel(id, ctrl.signal)
      .then((d) => {
        setData(d);
        setText(d.source_text ?? "");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [id]);

  const remove = async () => {
    if (!data || filing) return;
    const ok = await dialog.confirm(
      `Delete ${data.name}? The .subckt disappears from the generated SPICE library.`,
      { title: "Delete sim model", confirmLabel: "Delete", tone: "danger" },
    );
    if (!ok) return;
    setFiling(true);
    setNotice(null);
    try {
      await deleteSimModel(id);
      navigate("/library/templates?tab=sim");
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setFiling(false);
    }
  };

  const file = async () => {
    if (!data || filing) return;
    setFiling(true);
    setNotice(null);
    try {
      const res = await proposeSimModelEdit(id, text, comment);
      setNotice(
        res.mirror_warnings.length
          ? `Published v${res.version_no} — mirror warnings: ${res.mirror_warnings.join("; ")}`
          : `Published v${res.version_no}. Links stamped against the old port list ` +
            `show as stale on their symbols until re-confirmed.`,
      );
      setComment("");
      const fresh = await getSimModel(id);
      setData(fresh);
      setText(fresh.source_text ?? "");
    } catch (err) {
      setNotice(errorMessage(err));
    } finally {
      setFiling(false);
    }
  };

  if (error) {
    return (
      <div className="main-solo">
        <div className="page">
          <BackLink to="/library/templates?tab=sim" className="backlink">
            ← All templates
          </BackLink>
          <ErrorBanner message={error} />
        </div>
      </div>
    );
  }
  if (data === null) {
    return (
      <div className="main-solo">
        <div className="page">
          <BackLink to="/library/templates?tab=sim" className="backlink">
            ← All templates
          </BackLink>
          <Spinner label="Loading sim model" />
        </div>
      </div>
    );
  }

  return (
    <div className="main-solo">
      <div className="page">
        <BackLink to="/library/templates?tab=sim" className="backlink">
          ← All templates
        </BackLink>
        <div className="toolbar">
          <h1 className="mono">{data.name}</h1>
          <span className="pill neutral">
            {data.kind === "primitive"
              ? "primitive"
              : data.kind === "composed"
                ? "generated"
                : "sim model"}
          </span>
          {data.version_no !== null ? (
            <span className="toolbar-total">v{data.version_no}</span>
          ) : null}
        </div>
        {data.kind === "primitive" ? (
          <p className="muted">
            A building block. Other models instantiate it by name, and a symbol whose part
            IS the primitive (a diode, a switch) can link to it directly.
          </p>
        ) : null}
        {generated ? (
          <p className="muted">
            Built from library blocks, not typed. It belongs to the symbol below and is
            rebuilt whenever that composition is saved or one of its blocks publishes a
            new version — so edit it on the symbol's Simulation card, where the block
            design lives. Text pasted here would be overwritten.
          </p>
        ) : null}

        <div className="card pad">
          <h2 className="card-title">Interface</h2>
          <table className="kv">
            <tbody>
              <tr>
                <td>Ports</td>
                <td className="mono">{data.ports.join("  ") || "—"}</td>
              </tr>
              <tr>
                <td>Parameters</td>
                <td className="mono">
                  {Object.entries(data.params)
                    .map(([k, v]) => `${k}=${v}`)
                    .join("  ") || "—"}
                </td>
              </tr>
              {data.instantiates.length > 0 ? (
                <tr>
                  <td>Instantiates</td>
                  <td className="mono">{data.instantiates.join(", ")}</td>
                </tr>
              ) : null}
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
            </tbody>
          </table>
        </div>

        <div className="card pad">
          <h2 className="card-title">
            Linked by {data.linked_symbols.length} symbol
            {data.linked_symbols.length === 1 ? "" : "s"}
          </h2>
          {data.linked_symbols.length === 0 ? (
            <p className="muted">
              {data.kind === "primitive"
                ? "No symbol links to it directly — other models instantiate it by name."
                : "No symbol links to this model yet."}
            </p>
          ) : (
            <p>
              {data.linked_symbols.map((u, i) => (
                <span key={u.id}>
                  {i > 0 ? ", " : ""}
                  <Link to={`/library/templates/symbols/${u.id}`} className="comp-link">
                    {u.name}
                  </Link>
                </span>
              ))}
            </p>
          )}
        </div>

        {data.source_text ? (
          <div className="card pad">
            <h2 className="card-title">Source (.subckt)</h2>
            <pre className="code-block">{data.source_text}</pre>
          </div>
        ) : null}

        {data.linked_symbols.length === 0 ? (
          <div className="card pad">
            <h2 className="card-title">Delete</h2>
            <p className="muted">
              Nothing links to this model. Deleting is refused while another model still
              instantiates it, so a building block in use cannot be removed by accident.
            </p>
            <button
              type="button"
              className="btn btn-danger"
              disabled={filing}
              onClick={() => void remove()}
            >
              Delete model
            </button>
            {notice ? <p className="muted">{notice}</p> : null}
          </div>
        ) : null}

        {generated ? null : (
        <details className="card pad">
          <summary>Propose an edit</summary>
          <p className="muted">
            Publishes immediately. Changing the PORT LIST flags every linked symbol's map
            as stale — its Sim fields are withheld until someone re-confirms the map there.
            Changing parameters or internals carries links untouched.
          </p>
          <textarea
            className="text skill-textarea sim-src mono"
            rows={14}
            value={text}
            spellCheck={false}
            onChange={(e) => setText(e.target.value)}
            aria-label="Subcircuit source"
          />
          <div className="btn-row">
            <input
              className="text"
              placeholder="What changed, and against which datasheet"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              aria-label="Version comment"
            />
            <button
              type="button"
              className="btn btn-accent"
              disabled={filing || !text.trim() || !comment.trim() || text === data.source_text}
              onClick={() => void file()}
            >
              {filing ? "Publishing…" : "Publish new version"}
            </button>
          </div>
          {notice ? <p className="muted">{notice}</p> : null}
        </details>
        )}

        {data.versions.length > 1 ? (
          <details className="card pad">
            <summary>History ({data.versions.length} versions)</summary>
            <table className="kv">
              <tbody>
                {data.versions.map((v) => (
                  <tr key={v.version_no}>
                    <td className="mono">v{v.version_no}</td>
                    <td>
                      {new Date(v.created_at).toLocaleString()} · {v.created_by}
                      {v.comment ? ` — ${v.comment}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        ) : null}
      </div>
    </div>
  );
}
