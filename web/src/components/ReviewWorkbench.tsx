import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  datasheetFileUrl,
  errorMessage,
  getComponent,
  getTemplate,
  getVersion,
  isAbortError,
  symbolSvgUrl,
  templatePreviewUrl,
  type ComponentDetail,
  type DatasheetRow,
  type VersionDetail,
} from "../api";
import ReviewCard from "./ReviewCard";
import { ErrorBanner, Spinner } from "./Ui";

/**
 * The verification workbench — everything a check needs, in one expansion row.
 *
 * Verifying used to mean: queue → component page → three cards → the datasheet
 * on another screen → back → next row, four hundred times. This puts the
 * checklist and the thing it is checked AGAINST side by side: the archived
 * datasheet renders in place (verification IS comparison), the symbol and
 * footprint render beside it, and the ReviewCards write the same records the
 * component page writes. Prev/next walk the filtered queue without closing
 * the bench.
 */
export function ComponentWorkbench({
  compId,
  onChanged,
}: {
  compId: number;
  /** Called after any verification is recorded, so the queue row can refresh. */
  onChanged?: () => void;
}) {
  const [detail, setDetail] = useState<ComponentDetail | null>(null);
  const [version, setVersion] = useState<VersionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dsIndex, setDsIndex] = useState(0);
  // The pinned footprint's LIVE version id — the preview URL's cache key, so a
  // freshly pushed land pattern shows the new drawing rather than the picture
  // the browser already has. The component's own version tells us which
  // version it PINS, which is not necessarily what the library serves.
  const [footprintVersionId, setFootprintVersionId] = useState<number | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setDetail(null);
    setVersion(null);
    setError(null);
    setDsIndex(0);
    setFootprintVersionId(null);
    getComponent(compId, ctrl.signal)
      .then(async (d) => {
        setDetail(d);
        if (d.current_version_no === null) return;
        const v = await getVersion(compId, d.current_version_no, ctrl.signal);
        setVersion(v);
        if (v.footprint)
          setFootprintVersionId(
            (await getTemplate("footprints", v.footprint.id, ctrl.signal)).version_id,
          );
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [compId]);

  if (error) return <ErrorBanner message={error} />;
  if (detail === null) return <Spinner label="Loading component" />;

  const live = detail.versions.find((v) => v.version_no === detail.current_version_no) ?? null;
  // the KiCad-native datasheet first, then anything with an archived file
  const sheets: DatasheetRow[] = (version?.datasheets ?? []).filter((d) => d.has_file);
  const sheet = sheets[dsIndex] ?? null;

  return (
    <div className="workbench">
      <div className="workbench-cards">
        <div className="workbench-head">
          <Link className="comp-link" to={`/library/components/${compId}`}>
            {detail.name}
          </Link>{" "}
          <span className="muted mono">v{detail.current_version_no ?? "?"}</span>
        </div>
        <ReviewCard kind="component" id={compId} label="Component data" onChange={onChanged ? () => onChanged() : undefined} />
        {live?.symbol ? (
          <ReviewCard
            kind="symbol"
            id={live.symbol.id}
            label={`Symbol — ${live.symbol.name}`}
            onChange={onChanged ? () => onChanged() : undefined}
          />
        ) : null}
        {live?.footprint ? (
          <ReviewCard
            kind="footprint"
            id={live.footprint.id}
            label={`Footprint — ${live.footprint.name}`}
            onChange={onChanged ? () => onChanged() : undefined}
          />
        ) : null}
      </div>
      <div className="workbench-side">
        <div className="workbench-previews">
          {detail.current_version_no !== null && live?.symbol ? (
            <img
              className="workbench-preview"
              src={symbolSvgUrl(compId, detail.current_version_no)}
              alt="symbol"
            />
          ) : null}
          {live?.footprint ? (
            <img
              className="workbench-preview"
              src={templatePreviewUrl("footprints", live.footprint.id, footprintVersionId)}
              alt="footprint"
            />
          ) : null}
        </div>
        {sheet ? (
          <>
            {sheets.length > 1 ? (
              <div className="btn-row">
                {sheets.map((d, i) => (
                  <button
                    key={d.id}
                    type="button"
                    className={"btn btn-sm" + (i === dsIndex ? " btn-primary" : "")}
                    onClick={() => setDsIndex(i)}
                  >
                    {d.label || `Datasheet ${i + 1}`}
                  </button>
                ))}
              </div>
            ) : null}
            <iframe
              className="workbench-datasheet"
              src={datasheetFileUrl(sheet.id)}
              title={sheet.label || "datasheet"}
            />
          </>
        ) : (
          <p className="muted">
            No archived datasheet to compare against — items that need one are honest skips
            (reason: no document).
          </p>
        )}
      </div>
    </div>
  );
}

/** The template flavour: one ReviewCard beside the rendered drawing. Templates
 *  carry no datasheet of their own — the components using them do. */
export function TemplateWorkbench({
  kind,
  id,
  name,
  versionId,
  onChanged,
}: {
  kind: "symbol" | "footprint";
  id: number;
  name: string;
  /** Live version id, for the preview URL's cache key. */
  versionId?: number | null;
  onChanged?: () => void;
}) {
  return (
    <div className="workbench">
      <div className="workbench-cards">
        <div className="workbench-head">
          <Link className="comp-link" to={`/library/templates/${kind}s/${id}`}>
            {name}
          </Link>
        </div>
        <ReviewCard kind={kind} id={id} onChange={onChanged ? () => onChanged() : undefined} />
      </div>
      <div className="workbench-side">
        <img
          className="workbench-preview workbench-preview-lg"
          src={templatePreviewUrl(kind === "symbol" ? "symbols" : "footprints", id, versionId)}
          alt={name}
        />
      </div>
    </div>
  );
}
