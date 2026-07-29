import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createComponent, errorMessage } from "../api";
import {
  BaseSymbolSelect,
  buildProperties,
  CategorySelect,
  DatasheetsEditor,
  FootprintDatalist,
  newEditRow,
  PropertiesEditor,
  usePickers,
  type EditDs,
  type EditRow,
} from "../components/editing";
import { ErrorBanner } from "../components/Ui";

const FP_DATALIST_ID = "fp-options-new";

function starterRows(): EditRow[] {
  return [newEditRow("Value"), newEditRow("Footprint"), newEditRow("ki_description")];
}

export default function NewComponent() {
  const navigate = useNavigate();
  const { pickers, pickerError } = usePickers(true);

  const [name, setName] = useState("");
  const [base, setBase] = useState("");
  const [catId, setCatId] = useState<number | "">("");
  const [rows, setRows] = useState<EditRow[]>(starterRows);
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const [datasheets, setDatasheets] = useState<EditDs[]>([]);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = !submitting && name.trim() !== "" && base !== "" && catId !== "";

  const submit = async () => {
    if (catId === "" || base === "") return;
    const built = buildProperties(rows, newKey, newValue);
    if ("error" in built) {
      setError(built.error);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await createComponent({
        name: name.trim(),
        base_component: base,
        category_id: catId,
        properties: built.properties,
        removed_properties: null,
        datasheets:
          datasheets.length > 0
            ? datasheets.map((d) => ({
                id: d.id,
                label: d.label.trim() || "Datasheet",
                source_url: d.source_url.trim() || null,
              }))
            : null,
        comment: comment.trim() || null,
      });
      navigate(`/library/components/${res.component_id}`);
    } catch (err) {
      setError(errorMessage(err));
      setSubmitting(false);
    }
  };

  return (
    <div className="main-solo">
      <div className="page">
        <Link to="/" className="backlink">
          &larr; Browse
        </Link>
        <h1>New component</h1>
        <p className="muted">
          Creates a published v1 directly — you are the approval. Names are globally unique.
        </p>

        {pickerError ? <ErrorBanner message={`Pickers failed to load: ${pickerError}`} /> : null}
        {error ? <ErrorBanner message={error} /> : null}

        <section className="card pad edit-card">
          <div className="edit-grid">
            <label>
              Name
              <input
                type="text"
                className="text mono new-name"
                value={name}
                placeholder="e.g. RC0402FR-071KL"
                onChange={(e) => setName(e.target.value)}
                autoFocus
              />
            </label>
            <span />
            <label>
              Base symbol
              <BaseSymbolSelect value={base} pickers={pickers} onChange={setBase} />
            </label>
            <label>
              Category
              <CategorySelect value={catId} pickers={pickers} fallbackLabel="" onChange={setCatId} />
            </label>
          </div>
          <p className="muted edit-hint">
            The <span className="mono">Footprint</span> property drives the pinned footprint —
            its value field suggests <span className="mono">7Sigma:</span> footprints.
          </p>
          <FootprintDatalist id={FP_DATALIST_ID} pickers={pickers} />
        </section>

        <section className="card">
          <h3 className="card-title pad-title">Properties</h3>
          <PropertiesEditor
            rows={rows}
            newKey={newKey}
            newValue={newValue}
            fpDatalistId={FP_DATALIST_ID}
            onRows={setRows}
            onNew={(p) => {
              if (p.newKey !== undefined) setNewKey(p.newKey);
              if (p.newValue !== undefined) setNewValue(p.newValue);
            }}
            onError={setError}
          />
        </section>

        <section className="card">
          <h3 className="card-title pad-title">Datasheets</h3>
          <DatasheetsEditor rows={datasheets} onRows={setDatasheets} />
        </section>

        <section className="card pad">
          <div className="edit-actions">
            <input
              type="text"
              className="text comment"
              placeholder="comment (optional)"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
            <button
              type="button"
              className="btn btn-accent"
              disabled={!canSubmit}
              onClick={() => void submit()}
            >
              {submitting ? "Creating…" : "Create component"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
