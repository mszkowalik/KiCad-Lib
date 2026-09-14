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
import ReviewSubjectRows from "./ReviewSubjectRows";
import GeometryPreview from "./GeometryPreview";
import { ErrorBanner, Spinner } from "./Ui";

/**
 * The verification workbench — everything a check needs, in one expansion row.
 *
 * Verifying used to mean: queue → component page → three cards → the datasheet
 * on another screen → back → next row, four hundred times. This puts the
 * checklist and the drawings it is checked against side by side, and the
 * ReviewCards write the same records the component page writes. Prev/next walk
 * the filtered queue without closing the bench.
 *
 * The datasheet is a LINK, not a frame (user request 2026-09-14). It used to
 * render in place, and a 40-page viewer with its own scroll, zoom and page
 * state pushed the checks off the screen they were meant to sit beside. In a
 * tab it can go on a second monitor, which is how it is actually read.
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

  return (
    <div className="workbench">
      <div className="workbench-cards">
        <div className="workbench-head">
          <Link className="comp-link" to={`/library/components/${compId}`}>
            {detail.name}
          </Link>{" "}
          <span className="muted mono">v{detail.current_version_no ?? "?"}</span>
        </div>
        {/* One fold per subject, same component as the component page. The
            three cards used to be stacked OPEN, so the checklist somebody came
            for started below two other subjects' checks (user report
            2026-09-14). */}
        <ReviewSubjectRows
          rows={[
            { key: "component", label: "Component data", id: compId },
            ...(live?.symbol
              ? [{ key: "symbol" as const, label: `Symbol — ${live.symbol.name}`, id: live.symbol.id }]
              : []),
            ...(live?.footprint
              ? [{
                  key: "footprint" as const,
                  label: `Footprint — ${live.footprint.name}`,
                  id: live.footprint.id,
                }]
              : []),
          ]}
          parts={detail.review?.parts ?? {}}
          onChanged={onChanged ? () => onChanged() : undefined}
          storageKey={`workbench:${compId}`}
        />
      </div>
      <div className="workbench-side">
        <div className="workbench-previews">
          {detail.current_version_no !== null && live?.symbol ? (
            <GeometryPreview
              className="workbench-preview"
              src={symbolSvgUrl(compId, detail.current_version_no)}
              alt="symbol"
              missingText="no symbol render"
            />
          ) : null}
          {live?.footprint ? (
            <GeometryPreview
              className="workbench-preview"
              src={templatePreviewUrl("footprints", live.footprint.id, footprintVersionId)}
              alt="footprint"
              missingText="no footprint render"
              board
            />
          ) : null}
        </div>
        {/* A LINK, not an embedded viewer (user request 2026-09-14). The
            bench renders the drawings because they are small and there is no
            other way to see them beside the checklist; a datasheet is 40 pages
            in a viewer with its own scroll, zoom and page state, and it pushed
            the checks off the screen it was meant to sit beside. Opened in a
            tab it can live on a second monitor, which is how it is actually
            read. */}
        {sheets.length ? (
          <div className="btn-row">
            {sheets.map((d, i) => (
              <a
                key={d.id}
                className="btn btn-sm"
                href={datasheetFileUrl(d.id)}
                target="_blank"
                rel="noreferrer"
                title="Opens in a new tab"
              >
                {d.label || `Datasheet ${i + 1}`} ↗
              </a>
            ))}
          </div>
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
        <GeometryPreview
          className="workbench-preview workbench-preview-lg"
          src={templatePreviewUrl(kind === "symbol" ? "symbols" : "footprints", id, versionId)}
          alt={name}
          missingText="no published version to preview"
          board={kind === "footprint"}
        />
      </div>
    </div>
  );
}
