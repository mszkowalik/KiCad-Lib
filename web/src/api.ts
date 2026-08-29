/** Typed client for the Project Management Platform API.
 *
 * Shapes mirror the FastAPI routers in platform/api/app/routers/
 * (categories.py, components.py, import_station.py).
 */
import { APP_BASE } from "./appbase";

/** Where the API lives, as a prefix for every request path.
 *
 * Defaults to APP_BASE — same origin, same mount point. That is what the
 * deployed images do: nginx serves the SPA and proxies /api, /kicad and /files
 * to the api container (see web/default.conf.template), and the Vite dev
 * server proxies the same paths (see vite.config.ts). Under a prefix the API
 * rides along with the app, so APP_BASE="/lib" gives "/lib/api/…".
 *
 * Set VITE_API_URL only to point a build at an API on another origin — it is
 * inlined at build time, so a value baked into an image would tie that image
 * to one hostname, which is why it is not the default.
 */
export const API_URL: string = import.meta.env.VITE_API_URL ?? APP_BASE;

/** API address for messages the user reads — "" is same-origin. */
export const apiOrigin = (): string =>
  API_URL || (typeof window === "undefined" ? "the same origin" : window.location.origin);

// ---------------------------------------------------------------- categories

export interface CategoryNode {
  id: number;
  name: string;
  parent_id: number | null;
  /** Components whose current version sits directly in this category. */
  component_count: number;
  /** component_count plus everything under descendant categories. */
  total_count: number;
  has_defaults: boolean;
  children: CategoryNode[];
}

// ---------------------------------------------------------------- components

export interface ComponentListItem {
  id: number;
  name: string;
  mfg_pn: string;
  manufacturer: string;
  version_no: number;
  status: string;
  category_id: number | null;
  category_path: string;
  base_component: string;
  description: string;
  value: string;
  footprint: string;
  lcsc: string;
  /** Unit price at the 1000-qty break (or the nearest tier above, per `bulk_qty`). */
  price_bulk: string;
  /** Which ladder tier `price_bulk` was actually sourced from, e.g. "1000", "5000". */
  bulk_qty: string;
  /** Primary datasheet source URL ("" when none). */
  datasheet: string;
  /** Production sign-off state — see SignoffState. */
  signoff: SignoffState;
  /** Effective review state (component + pinned symbol/footprint legs). */
  review: ReviewState;
  review_provenance: ReviewActor | null;
  lifecycle: LifecycleState;
}

export interface ComponentListResponse {
  total: number;
  page: number;
  page_size: number;
  items: ComponentListItem[];
}

/** A drawing a component version PINS. `version_no` is what this component was
 *  generated against; `current_version_no` is what the library serves KiCad
 *  today, so `is_current === false` means the part is drawn on a superseded
 *  symbol or land pattern. `id` is the parent row, for linking. */
export interface PinnedRef {
  id: number;
  name: string;
  version_no: number;
  current_version_no: number | null;
  is_current: boolean;
}

export interface VersionSummary {
  version_no: number;
  status: string;
  created_at: string;
  created_by: string | null;
  approved_by: string | null;
  comment: string | null;
  category_id: number | null;
  category_path: string;
  base_component: string;
  symbol: PinnedRef | null;
  footprint: PinnedRef | null;
}

export interface ComponentDetail {
  id: number;
  name: string;
  in_library: boolean;
  /** False = virtual part (test point, logo, fiducial, mounting hole):
   *  excluded from project BOM totals, orders and stock checks. */
  purchasable: boolean;
  current_version_no: number | null;
  versions: VersionSummary[];
  /** Production sign-off state of the CURRENT version — see SignoffState. */
  signoff: SignoffState;
  lifecycle: LifecycleState;
  /** Effective review state: weakest of the component's own record and its
   *  pinned symbol/footprint records. */
  review: {
    state: ReviewState;
    provenance: ReviewActor | null;
    blockers: string[];
    /** Per-drawing breakdown the aggregate is the WEAKEST of, so the page can
     *  say WHICH of the three is unchecked instead of only "partial". */
    parts: Partial<Record<"component" | "symbol" | "footprint", ReviewPart>>;
  };
}

/** One subject's verification state within `ComponentDetail.review.parts`. */
export interface ReviewPart {
  state: ReviewState;
  provenance: ReviewActor | null;
  answered?: number;
  total?: number;
  skipped?: number;
  failed?: number;
  flagged?: number;
  unanswered?: string[];
}

export interface PropertyRow {
  position: number;
  key: string;
  value: string | null;
  is_null: boolean;
  hide: boolean;
  show_name: boolean;
  layout: Record<string, unknown> | null;
  resolved_value: string;
}

/** Auto-managed LCSC pricing, component-scoped (identical across versions). */
export interface Prices {
  price_1: string | null;
  price_100: string | null;
  price_bulk: string | null;
  bulk_qty: string | null;
  source: string | null;
  updated: string | null;
}

export interface DatasheetVersionInfo {
  version_no: number;
  fetched_at: string;
  size_bytes: number;
  sha256: string;
  text_layer: TextLayer;
  page_count: number | null;
  text_pages: number | null;
}

/** Can this document be searched and read, or are its pages only images?
 *  Decided once at store time by the API — see
 *  api/app/services/datasheet_store.classify_text_layer for the rules.
 *
 *  `text`  searchable — (nearly) every page carries a text layer
 *  `mixed` some pages are text, the rest are images
 *  `scan`  no text at all: unsearchable, and the agent reads blank pages
 *  `none`  not a PDF (an archived web page, a DXF, a STEP file…)
 *  `error` a PDF that would not open, or one locked with a password
 *  `""`    not classified yet (the backfill has not reached it) */
export type TextLayer = "text" | "mixed" | "scan" | "none" | "error" | "";

/** Datasheet row, component-scoped. Position 0 is the KiCad-native one. */
export interface DatasheetRow {
  id: number;
  position: number;
  label: string;
  source_url: string | null;
  has_file: boolean;
  /** Version number of the current local PDF copy (null = none yet). */
  pdf_version_no: number | null;
  filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  fetched_at: string | null;
  /** Searchability of the CURRENT stored copy. */
  text_layer: TextLayer;
  page_count: number | null;
  text_pages: number | null;
  versions: DatasheetVersionInfo[];
}

/** Which exact PDF content a component version used (version-scoped). */
export interface DatasheetPin {
  datasheet_id: number;
  label: string;
  pdf_version_no: number | null;
}

export interface VersionDetail extends VersionSummary {
  component_id: number;
  component_name: string;
  prices: Prices | null;
  datasheets: DatasheetRow[];
  datasheet_pins: DatasheetPin[];
  removed_properties: string[];
  properties: PropertyRow[];
}

// ------------------------------------------------------------------ editing

export interface SymbolListItem {
  id: number;
  name: string;
  version_no: number | null;
  /** Cache key for templatePreviewUrl — see that function. */
  version_id: number | null;
  pin_count: number | null;
  comment_count: number;
}

export interface FootprintListItem {
  id: number;
  name: string;
  version_no: number | null;
  /** Cache key for templatePreviewUrl — see that function. */
  version_id: number | null;
  pad_count: number | null;
  comment_count: number;
}

export interface PropertyIn {
  key: string;
  value: string | null;
  is_null: boolean;
  hide: boolean;
  show_name: boolean;
  layout: Record<string, unknown> | null;
}

/** Datasheet row sent on save. Include `id` of an existing row to keep its
 *  locally-fetched file (preserved only if the URL is unchanged). */
export interface DatasheetIn {
  id: number | null;
  label: string;
  source_url: string | null;
}

export interface VersionCreate {
  base_component: string;
  category_id: number;
  properties: PropertyIn[];
  removed_properties: string[] | null;
  /** null = leave the datasheet set unchanged; an array REPLACES it. */
  datasheets: DatasheetIn[] | null;
  comment: string | null;
}

export interface VersionCreateResponse extends VersionSummary {
  component_id: number;
  component_name: string;
  mirror: Record<string, number>;
  mirror_warnings: string[];
}

// -------------------------------------------------------------------- import

export interface MirrorSummary {
  symbol_libs: number;
  components_in_libs: number;
  footprints: number;
  models3d: number;
  warnings: string[];
}

export interface ImportReport {
  warnings?: string[];
  libraries?: number;
  categories?: number;
  rules?: number;
  skills?: number;
  symbols?: number;
  footprints?: number;
  models3d?: number;
  components?: number;
  properties?: number;
  duration_s?: number;
  mirror?: MirrorSummary;
  // Sync-mode fields (POST /api/import/sync): diff YAML against the DB and
  // create draft proposals. `mode === "sync"` selects the sync report view.
  mode?: string;
  yaml_components?: number;
  new_proposals?: string[];
  edit_proposals?: string[];
  already_pending?: string[];
  skipped?: Array<{ name: string; reason: string }>;
  only_in_db?: string[];
  unchanged?: number;
  proposals_created?: number;
  /** Present on failed runs persisted by the importer. */
  error?: string;
  partial?: ImportReport;
}

export interface ImportLastRun {
  id: number;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  duration_s: number | null;
  report: ImportReport | null;
}

export interface ImportStatus {
  running: boolean;
  stage: string;
  started_at: string | null;
  error: string | null;
  report: ImportReport | null;
  last_run: ImportLastRun | null;
}

// -------------------------------------------------------------------- client

export class ApiError extends Error {
  readonly status: number;
  /** The parsed `detail` payload of a structured refusal, when the body
   *  carried one — lets a caller render context (e.g. the production-run
   *  review warning) instead of only the sentence. */
  readonly detail?: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Human-readable message for any error thrown by this client. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

/** Called by the auth provider when any request comes back 401.
 *
 * The session cookie can die between page loads (logout in another tab, an
 * admin revoking it, plain expiry). Without this hook the SPA would keep
 * rendering with stale data and one failing panel per screen; instead the
 * provider flips to the login page the moment the server stops recognising us.
 */
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    // `include`, not the `same-origin` default: a dev server aimed at a remote
    // API is cross-origin, and the session lives in a cookie. The API sets
    // allow_credentials with an explicit origin list to match.
    res = await fetch(`${API_URL}${path}`, { credentials: "include", ...init });
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw new ApiError(0, `Cannot reach API at ${apiOrigin()} (${errorMessage(err)})`);
  }
  if (!res.ok) {
    let detail = "";
    let detailPayload: unknown;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detailPayload = body.detail;
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (
        body.detail &&
        typeof body.detail === "object" &&
        !Array.isArray(body.detail) &&
        typeof (body.detail as { error?: unknown }).error === "string"
      ) {
        // structured refusal: {error, …context}. The context keys stay in the
        // payload for non-browser callers; `error` is the readable sentence.
        detail = (body.detail as { error: string }).error;
      } else if (Array.isArray(body.detail)) {
        // Pydantic validation errors: [{loc, msg, type}, ...]
        detail = body.detail
          .map((d) =>
            d && typeof d === "object" && "msg" in d
              ? String((d as { msg: unknown }).msg)
              : JSON.stringify(d),
          )
          .join("; ");
      }
    } catch {
      // non-JSON error body — fall through to statusText
    }
    // A dead session must bounce to the login page, not surface as one broken
    // panel per screen. `/api/auth/*` is excluded: a wrong password there is a
    // 401 the login form itself must render.
    if (res.status === 401 && !path.startsWith("/api/auth/")) onUnauthorized?.();
    throw new ApiError(res.status, detail || `${res.status} ${res.statusText}`, detailPayload);
  }
  return (await res.json()) as T;
}

export function getCategories(signal?: AbortSignal): Promise<CategoryNode[]> {
  return request("/api/categories", { signal });
}

export function createCategory(name: string, parent_id: number | null): Promise<unknown> {
  return request("/api/categories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, parent_id }),
  });
}

export function updateCategory(
  id: number,
  body: { name?: string; parent_id?: number | null; position?: number },
): Promise<unknown> {
  return request(`/api/categories/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteCategory(id: number): Promise<{ deleted: number }> {
  return request(`/api/categories/${id}`, { method: "DELETE" });
}

export interface ListComponentsParams {
  q?: string;
  category_id?: number;
  page?: number;
  page_size?: number;
}

export function listComponents(
  params: ListComponentsParams,
  signal?: AbortSignal,
): Promise<ComponentListResponse> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.category_id != null) qs.set("category_id", String(params.category_id));
  if (params.page != null) qs.set("page", String(params.page));
  if (params.page_size != null) qs.set("page_size", String(params.page_size));
  const suffix = qs.toString();
  return request(`/api/components${suffix ? `?${suffix}` : ""}`, { signal });
}

export function getComponent(id: number, signal?: AbortSignal): Promise<ComponentDetail> {
  return request(`/api/components/${id}`, { signal });
}

/** Flag a component as a purchased part or a virtual one (test point, logo,
 *  fiducial, mounting hole) that project BOMs ignore. */
export function setComponentPurchasable(
  id: number,
  purchasable: boolean,
): Promise<{ id: number; purchasable: boolean }> {
  return request(`/api/components/${id}/purchasable`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ purchasable }),
  });
}

/** Flip a component between library part and BOM-only part. Turning a part
 *  back INTO the library requires a pinned symbol (422 otherwise). */
export function setComponentInLibrary(
  id: number,
  inLibrary: boolean,
): Promise<{ id: number; in_library: boolean }> {
  return request(`/api/components/${id}/in-library`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ in_library: inLibrary }),
  });
}

export function getVersion(
  id: number,
  versionNo: number,
  signal?: AbortSignal,
): Promise<VersionDetail> {
  return request(`/api/components/${id}/versions/${versionNo}`, { signal });
}

export function createVersion(id: number, body: VersionCreate): Promise<VersionCreateResponse> {
  return request(`/api/components/${id}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getSymbols(signal?: AbortSignal): Promise<SymbolListItem[]> {
  return request("/api/symbols", { signal });
}

export function getFootprints(signal?: AbortSignal): Promise<FootprintListItem[]> {
  return request("/api/footprints", { signal });
}

// -------------------------------------------------------- template detail

/** URL path segment for template endpoints and routes. */
export type TemplateKind = "symbols" | "footprints";

export interface TemplateUse {
  id: number;
  name: string;
}

export interface TemplateDetail {
  id: number;
  name: string;
  kind: "symbol" | "footprint";
  version_no: number | null;
  /** Cache key for templatePreviewUrl — see that function. */
  version_id: number | null;
  created_at: string | null;
  created_by: string | null;
  comment: string | null;
  parsed: Record<string, unknown>;
  source_text: string | null;
  /** footprints only */
  models?: string[];
  /**
   * Footprints only. Short package name ("0402", "SOT-23-6") that
   * `{Footprint_Name}` in a ki_description resolves to. Lives on the footprint
   * so components don't each carry a copy; unversioned.
   */
  display_name?: string;
  used_by: TemplateUse[];
}

/**
 * Sets a footprint's short package name. Rebuilds the symbol libraries of every
 * category using it, since the name is baked into generated descriptions.
 */
export function saveFootprintDisplayName(
  id: number,
  displayName: string,
): Promise<{
  id: number;
  name: string;
  display_name: string;
  rebuilt_libraries: string[];
  mirror_warnings: string[];
}> {
  return request(`/api/footprints/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
}

/** Retire a footprint, all its versions and its mirror file. The server
 *  refuses (409) if ANY component version — including historical ones —
 *  pins it, so history stays reproducible. */
export function deleteFootprint(id: number): Promise<{ deleted: number; name: string }> {
  return request(`/api/footprints/${id}`, { method: "DELETE" });
}

export function getTemplate(
  kind: TemplateKind,
  id: number,
  signal?: AbortSignal,
): Promise<TemplateDetail> {
  return request(`/api/${kind}/${id}`, { signal });
}

/** Preview of a template's CURRENT drawing.
 *
 * Always pass `versionId` when you have it. Without it the URL is identical
 * for every version of the template, so a browser — or an `<img>` already
 * mounted — has no reason to refetch after a push, and the old land pattern
 * stays on screen until a hard reload (reported 2026-08-24: a pushed
 * D_SOD-323 kept showing its pre-edit pads). With it the URL changes per
 * version and the server may cache the response for a year. */
export function templatePreviewUrl(
  kind: TemplateKind,
  id: number,
  versionId?: number | null,
): string {
  const v = versionId ? `?v=${versionId}` : "";
  return `${API_URL}/api/${kind}/${id}/preview.svg${v}`;
}

export interface GeometryProposalResult {
  ok: true;
  proposal_id: number;
  version_no: number;
  /** footprints */
  pad_count?: number | null;
  previous_pad_count?: number | null;
  /** symbols */
  pin_count?: number | null;
  previous_pin_count?: number | null;
  warnings: string[];
  status: string;
}

/** PUBLISH a new version of a symbol/footprint from pasted editor text. The
 *  name is never sent — the server takes it from the row, so a paste cannot
 *  rename the template.
 *
 *  `minorChange === true` is the recheck WAIVER: it carries the production
 *  sign-offs and verification records of every affected component across the
 *  new drawing, with the user's name on the decision. `null` (the default)
 *  means nobody was asked, and the server compares material fingerprints —
 *  silkscreen-only edits carry, a moved pad does not. */
export function proposeTemplateEdit(
  kind: TemplateKind,
  id: number,
  source_text: string,
  comment: string,
  minorChange: boolean | null = null,
): Promise<GeometryProposalResult> {
  return request(`/api/${kind}/${id}/propose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_text, comment, minor_change: minorChange }),
  });
}

/** Publish the first version of a template that does not exist yet. The name is read out
 *  of the pasted text by the server — a footprint header has to match the row
 *  name anyway, so a separate field could only disagree with it. */
export function proposeNewTemplate(
  kind: TemplateKind,
  source_text: string,
  comment: string,
  name = "",
): Promise<GeometryProposalResult & { footprint?: string; symbol?: string }> {
  return request(`/api/${kind}/propose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_text, comment, name }),
  });
}

// -------------------------------------------------------- simulation models

export interface SimModelListItem {
  id: number;
  name: string;
  kind: "primitive" | "part";
  version_no: number | null;
  ports: string[];
  params: Record<string, string>;
  linked_symbols: number;
}

export interface SimModelDetail extends Omit<SimModelListItem, "linked_symbols"> {
  created_at: string | null;
  created_by: string | null;
  comment: string | null;
  instantiates: string[];
  source_text: string | null;
  linked_symbols: TemplateUse[];
  versions: {
    version_no: number;
    created_at: string;
    created_by: string;
    comment: string | null;
  }[];
}

export interface SimModelProposalResult {
  ok: true;
  model: string;
  version_no: number;
  is_new_model?: boolean;
  kind: string;
  ports: string[];
  params: Record<string, string>;
  status: string;
  mirror_warnings: string[];
}

export function getSimModels(signal?: AbortSignal): Promise<SimModelListItem[]> {
  return request("/api/sim-models", { signal });
}

export function getSimModel(id: number, signal?: AbortSignal): Promise<SimModelDetail> {
  return request(`/api/sim-models/${id}`, { signal });
}

/** PUBLISH a brand-new sim model. The name is read out of the `.subckt` line
 *  by the server — there is no name field, same contract as proposeNewTemplate. */
export function proposeNewSimModel(
  source_text: string,
  comment: string,
  kind: "primitive" | "part" | null = null,
): Promise<SimModelProposalResult> {
  return request("/api/sim-models/propose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_text, comment, kind }),
  });
}

/** PUBLISH a new version of an existing sim model. A paste that renames the
 *  .subckt is rejected — the name is the reference every link resolves. */
export function proposeSimModelEdit(
  id: number,
  source_text: string,
  comment: string,
): Promise<SimModelProposalResult> {
  return request(`/api/sim-models/${id}/propose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_text, comment }),
  });
}

// A symbol's sim link: everything the editor needs in one round trip.
export interface SymbolSimPin {
  number: string;
  name: string;
  type: string;
  hide: boolean;
}

export interface SymbolSimLinkInfo {
  symbol: { id: number; name: string };
  pins: SymbolSimPin[];
  link: {
    model_id: number;
    model_name: string;
    pin_map: Record<string, string>;
    updated_at: string | null;
    updated_by: string;
    /** Human-readable reasons the stored map may no longer mean what its
     *  author intended. Non-empty = the mirror WITHHOLDS the Sim fields. */
    stale: string[];
  } | null;
  models: { id: number; name: string; ports: string[] }[];
  /** The not-connected sentinel a pin can map to ("-"). */
  nc: string;
}

export interface SimLinkSaveResult {
  ok: true;
  symbol: string;
  model?: string;
  pin_map?: Record<string, string>;
  heuristic_warnings?: string[];
  status: string;
  mirror_warnings: string[];
}

export function getSymbolSimLink(id: number, signal?: AbortSignal): Promise<SymbolSimLinkInfo> {
  return request(`/api/symbols/${id}/sim-link`, { signal });
}

/** PUBLISHES the link and rebuilds the mirror — Sim fields appear on every
 *  component of the symbol immediately. */
export function saveSymbolSimLink(
  id: number,
  model_name: string,
  pin_map: Record<string, string>,
): Promise<SimLinkSaveResult> {
  return request(`/api/symbols/${id}/sim-link`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_name, pin_map }),
  });
}

export function removeSymbolSimLink(id: number): Promise<SimLinkSaveResult> {
  return request(`/api/symbols/${id}/sim-link`, { method: "DELETE" });
}

/** Render UNSAVED geometry so the paste box can show it before filing.
 *  Returns an object URL the caller must revoke. Writes nothing. */
export async function renderTemplateSource(
  kind: TemplateKind,
  source_text: string,
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch(`${API_URL}/api/${kind}/preview.svg`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_text }),
    signal,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = (await res.json()) as { detail?: { error?: string } };
      detail = body.detail?.error ?? "";
    } catch {
      // non-JSON error body — fall through to statusText
    }
    throw new ApiError(res.status, detail || `${res.status} ${res.statusText}`);
  }
  return URL.createObjectURL(await res.blob());
}

// -------------------------------------------------------------- datasheets

export interface DatasheetFetchResult {
  id: number;
  /** "new_version" | "unchanged" | "skipped_unstable_non_pdf" | "no_url" */
  result: string;
  version_no?: number;
  component_bumped_to?: number | null;
  has_file: boolean;
  filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  fetched_at: string | null;
  looks_like_pdf?: boolean;
}

export function fetchDatasheet(id: number): Promise<DatasheetFetchResult> {
  return request(`/api/datasheets/${id}/fetch`, { method: "POST" });
}

export function datasheetFileUrl(id: number): string {
  return `${API_URL}/api/datasheets/${id}/file`;
}

export function datasheetVersionFileUrl(id: number, versionNo: number): string {
  return `${API_URL}/api/datasheets/${id}/versions/${versionNo}/file`;
}

// ------------------------------------------------------------ kicad / sync

export interface KicadConfig {
  public_base_url: string;
  httplib_root_url: string;
  mirror_url: string;
  /** PCM repository URL — add in KiCad's Plugin and Content Manager.
   *  Carries `?t=<token>` when the caller is signed in, which is what makes
   *  the installed sync plugin come with that token already baked in. */
  pcm_repo_url: string;
  /** `.kicad_httplib` download, carrying the same token. */
  httplib_url: string;
  /** True when the two URLs above are personal rather than shared. */
  personalised: boolean;
  token_hint: string;
}

// --------------------------------------------------------------------- auth

export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  role: string;
  is_admin: boolean;
}

export interface AuthState {
  /** False on a dev box with AUTH_ENABLED=0 — the SPA then skips the gate. */
  auth_enabled: boolean;
  user: AuthUser | null;
}

export function getAuthState(signal?: AbortSignal): Promise<AuthState> {
  return request("/api/auth/me", { signal });
}

export function login(username: string, password: string): Promise<AuthUser> {
  return request("/api/auth/login", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ username, password }),
  });
}

export function logout(): Promise<{ ok: boolean }> {
  return request("/api/auth/logout", { method: "POST" });
}

export function changeOwnPassword(
  current_password: string,
  new_password: string,
): Promise<{ ok: boolean }> {
  return request("/api/auth/password", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ current_password, new_password }),
  });
}

// -------------------------------------------------------------------- users

export interface ApiTokenRow {
  id: number;
  label: string;
  prefix: string;
  /** Full value — only present on single-user reads, never in the list. */
  token: string;
  created_at: string | null;
  last_used_at: string | null;
}

export interface PlatformUser {
  id: number;
  username: string;
  display_name: string;
  role: string;
  active: boolean;
  created_at: string | null;
  last_login_at: string | null;
  session_count: number;
  tokens: ApiTokenRow[];
  /** Personal PCM repository URL — empty unless the response revealed tokens. */
  repository_url: string;
  /** Personal `.kicad_httplib` download URL. */
  httplib_url: string;
}

export function getUsers(signal?: AbortSignal): Promise<PlatformUser[]> {
  return request("/api/users", { signal });
}

export function getUser(id: number, signal?: AbortSignal): Promise<PlatformUser> {
  return request(`/api/users/${id}`, { signal });
}

export function createUser(body: {
  username: string;
  password: string;
  display_name?: string;
  role?: string;
}): Promise<PlatformUser> {
  return request("/api/users", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function updateUser(
  id: number,
  body: {
    username?: string;
    display_name?: string;
    role?: string;
    active?: boolean;
    password?: string;
  },
): Promise<PlatformUser> {
  return request(`/api/users/${id}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function deleteUser(id: number): Promise<{ ok: boolean }> {
  return request(`/api/users/${id}`, { method: "DELETE" });
}

export function revokeUserSessions(id: number): Promise<{ ok: boolean; revoked: number }> {
  return request(`/api/users/${id}/sessions/revoke`, { method: "POST" });
}

export function addUserToken(id: number, label: string): Promise<PlatformUser> {
  return request(`/api/users/${id}/tokens`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ label }),
  });
}

export function revokeUserToken(userId: number, tokenId: number): Promise<PlatformUser> {
  return request(`/api/users/${userId}/tokens/${tokenId}`, { method: "DELETE" });
}

// ------------------------------------------------------------------ settings

/** One editable runtime setting. `value` is always null for a secret — the API
 *  has no read-back path for those, only `is_set`. */
export interface SettingItem {
  key: string;
  group: string;
  label: string;
  help: string;
  kind: "str" | "int" | "bool";
  secret: boolean;
  /** Only read when the app starts, so a change needs a restart to take hold. */
  restart: boolean;
  choices: string[];
  source: "database" | "environment";
  updated_at: string | null;
  value: string | number | boolean | null;
  is_set: boolean;
}

export interface SettingGroup {
  group: string;
  items: SettingItem[];
}

export function getSettings(signal?: AbortSignal): Promise<{ groups: SettingGroup[] }> {
  return request("/api/settings", { signal });
}

export function setSetting(key: string, value: string): Promise<{ ok: boolean; restart_required: boolean }> {
  return request(`/api/settings/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
}

/** Drop the override; the environment or code default applies again. */
export function revertSetting(key: string): Promise<{ ok: boolean; restart_required: boolean }> {
  return request(`/api/settings/${encodeURIComponent(key)}`, { method: "DELETE" });
}

export interface DatasheetFetchStatus {
  running: boolean;
  mode: string | null;
  done: number;
  total: number;
  new_versions: number;
  unchanged: number;
  errors: number;
  /** Of `unchanged`, how many the supplier settled with a 304 (no download). */
  not_modified: number;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  /** What kicked the current/last run: "startup" | "nightly" | "manual". */
  trigger: string | null;
  /** ISO time of the next scheduled nightly re-check (null = disabled). */
  next_nightly_at: string | null;
  last_nightly_at: string | null;
  datasheets_total: number;
  datasheets_with_local_copy: number;
}

export function getKicadConfig(signal?: AbortSignal): Promise<KicadConfig> {
  return request("/api/kicad/config", { signal });
}

export const httplibFileUrl = `${API_URL}/api/kicad/httplib-file`;
export const syncScriptUrl = `${API_URL}/api/kicad/sync-script`;

export function getDatasheetFetchStatus(signal?: AbortSignal): Promise<DatasheetFetchStatus> {
  return request("/api/datasheets/fetch-status", { signal });
}

export function startDatasheetFetchAll(mode: "missing" | "all"): Promise<{ status: string }> {
  return request("/api/datasheets/fetch-all", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
}

export function symbolSvgUrl(id: number, versionNo: number): string {
  return `${API_URL}/api/components/${id}/versions/${versionNo}/symbol.svg`;
}

export function footprintSvgUrl(id: number, versionNo: number): string {
  return `${API_URL}/api/components/${id}/versions/${versionNo}/footprint.svg`;
}

/** Binary GLB board view: footprint with copper/mask/silk on a board slab
 *  plus the placed 3D model. 404 = no pinned footprint. */
/** The 3D board view of a FOOTPRINT TEMPLATE, addressed by the drawing rather
 *  than by a component version that pins it — what the template page's 3D tab
 *  shows. Version-addressed, so the URL moves when the drawing does and the
 *  server can answer `immutable`. */
export function footprintTemplateGlbUrl(id: number, versionNo: number): string {
  return `${API_URL}/api/footprints/${id}/versions/${versionNo}/preview.glb`;
}

export function footprintGlbUrl(id: number, versionNo: number): string {
  return `${API_URL}/api/components/${id}/versions/${versionNo}/footprint.glb`;
}

export interface ComponentCreate extends VersionCreate {
  name: string;
}

/** Creates a new component with a published v1. 409 on duplicate name. */
export function createComponent(body: ComponentCreate): Promise<VersionCreateResponse> {
  return request("/api/components", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ----------------------------------------------------------------- jaravis

export interface JaravisStatus {
  available: boolean;
  model: string;
  hint: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatTraceItem {
  tool: string;
  input: unknown;
}

export interface ChatProposalRef {
  proposal_id: number;
  component: string;
  kind: string; // "new" | "edit" | "skill" | "symbol" | "footprint"
  version_no?: number;
}

export interface ChatResponse {
  reply: string;
  trace: ChatTraceItem[];
  proposals: ChatProposalRef[];
}

export function getJaravisStatus(signal?: AbortSignal): Promise<JaravisStatus> {
  return request("/api/jaravis/status", { signal });
}

/** SLOW: runs a whole agent loop server-side (10s–2min), non-streaming.
 *  Deliberately no timeout — the browser's own limit applies. Kept for
 *  scripts; the chat UI uses jaravisChatStream. */
export function jaravisChat(messages: ChatMessage[]): Promise<ChatResponse> {
  return request("/api/jaravis/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
}

/** One NDJSON progress event from a Jaravis chat stream. */
export interface ChatStreamEvent {
  type: "note" | "tool" | "done" | "error" | "session";
  /** note: interim narration text from the agent */
  text?: string;
  /** tool: tool name + input the moment the call is issued */
  tool?: string;
  input?: unknown;
  /** done: the final result (same shape as ChatResponse) */
  reply?: string;
  trace?: ChatTraceItem[];
  proposals?: ChatProposalRef[];
  /** error: server-side failure after the stream started */
  error?: string;
  /** session: the session id + its (possibly auto-generated) title */
  session_id?: number;
  title?: string;
}

/** POST a JSON body and return the streaming Response, mapping connection and
 *  non-2xx failures to ApiError (aborts re-thrown untouched). */
async function openStream(path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw new ApiError(0, `Cannot reach API at ${apiOrigin()} (${errorMessage(err)})`);
  }
  if (!res.ok || !res.body) {
    let detail = "";
    try {
      const b = (await res.json()) as { detail?: unknown };
      if (typeof b.detail === "string") detail = b.detail;
    } catch {
      // non-JSON error body — fall through to statusText
    }
    throw new ApiError(res.status, detail || `${res.status} ${res.statusText}`);
  }
  return res;
}

/** Read an NDJSON stream to completion, firing onEvent per parsed line. */
async function pumpNdjson(res: Response, onEvent: (ev: ChatStreamEvent) => void): Promise<void> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) onEvent(JSON.parse(line) as ChatStreamEvent);
    }
  }
}

/** Stateless streaming chat (kept for scripts). Aborting the signal (Stop
 *  button) closes the connection, which ends the run server-side at the next
 *  event boundary. The chat UI uses jaravisSessionChatStream instead. */
export async function jaravisChatStream(
  messages: ChatMessage[],
  onEvent: (ev: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await openStream("/api/jaravis/chat/stream", { messages }, signal);
  await pumpNdjson(res, onEvent);
}

// ------------------------------------------------------- jaravis sessions

export interface JaravisSessionSummary {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface StoredChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  trace: ChatTraceItem[];
  proposals: ChatProposalRef[];
  created_at: string;
}

export interface JaravisSessionDetail extends JaravisSessionSummary {
  messages: StoredChatMessage[];
}

export function listJaravisSessions(signal?: AbortSignal): Promise<JaravisSessionSummary[]> {
  return request("/api/jaravis/sessions", { signal });
}

export function createJaravisSession(): Promise<JaravisSessionSummary> {
  return request("/api/jaravis/sessions", { method: "POST" });
}

export function getJaravisSession(id: number, signal?: AbortSignal): Promise<JaravisSessionDetail> {
  return request(`/api/jaravis/sessions/${id}`, { signal });
}

export function renameJaravisSession(id: number, title: string): Promise<JaravisSessionSummary> {
  return request(`/api/jaravis/sessions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export function deleteJaravisSession(id: number): Promise<{ deleted: number }> {
  return request(`/api/jaravis/sessions/${id}`, { method: "DELETE" });
}

/** Persisted streaming chat: starts a turn in a session. The turn runs
 *  server-side in a background thread that survives this connection closing, so
 *  the answer is persisted even if the tab is closed. Same event stream as
 *  jaravisChatStream, preceded by a "session" event carrying the (possibly
 *  auto-generated) title. Throws ApiError 409 if a turn is already running for
 *  the session (attach with attachJaravisRun instead). */
export async function jaravisSessionChatStream(
  sessionId: number,
  content: string,
  onEvent: (ev: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await openStream(`/api/jaravis/sessions/${sessionId}/chat/stream`, { content }, signal);
  await pumpNdjson(res, onEvent);
}

/** Re-attach to a session's in-flight run and replay its events (used after a
 *  page reload). Resolves false if no turn is currently running (HTTP 204) —
 *  the stored messages are then authoritative; resolves true once the attached
 *  stream has been fully drained. */
export async function attachJaravisRun(
  sessionId: number,
  onEvent: (ev: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<boolean> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/jaravis/sessions/${sessionId}/run/stream`, { signal });
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw new ApiError(0, `Cannot reach API at ${API_URL} (${errorMessage(err)})`);
  }
  if (res.status === 204) return false;
  if (!res.ok || !res.body) return false; // treat as "no run" rather than a hard error
  await pumpNdjson(res, onEvent);
  return true;
}

/** Stop a session's in-flight run server-side (the Stop button). */
export function cancelJaravisRun(sessionId: number): Promise<{ cancelled: boolean }> {
  return request(`/api/jaravis/sessions/${sessionId}/run/cancel`, { method: "POST" });
}

// ---------------------------------------------------------------- comments

/** Which entity family a comment hangs off — matches the URL path segment. */
export type CommentTargetKind = "components" | "symbols" | "footprints";

/** Free-form note on any entity (not versioned). */
export interface Comment {
  id: number;
  target_type: string; // "component" | "symbol" | "footprint"
  target_id: number;
  author: string;
  body: string;
  created_at: string;
}

export function getComments(
  kind: CommentTargetKind,
  id: number,
  signal?: AbortSignal,
): Promise<Comment[]> {
  return request(`/api/${kind}/${id}/comments`, { signal });
}

export function addComment(kind: CommentTargetKind, id: number, body: string): Promise<Comment> {
  return request(`/api/${kind}/${id}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
}

export function deleteComment(commentId: number): Promise<{ deleted: number }> {
  return request(`/api/comments/${commentId}`, { method: "DELETE" });
}

// ------------------------------------------------------------------ skills

export interface SkillListItem {
  id: number;
  name: string;
  /** When-to-use one-liner. Unversioned — see SkillDetail.description. */
  description: string;
  current_version_no: number | null;
  updated_at: string | null;
  size: number;
}

export interface SkillVersionInfo {
  version_no: number;
  created_at: string;
  created_by: string | null;
  status: string; // "published" | "draft" | "rejected"
  comment: string | null;
  size: number;
}

export interface SkillDetail {
  id: number;
  name: string;
  /**
   * When-to-use one-liner: what an agent reads to decide whether the document
   * is relevant. NOT versioned (it labels the skill, not a revision), so it is
   * saved through `saveSkillDescription`, independently of the editor text.
   */
  description: string;
  current_version_no: number | null;
  /** Content of the CURRENT version. */
  content: string;
  versions: SkillVersionInfo[];
}

export interface SkillVersionDetail {
  skill_id: number;
  name: string;
  version_no: number;
  created_at: string;
  created_by: string | null;
  status: string; // "published" | "draft" | "rejected"
  comment: string | null;
  content: string;
}

export interface SkillSaveResponse {
  id: number;
  name: string;
  current_version_no: number;
}

export function getSkills(signal?: AbortSignal): Promise<SkillListItem[]> {
  return request("/api/skills", { signal });
}

export function getSkill(id: number, signal?: AbortSignal): Promise<SkillDetail> {
  return request(`/api/skills/${id}`, { signal });
}

export function getSkillVersion(
  id: number,
  versionNo: number,
  signal?: AbortSignal,
): Promise<SkillVersionDetail> {
  return request(`/api/skills/${id}/versions/${versionNo}`, { signal });
}

/** Saves an edit (or restores an old version's content) as the new current version. */
export function saveSkill(id: number, content: string): Promise<SkillSaveResponse> {
  return request(`/api/skills/${id}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

/**
 * Saves the when-to-use description. Unversioned, so this never mints a new
 * content version — the Skills page calls it alongside (or instead of)
 * `saveSkill` depending on what the user actually changed.
 */
export function saveSkillDescription(
  id: number,
  description: string,
): Promise<{ id: number; name: string; description: string }> {
  return request(`/api/skills/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description }),
  });
}

/** Permanently deletes a skill and all its versions. */
export function deleteSkill(
  id: number,
): Promise<{ deleted: number; name: string; versions_removed: number }> {
  return request(`/api/skills/${id}`, { method: "DELETE" });
}

/** Creates a new skill (409 on duplicate name). */
export function createSkill(
  name: string,
  content: string,
  description = "",
): Promise<SkillSaveResponse> {
  return request("/api/skills", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, content, description }),
  });
}

// ------------------------------------------------------- production sign-off

/** Has a human checked this part before boards were built?
 *
 * NOT the same as a version being published — approval only means the edit was
 * let into the library. See `api/app/services/signoff.py`.
 *
 * - `signed`   — the current version was checked.
 * - `stale`    — an older version was checked and something material changed.
 * - `revoked`  — a sign-off on the current version was taken back.
 * - `unsigned` — never checked. */
export type SignoffState = "signed" | "stale" | "revoked" | "unsigned";

export interface SignoffRow {
  id: number;
  component_version_id: number;
  /** `checked` = a human looked. `auto-carried` = the drawing's fingerprint was
   *  identical, so nothing reaching the board changed. `carried` = a human
   *  waived the re-check on a drawing that DID change. */
  kind: "checked" | "carried" | "auto-carried";
  carried_from_id: number | null;
  signed_by: string;
  signed_at: string | null;
  note: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
  revoke_reason: string | null;
}

/** The drawings a component version pins, named for a human. `id` is the
 *  parent symbol/footprint row, so the label can be a link. */
export interface GeometryLabel {
  symbol: { id: number; name: string; version_no: number } | null;
  footprint: { id: number; name: string; version_no: number } | null;
}

export interface SignoffDetail {
  component_id: number;
  component_name: string;
  state: SignoffState;
  signoff: SignoffRow | null;
  current_version_no: number | null;
  current: GeometryLabel;
  signed_version_no: number | null;
  signed: GeometryLabel;
  /** Why the sign-off did not follow the component forward — one sentence per
   *  leg that changed. Empty unless the state is `stale`. */
  blockers: string[];
  last_revoked?: SignoffRow;
  history: SignoffRow[];
}

export function getSignoff(comp_id: number, signal?: AbortSignal): Promise<SignoffDetail> {
  return request(`/api/components/${comp_id}/signoff`, { signal });
}

export function addSignoff(comp_id: number, note?: string): Promise<SignoffDetail> {
  return request(`/api/components/${comp_id}/signoff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note: note ?? null }),
  });
}

export function revokeSignoff(comp_id: number, reason: string): Promise<SignoffDetail> {
  return request(`/api/components/${comp_id}/signoff/revoke`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export interface BulkSignoffResult {
  signed: string[];
  skipped: { component_id: number; component?: string; reason: string }[];
  total: number;
}

export function bulkSignoff(
  component_ids: number[],
  note?: string,
): Promise<BulkSignoffResult> {
  return request("/api/signoffs/bulk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ component_ids, note: note ?? null }),
  });
}

export function startImport(): Promise<{ status: string }> {
  return request("/api/import", { method: "POST" });
}

export function getImportStatus(signal?: AbortSignal): Promise<ImportStatus> {
  return request("/api/import/status", { signal });
}

// ------------------------------------------------------------- file viewer

export interface ViewerCapabilities {
  dwg_convert: boolean;
}

export function getViewerCapabilities(signal?: AbortSignal): Promise<ViewerCapabilities> {
  return request("/api/view/capabilities", { signal });
}

/** Server-side DWG→DXF conversion (LibreDWG). `srcPath` is a same-origin
 *  path like /api/datasheets/3/file or /files/3DModels/x.dwg. */
export function dwgToDxfUrl(srcPath: string): string {
  return `${API_URL}/api/view/dwg2dxf?src=${encodeURIComponent(srcPath)}`;
}

export interface Model3DFile {
  name: string;
  /** Same-origin path into the file mirror (/files/3DModels/...). */
  url: string;
  size_bytes: number;
}

export function getModels3d(
  compId: number,
  versionNo: number,
  signal?: AbortSignal,
): Promise<Model3DFile[]> {
  return request(`/api/components/${compId}/versions/${versionNo}/models3d`, { signal });
}

/** Upload a local file as this row's stored copy (versioned; non-PDF too). */
export function uploadDatasheetFile(id: number, file: File): Promise<DatasheetFetchResult> {
  const fd = new FormData();
  fd.append("file", file);
  return request(`/api/datasheets/${id}/upload`, { method: "POST", body: fd });
}

export interface AddComponentFileResult {
  id: number;
  result: string;
  version_no: number;
  component_bumped_to: number | null;
  datasheets: DatasheetRow[];
}

/** Attach an uploaded file to a component as a new datasheet-style row
 *  (bumps the component version so the file is pinned from there on). */
export function addComponentFile(
  compId: number,
  label: string,
  file: File,
): Promise<AddComponentFileResult> {
  const fd = new FormData();
  fd.append("label", label);
  fd.append("file", file);
  return request(`/api/components/${compId}/files`, { method: "POST", body: fd });
}

// ---------------------------------------------------------------- projects

export interface SnapshotBoard {
  name: string;
  dir: string;
  pro: string;
  sch: string | null;
  pcb: string | null;
  variants: { name: string; description: string }[];
  layers: { name: string; type: string; user_name: string }[];
}

export interface SnapshotInfo {
  id: number;
  project_id: number;
  sha: string;
  ref_name: string;
  is_tag: boolean;
  commit_message: string;
  committed_at: string | null;
  status: string; // pending | ingesting | ready | error
  stage: string | null;
  error: string | null;
  boards: SnapshotBoard[];
  report: {
    boards?: number;
    bom_lines?: number;
    matched_lines?: number;
    warnings?: string[];
  } | null;
  created_at: string;
}

export interface ProjectInfo {
  id: number;
  name: string;
  git_url: string;
  has_token: boolean;
  default_branch: string;
  display_currency: string | null;
  effective_currency: string;
  description: string;
  created_at: string;
  has_mirror: boolean;
  latest_snapshot: SnapshotInfo | null;
  run_count: number;
}

export interface ProjectCreate {
  name: string;
  git_url: string;
  git_token?: string | null;
  default_branch?: string;
  display_currency?: string | null;
  description?: string;
}

export interface ProjectPatchBody {
  name?: string;
  git_url?: string;
  /** "" clears the stored token; omit to leave unchanged. */
  git_token?: string;
  default_branch?: string;
  display_currency?: string;
  description?: string;
}

export function getProjects(signal?: AbortSignal): Promise<ProjectInfo[]> {
  return request("/api/projects", { signal });
}

export function createProject(body: ProjectCreate): Promise<ProjectInfo> {
  return request("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getProject(id: number, signal?: AbortSignal): Promise<ProjectInfo> {
  return request(`/api/projects/${id}`, { signal });
}

export function updateProject(id: number, body: ProjectPatchBody): Promise<ProjectInfo> {
  return request(`/api/projects/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteProject(id: number): Promise<{ deleted: number }> {
  return request(`/api/projects/${id}`, { method: "DELETE" });
}

export interface FetchResult {
  fetched: boolean;
  queued: { sha: string; ref: string; tag: boolean }[];
}

export function fetchProject(id: number): Promise<FetchResult> {
  return request(`/api/projects/${id}/fetch`, { method: "POST" });
}

export interface HistoryCommit {
  sha: string;
  author: string;
  date: string;
  message: string;
  refs: string[];
  snapshot: { id: number; status: string } | null;
}

export interface ProjectHistory {
  branch: string;
  branches: { name: string; sha: string }[];
  tags: { name: string; sha: string; date: string }[];
  commits: HistoryCommit[];
}

export function getProjectHistory(
  id: number,
  ref?: string,
  signal?: AbortSignal,
): Promise<ProjectHistory> {
  const qs = ref ? `?ref=${encodeURIComponent(ref)}` : "";
  return request(`/api/projects/${id}/history${qs}`, { signal });
}

export function getSnapshots(projectId: number, signal?: AbortSignal): Promise<SnapshotInfo[]> {
  return request(`/api/projects/${projectId}/snapshots`, { signal });
}

export function ingestSnapshot(projectId: number, ref: string): Promise<{ status: string; sha: string }> {
  return request(`/api/projects/${projectId}/snapshots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ref }),
  });
}

export function getSnapshot(id: number, signal?: AbortSignal): Promise<SnapshotInfo> {
  return request(`/api/snapshots/${id}`, { signal });
}

export function deleteSnapshot(id: number): Promise<{ deleted: number }> {
  return request(`/api/snapshots/${id}`, { method: "DELETE" });
}

// ----------------------------------------------------------- BOM & pricing

export interface BomLine {
  key: string;
  refs: string;
  qty_per: number;
  qty_total: number;
  value: string;
  footprint: string;
  lcsc: string;
  mpn: string;
  manufacturer: string;
  symbol_name: string;
  component_id: number | null;
  component_name: string | null;
  dnp: boolean;
  exclude_from_bom: boolean;
  exclude_from_board: boolean;
  /** Matched component is flagged virtual (test point, logo, fiducial). */
  not_purchasable: boolean;
  excluded: boolean;
  unit_price: number | null;
  unit_price_src: number | null;
  price_currency: string | null;
  price_qty_from: number | null;
  price_source: string | null;
  price_updated: string | null;
  line_total: number | null;
  rate_known: boolean;
  moq: number | null;
  /** LCSC retail stock (lcsc.com webshop). */
  stock: number | null;
  /** JLCPCB assembly-parts stock (jlcpcb.com/parts) — a separate pool. */
  jlc_stock: number | null;
  stock_ok?: boolean;
  order_qty: number;
  order_excess: number;
  order_total: number | null;
}

export interface ExtraBomLine extends Partial<BomLine> {
  key: string;
  id: number;
  label: string;
  qty_per: number;
  qty_total: number;
  notes: string;
}

export interface CostLine {
  key: string;
  id: number;
  label: string;
  basis: string; // per_device | per_run
  price_src: number;
  currency: string;
  price: number | null;
  per_device: number | null;
  company: string;
  mpn: string;
  notes: string;
  rate_known: boolean;
}

export interface BomTotals {
  bom_per_device: number | null;
  extra_per_device: number | null;
  cost_per_device: number | null;
  per_run_fixed: number | null;
  device_total: number | null;
  run_total: number | null;
  order_parts_total: number | null;
  unpriced_lines: number;
  unknown_rates: string[];
}

export interface PricedBom {
  snapshot_id: number;
  sha: string;
  board: string;
  variant: string;
  volume: number;
  currency: string;
  lines: BomLine[];
  extra: ExtraBomLine[];
  costs: CostLine[];
  totals: BomTotals;
}

export function getBom(
  snapshotId: number,
  board: string,
  variant: string,
  volume: number,
  currency?: string,
  signal?: AbortSignal,
): Promise<PricedBom> {
  const qs = new URLSearchParams({ board, variant, volume: String(volume) });
  if (currency) qs.set("currency", currency);
  return request(`/api/snapshots/${snapshotId}/bom?${qs}`, { signal });
}

export interface CurvePoint {
  volume: number;
  device_total: number | null;
  bom_per_device: number | null;
  extra_per_device: number | null;
  cost_per_device: number | null;
  run_total: number | null;
  unpriced_lines: number;
}

export function getBomCurve(
  snapshotId: number,
  board: string,
  variant: string,
  volumes: number[],
  currency?: string,
  signal?: AbortSignal,
): Promise<CurvePoint[]> {
  const qs = new URLSearchParams({ board, variant, volumes: volumes.join(",") });
  if (currency) qs.set("currency", currency);
  return request(`/api/snapshots/${snapshotId}/bom/curve?${qs}`, { signal });
}

export interface BomDiffLine {
  refs: string;
  qty: number;
  value: string;
  footprint: string;
  lcsc: string;
  symbol_name: string;
  component_id: number | null;
  dnp: boolean;
}

export interface BomDiff {
  from: { snapshot_id: number; sha: string; ref: string };
  to: { snapshot_id: number; sha: string; ref: string };
  board: string;
  variant: string;
  added: BomDiffLine[];
  removed: BomDiffLine[];
  changed: { from: BomDiffLine; to: BomDiffLine }[];
}

export function getBomDiff(
  projectId: number,
  fromSnapshot: number,
  toSnapshot: number,
  board: string,
  variant: string,
  signal?: AbortSignal,
): Promise<BomDiff> {
  const qs = new URLSearchParams({
    from_snapshot: String(fromSnapshot),
    to_snapshot: String(toSnapshot),
    board,
    variant,
  });
  return request(`/api/projects/${projectId}/bom-diff?${qs}`, { signal });
}

export interface StockCheckLine {
  refs: string;
  value: string;
  lcsc: string;
  component_id: number | null;
  needed: number;
  /** Quantity held in the user's private JLC parts library. */
  private_stock: number;
  private_ok: boolean;
  /** Still to buy after consuming private stock. */
  to_buy: number;
  order_qty: number;
  /** LCSC retail stock. */
  stock: number | null;
  /** JLCPCB assembly-parts stock. */
  jlc_stock: number | null;
  moq: number | null;
  ok: boolean | null;
}

export interface StockCheck {
  volume: number;
  lines: StockCheckLine[];
  shortages: number;
  covered_by_private: number;
  private_inventory: number;
  unknown: number;
}

export function runStockCheck(
  snapshotId: number,
  board: string,
  variant: string,
  volume: number,
): Promise<StockCheck> {
  const qs = new URLSearchParams({ board, variant, volume: String(volume) });
  return request(`/api/snapshots/${snapshotId}/stock-check?${qs}`, { method: "POST" });
}

// ------------------------------------------------------------- render URLs

export function boardLayerSvgUrl(snapshotId: number, board: string, layer: string): string {
  return `${API_URL}/api/snapshots/${snapshotId}/boards/${encodeURIComponent(board)}/layer.svg?layer=${encodeURIComponent(layer)}`;
}

export function boardGlbUrl(snapshotId: number, board: string): string {
  return `${API_URL}/api/snapshots/${snapshotId}/boards/${encodeURIComponent(board)}/board.glb`;
}

export function boardStepUrl(snapshotId: number, board: string): string {
  return `${API_URL}/api/snapshots/${snapshotId}/boards/${encodeURIComponent(board)}/board.step`;
}

export function fabZipUrl(snapshotId: number, board: string): string {
  return `${API_URL}/api/snapshots/${snapshotId}/boards/${encodeURIComponent(board)}/fab.zip`;
}

export interface SchematicPages {
  variant: string;
  pages: string[];
}

export function getSchematicPages(
  snapshotId: number,
  board: string,
  variant: string,
  signal?: AbortSignal,
): Promise<SchematicPages> {
  const qs = variant ? `?variant=${encodeURIComponent(variant)}` : "";
  return request(`/api/snapshots/${snapshotId}/boards/${encodeURIComponent(board)}/schematic${qs}`, {
    signal,
  });
}

export function schematicPageUrl(
  snapshotId: number,
  board: string,
  page: string,
  variant: string,
): string {
  const qs = new URLSearchParams({ page });
  if (variant) qs.set("variant", variant);
  return `${API_URL}/api/snapshots/${snapshotId}/boards/${encodeURIComponent(board)}/schematic/page?${qs}`;
}

export interface CheckViolation {
  type?: string;
  severity?: string;
  description?: string;
}

export interface BoardChecks {
  erc: Record<string, unknown> | null;
  drc: Record<string, unknown> | null;
}

export function getBoardChecks(
  snapshotId: number,
  board: string,
  signal?: AbortSignal,
): Promise<BoardChecks> {
  return request(`/api/snapshots/${snapshotId}/boards/${encodeURIComponent(board)}/checks`, {
    signal,
  });
}

// ------------------------------------------------- extra items / cost items

export interface ExtraItem {
  id: number;
  project_id: number;
  position: number;
  label: string;
  qty: number;
  component_id: number | null;
  manufacturer: string;
  mpn: string;
  unit_price: number | null;
  currency: string;
  notes: string;
}

export interface ExtraItemIn {
  label: string;
  qty: number;
  component_id: number | null;
  manufacturer: string;
  mpn: string;
  unit_price: number | null;
  currency: string;
  notes: string;
  position: number;
}

/** Which commit-anchored revision of the manual cost list is in effect.
 *  anchor_sha "" = "since the beginning" (pre-versioning data). */
export interface CostRevisionInfo {
  id: number;
  anchor_sha: string;
  anchor_ref: string;
  anchor_committed_at: string | null;
}

function snapQuery(snapshotId?: number | null): string {
  return snapshotId != null ? `?snapshot_id=${snapshotId}` : "";
}

export function getExtraItems(
  projectId: number,
  snapshotId?: number | null,
  signal?: AbortSignal,
): Promise<{ items: ExtraItem[]; revision: CostRevisionInfo | null }> {
  return request(`/api/projects/${projectId}/extra-items${snapQuery(snapshotId)}`, { signal });
}

export function addExtraItem(
  projectId: number,
  body: ExtraItemIn,
  snapshotId?: number | null,
): Promise<ExtraItem> {
  return request(`/api/projects/${projectId}/extra-items${snapQuery(snapshotId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateExtraItem(
  id: number,
  body: ExtraItemIn,
  snapshotId?: number | null,
): Promise<ExtraItem> {
  return request(`/api/extra-items/${id}${snapQuery(snapshotId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteExtraItem(
  id: number,
  snapshotId?: number | null,
): Promise<{ deleted: number }> {
  return request(`/api/extra-items/${id}${snapQuery(snapshotId)}`, { method: "DELETE" });
}

/** Quantity break for a cost item — the step with the largest qty_from <=
 *  run volume overrides the base price (which is the qty-1 tier). */
export interface CostStep {
  qty_from: number;
  price: number;
}

export interface CostItem {
  id: number;
  project_id: number;
  position: number;
  label: string;
  basis: string;
  price: number;
  steps: CostStep[];
  currency: string;
  company: string;
  mpn: string;
  /** production-step identity ("pcba:setup"); "" = free-form item */
  step_key: string;
  notes: string;
}

export interface CostItemIn {
  label: string;
  basis: string;
  price: number;
  steps: CostStep[];
  currency: string;
  company: string;
  mpn: string;
  step_key?: string;
  notes: string;
  position: number;
}

export function getCostItems(
  projectId: number,
  snapshotId?: number | null,
  signal?: AbortSignal,
): Promise<{ items: CostItem[]; revision: CostRevisionInfo | null }> {
  return request(`/api/projects/${projectId}/cost-items${snapQuery(snapshotId)}`, { signal });
}

export function addCostItem(
  projectId: number,
  body: CostItemIn,
  snapshotId?: number | null,
): Promise<CostItem> {
  return request(`/api/projects/${projectId}/cost-items${snapQuery(snapshotId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateCostItem(
  id: number,
  body: CostItemIn,
  snapshotId?: number | null,
): Promise<CostItem> {
  return request(`/api/cost-items/${id}${snapQuery(snapshotId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteCostItem(id: number, snapshotId?: number | null): Promise<{ deleted: number }> {
  return request(`/api/cost-items/${id}${snapQuery(snapshotId)}`, { method: "DELETE" });
}

// ------------------------------------------------------------ project notes

export interface ProjectNoteRow {
  id: number;
  author: string;
  body: string;
  /** Commit context the note was written against ("" = none). */
  sha: string;
  ref_name: string;
  created_at: string;
}

export function getProjectNotes(projectId: number, signal?: AbortSignal): Promise<ProjectNoteRow[]> {
  return request(`/api/projects/${projectId}/notes`, { signal });
}

export function addProjectNote(
  projectId: number,
  body: string,
  snapshotId?: number | null,
): Promise<ProjectNoteRow> {
  return request(`/api/projects/${projectId}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body, snapshot_id: snapshotId ?? null }),
  });
}

export function deleteProjectNote(noteId: number): Promise<{ deleted: number }> {
  return request(`/api/project-notes/${noteId}`, { method: "DELETE" });
}

// --------------------------------------------------------- production runs

export interface RunEffectiveLine {
  key: string;
  refs?: string;
  label?: string;
  value?: string;
  qty_total: number;
  unit_price: number | null;
  /** unit_price converted to USD at the run date — the Materials table compares
   *  these planned lines against pool draws, which are USD-denominated.
   *  null when the FX rate is unknown (never a silent 1:1). */
  unit_usd?: number | null;
  line_total: number | null;
  excluded?: boolean;
  dnp?: boolean;
  overridden: boolean;
  dropped?: boolean;
  override_note?: string;
  lcsc?: string;
  component_name?: string | null;
}

export interface RunEffective {
  /** The instant prices were resolved at (run date; recomputed on every read). */
  priced_at: string | null;
  currency: string | null;
  cost_revision?: CostRevisionInfo | null;
  qty: number;
  lines: RunEffectiveLine[];
  costs: (CostLine & { overridden: boolean; dropped?: boolean; run_cost?: number | null })[];
  added: { key: string; label: string; qty_total: number; unit_price: number; line_total: number | null; note: string }[];
  totals: {
    parts_total: number | null;
    costs_total: number | null;
    run_total: number | null;
    per_device: number | null;
  };
}

export interface RunAttachmentRow {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface RunDeviceRow {
  id: number;
  serial: string;
  note: string;
  created_at: string;
}

export interface RunInfo {
  id: number;
  project_id: number;
  label: string;
  snapshot_id: number | null;
  board: string;
  variant: string;
  qty: number;
  status: string;
  run_date: string;
  notes: string;
  qty_good?: number | null;
  /** the sale side: price PER DEVICE, units billed, and the customer order */
  qty_sold?: number | null;
  sale_unit_price?: number | null;
  /** empty inherits the project's display currency */
  sale_currency?: string;
  customer?: string;
  order_ref?: string;
  order_date?: string;
  created_at: string;
  attachment_count: number;
  device_count: number;
  effective?: RunEffective | null;
  overrides?: Record<string, unknown>;
  attachments?: RunAttachmentRow[];
  devices?: RunDeviceRow[];
}

export interface RunCreate {
  label: string;
  snapshot_id: number | null;
  board: string;
  variant: string;
  qty: number;
  status?: string;
  run_date?: string;
  notes?: string;
  /** Explicit confirmation of the design-review warning. Without it a
   *  snapshot with unsigned/unreviewed/deprecated components (or one whose
   *  review was never completed) answers 409 with a ReviewWarningDetail. */
  ack_review?: boolean;
}

/** The 409 payload of the run-creation review gate (`ApiError.detail`). */
export interface ReviewWarningDetail {
  review_warning: true;
  unsigned: string[];
  unreviewed: string[];
  deprecated: string[];
  changed_since_review: string[];
  review_completed: boolean;
}

export function reviewWarningOf(err: unknown): ReviewWarningDetail | null {
  if (err instanceof ApiError && err.status === 409 && err.detail &&
      typeof err.detail === "object" && (err.detail as { review_warning?: unknown }).review_warning === true) {
    return err.detail as ReviewWarningDetail;
  }
  return null;
}

export interface RunPatchBody {
  label?: string;
  qty?: number;
  status?: string;
  run_date?: string;
  notes?: string;
  overrides?: Record<string, unknown>;
  /** re-point the run at another snapshot of the same project; the server
   *  refuses (409) while `b<id>` overrides are keyed to the old snapshot's
   *  BOM lines. A snapshot cannot be cleared — omit to leave it alone. */
  snapshot_id?: number;
  /** sale side. Only fields actually present are applied, so patching a label
   *  can never blank a price. `null` clears one deliberately. */
  sale_unit_price?: number | null;
  sale_currency?: string;
  qty_sold?: number | null;
  qty_good?: number | null;
  customer?: string;
  order_ref?: string;
  order_date?: string;
}

export function getRuns(projectId: number, signal?: AbortSignal): Promise<RunInfo[]> {
  return request(`/api/projects/${projectId}/runs`, { signal });
}

export function createRun(projectId: number, body: RunCreate): Promise<RunInfo> {
  return request(`/api/projects/${projectId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getRun(runId: number, signal?: AbortSignal): Promise<RunInfo> {
  return request(`/api/runs/${runId}`, { signal });
}

export function updateRun(runId: number, body: RunPatchBody): Promise<RunInfo> {
  return request(`/api/runs/${runId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteRun(runId: number): Promise<{ deleted: number }> {
  return request(`/api/runs/${runId}`, { method: "DELETE" });
}

export async function uploadRunAttachment(
  runId: number,
  file: File,
): Promise<{ id: number; filename: string; size_bytes: number }> {
  const form = new FormData();
  form.append("file", file);
  return request(`/api/runs/${runId}/attachments`, { method: "POST", body: form });
}

export function runAttachmentUrl(attachmentId: number): string {
  return `${API_URL}/api/run-attachments/${attachmentId}`;
}

export function deleteRunAttachment(attachmentId: number): Promise<{ deleted: number }> {
  return request(`/api/run-attachments/${attachmentId}`, { method: "DELETE" });
}

export function addRunDevices(
  runId: number,
  serials: string,
): Promise<{ added: number; skipped_duplicates: number; total: number }> {
  return request(`/api/runs/${runId}/devices`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ serials }),
  });
}

export function deleteRunDevice(deviceId: number): Promise<{ deleted: number }> {
  return request(`/api/run-devices/${deviceId}`, { method: "DELETE" });
}

// ------------------------------------------- post-factum production costs
// Supplier documents entered AFTER a run. `kind:"part"` lines with no run feed
// the component cost pool; runs draw from it (consumption) at a moving average.
// Attrition is recorded as a stock adjustment, optionally charged to a run.

export type CostLineKind =
  | "part" | "fab" | "assembly" | "tooling" | "freight"
  | "duty" | "tax" | "rework" | "packaging" | "service" | "other";

export interface RunCostLineRow {
  id: number;
  document_id: number;
  run_id: number | null;
  /** a share destined for a project but not yet for a specific run */
  project_id?: number | null;
  /** set on a share of a split position; children live on the parent's document */
  parent_line_id?: number | null;
  /** true when the line has live children — it is a header worth zero, they carry the money */
  is_header?: boolean;
  children_total?: number | null;
  /** header only: amount not yet allocated to a child */
  residual?: number | null;
  position: number;
  kind: CostLineKind;
  basis: "per_device" | "per_run";
  label: string;
  qty: number;
  /** qty x run units for a per_device line — what the money is charged on */
  qty_effective?: number;
  unit_price: number;
  line_total: number | null;
  currency: string;
  allocate: string;
  component_id: number | null;
  mpn: string;
  lcsc: string;
  description: string;
  plan_key: string;
  plan_kind: string;
  plan_ref?: string;
  notes: string;
  ocr_confidence: number | null;
  voided: boolean;
}

/** Where a document's money went, leaves only. `unassigned` + `residual` is the
 *  amount no run and no project is paying for. */
export interface DocumentAssignment {
  run: number | null;
  project: number | null;
  pool: number | null;
  /** recorded so the document reconciles, charged to nobody on purpose */
  excluded: number | null;
  unassigned: number | null;
  residual: number | null;
  by_run: Record<string, number | null>;
  by_project: Record<string, number | null>;
  fully_assigned: boolean;
}

export interface RunCostDocumentRow {
  id: number;
  project_id: number | null;
  run_id: number | null;
  doc_type: string;
  supplier: string;
  doc_number: string;
  external_id: string;
  doc_date: string;
  paid_at: string;
  currency: string;
  fx_rate_usd: number | null;
  display_amount: number | null;
  total_amount: number | null;
  tax_amount: number | null;
  notes: string;
  attachment_id: number | null;
  /** how many originals are filed with this document */
  attachment_count?: number;
  created_at: string | null;
  line_count: number;
  lines_total: number | null;
  /** false when the entered total does not match the sum of its lines */
  reconciled: boolean;
  assignment: DocumentAssignment;
  lines?: RunCostLineRow[];
  /** register only */
  total_usd?: number | null;
  lines_total_usd?: number | null;
  assignment_usd?: Record<string, number | null>;
  project_name?: string;
  run_label?: string;
}

// ----------------------------------------------------------- invoice register

export interface InvoiceRegister {
  documents: RunCostDocumentRow[];
  projects: Record<string, string>;
  runs: Record<string, {
    label: string; project_id: number; run_date: string; qty: number;
    qty_sold: number | null; sale_unit_price: number | null; sale_currency: string;
    customer: string; order_ref: string; order_date: string;
  }>;
  summary: {
    document_count: number;
    total_usd: number | null;
    to_runs_usd: number | null;
    to_projects_usd: number | null;
    to_pool_usd: number | null;
    excluded_usd: number | null;
    unassigned_usd: number | null;
    residual_usd: number | null;
    /** total minus every bucket — non-zero means a bug, not bad data */
    gap_usd: number | null;
    unknown_rates: string[];
    by_supplier_usd: Record<string, number | null>;
  };
  by_project_usd: Record<string, number | null>;
  by_run_usd: Record<string, {
    direct_usd: number | null;
    components_usd: number | null;
    total_usd: number | null;
    /** price per device x units billed, converted at the ORDER date */
    revenue_usd: number | null;
    margin_usd: number | null;
    margin_pct: number | null;
  }>;
  pool: {
    purchased_usd: number | null;
    adjustments_usd: number | null;
    drawn_usd: number | null;
    on_hand_usd: number | null;
    balanced: boolean;
    part_count: number;
  };
  issues: {
    unreconciled: {
      id: number; supplier: string; doc_number: string; doc_date: string;
      total_amount: number | null; lines_total: number | null; currency: string;
    }[];
    unassigned: {
      id: number; supplier: string; doc_number: string; doc_date: string;
      amount_usd: number | null; residual_usd: number | null;
    }[];
    /** stock that went below zero at some point in the replay — each one is a
     *  missing purchase document, an unrecorded loss, or a shipped-without */
    negative_stock: {
      key: string; component_id: number | null; component_name: string;
      mpn: string; lcsc: string; first_short: string | null;
      min_qty: number | null; remaining_qty: number | null;
    }[];
    /** freight/duty on a parts document that is not spread into part prices */
    unspread_transport: {
      document_id: number; line_id: number; label: string; supplier: string;
      doc_number: string; doc_date: string; amount: number | null; currency: string;
    }[];
  };
}

/** The vendor-neutral production-step catalog (fab / pcba / final). A step key
 *  travels in a line's `plan_key` and a planned cost item's `step_key`; the
 *  plan-vs-actual match is on the key, never on printed labels. */
export interface CostStepCatalog {
  stages: Record<string, string>;
  steps: { key: string; label: string; default_kind: string;
           default_basis: string | null; stage: string }[];
  vendor_aliases: Record<string, [string, string][]>;
  templates: Record<string, { label: string; step: string }[]>;
}

export function getCostSteps(signal?: AbortSignal): Promise<CostStepCatalog> {
  return request("/api/cost-steps", { signal });
}

/** One share of a split position. Amounts are ABSOLUTE — a percentage entry is
 *  converted in the browser before it is sent, so nothing has to be re-derived. */
export interface SplitChild {
  label?: string;
  kind?: CostLineKind;
  basis?: "per_device" | "per_run";
  amount?: number;
  qty?: number;
  unit_price?: number;
  run_id?: number | null;
  project_id?: number | null;
  /** "excluded" records the share without charging it to anyone */
  allocate?: string;
  mpn?: string;
  notes?: string;
  plan_key?: string;
  plan_kind?: string;
  plan_ref?: string;
}

export function getInvoiceRegister(signal?: AbortSignal): Promise<InvoiceRegister> {
  return request("/api/invoices", { signal });
}

export function getSharedDocuments(signal?: AbortSignal): Promise<RunCostDocumentRow[]> {
  return request("/api/documents", { signal });
}

/** One document with its full line tree — what an expanded invoice row shows. */
export function getDocument(docId: number, signal?: AbortSignal): Promise<RunCostDocumentRow> {
  return request(`/api/run-documents/${docId}`, { signal });
}

export interface DocumentAttachment {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string | null;
}

/** The supplier's original, filed with the money it evidences. Stored under a
 *  `documents/` prefix, so it outlives a deleted run. */
export function getDocumentAttachments(
  docId: number, signal?: AbortSignal,
): Promise<DocumentAttachment[]> {
  return request(`/api/run-documents/${docId}/attachments`, { signal });
}

export function uploadDocumentAttachment(
  docId: number, file: File,
): Promise<{ id: number; document_id: number; filename: string; size_bytes: number }> {
  const fd = new FormData();
  fd.append("file", file);
  return request(`/api/run-documents/${docId}/attachment`, { method: "POST", body: fd });
}

/** Same-origin PATH to an attachment (not an absolute URL) so it can be fed to
 *  `viewkind.fileHref`, which routes PDFs to the browser viewer and CAD/mesh
 *  files to the /view page. `inline` asks the API to display rather than download. */
export function attachmentPath(attachmentId: number, inline = true): string {
  return `/api/run-attachments/${attachmentId}${inline ? "?inline=true" : ""}`;
}

export function createSharedDocument(body: DocumentCreate): Promise<RunCostDocumentRow> {
  return request("/api/documents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function splitCostLine(
  lineId: number,
  children: SplitChild[],
  opts: { allow_parts?: boolean; replace?: boolean } = {},
): Promise<{ parent_id: number; created: number; residual: number; document: RunCostDocumentRow }> {
  return request(`/api/run-cost-lines/${lineId}/split`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ children, ...opts }),
  });
}

export function updateCostLine(
  lineId: number,
  body: Partial<Pick<RunCostLineRow,
    "run_id" | "project_id" | "label" | "kind" | "basis" | "qty" | "unit_price" |
    "allocate" | "notes" | "plan_key" | "plan_kind" | "plan_ref">>,
): Promise<RunCostLineRow> {
  return request(`/api/run-cost-lines/${lineId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function resolveDocumentParts(
  docId: number,
): Promise<{ resolved: number; unresolved: string[]; checked: number }> {
  return request(`/api/run-documents/${docId}/resolve-parts`, { method: "POST" });
}

/** Same matching pass across EVERY unresolved part line — after a library
 *  import, or when unmatched lines have piled up across documents. */
export function resolveAllParts(): Promise<{
  resolved: number;
  unresolved: string[];
  checked: number;
}> {
  return request("/api/cost-lines/resolve-parts", { method: "POST" });
}

/** NBP table-A rate for a currency at a document date (invoice-date
 *  convention). `effective_date` is the publication date actually used —
 *  NBP publishes nothing on weekends or holidays. */
export interface NbpRate {
  currency: string;
  requested_date: string;
  effective_date: string;
  rate_usd: number;
  detail: string;
  requested_date_used: boolean;
}

export function getNbpRate(
  currency: string,
  date: string,
  signal?: AbortSignal,
): Promise<NbpRate> {
  const qs = new URLSearchParams({ currency, date });
  return request(`/api/fx/nbp?${qs}`, { signal });
}

/** Historical rates (currency -> USD per unit) as of an ISO date — the same
 *  `fx.rates_at` resolution the server's money views use, so a client-side
 *  preview can match the stored figures. Empty date = live rates. */
export function getFxAt(
  date: string,
  signal?: AbortSignal,
): Promise<{ date: string; rates: Record<string, number> }> {
  const qs = new URLSearchParams({ date });
  return request(`/api/fx/at?${qs}`, { signal });
}

export interface RunActuals {
  currency: string;
  /** planned-vs-billed per production step (USD); "~<kind>" keys are
   *  unclassified actuals from lines without a step */
  steps?: {
    key: string; label: string; stage: string | null;
    planned_usd: number | null; actual_usd: number | null; delta_usd: number | null;
    /** which documents billed this step on this run */
    sources: { document_id: number; doc_number: string; supplier: string;
               doc_date: string; amount_usd: number | null }[];
  }[];
  qty_planned: number;
  qty_good: number | null;
  qty_sold: number | null;
  sale_unit_price: number | null;
  sale_currency: string;
  customer: string;
  order_ref: string;
  order_date: string;
  /** price per device x units billed, in `currency` */
  revenue: number | null;
  margin: number | null;
  /** margin over REVENUE (gross margin), null when nothing is priced */
  margin_pct: number | null;
  margin_per_device: number | null;
  components: number | null;
  components_by_basis: Record<string, number | null>;
  direct: number | null;
  by_kind: Record<string, number | null>;
  attrition: number | null;
  total: number | null;
  per_device: number | null;
  planned_total: number | null;
  delta: number | null;
  /** null when nothing was planned — a late position has no percentage */
  delta_pct: number | null;
  document_count: number;
  consumption_count: number;
  unknown_rates: string[];
}

/** One slice of a draw, bound to the specific purchase lot it came from. */
export interface ConsumptionLot {
  id: number;
  qty: number;
  /** The LOT's landed unit cost, snapshotted when the draw was bound. */
  unit_cost_usd: number;
  total_usd: number;
  /** reported = the supplier said so; fifo/manual/unallocated = inferred. */
  source: string;
  ext_ref: string;
  lot_line_id: number | null;
  purchase_order: string;
}

export interface ConsumptionRow {
  id: number;
  component_id: number | null;
  mpn: string;
  lcsc: string;
  qty: number;
  /** Quantity-weighted average of `lots`, so both views total the same. */
  unit_cost_usd: number;
  basis: string;
  consumed_at: string;
  note: string;
  total_usd: number;
  lots: ConsumptionLot[];
}

export interface CostPoolRow {
  key: string;
  component_id: number | null;
  mpn: string;
  lcsc: string;
  bought: number;
  used: number;
  lost: number;
  on_hand: number;
  avg_unit_usd: number;
  value_usd: number;
  unknown_rate: boolean;
}

export interface DocumentCreate {
  run_id?: number | null;
  doc_type?: string;
  supplier?: string;
  doc_number?: string;
  external_id?: string;
  doc_date?: string;
  currency?: string;
  fx_rate_usd?: number | null;
  total_amount?: number | null;
  notes?: string;
  lines?: Partial<RunCostLineRow>[];
}

export function getRunDocuments(runId: number, signal?: AbortSignal): Promise<RunCostDocumentRow[]> {
  return request(`/api/runs/${runId}/documents`, { signal });
}

export function getProjectDocuments(
  projectId: number, signal?: AbortSignal,
): Promise<RunCostDocumentRow[]> {
  return request(`/api/projects/${projectId}/documents`, { signal });
}

export function createDocument(projectId: number, body: DocumentCreate): Promise<RunCostDocumentRow> {
  return request(`/api/projects/${projectId}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteDocument(docId: number, force = false): Promise<{ deleted: number }> {
  return request(`/api/run-documents/${docId}${force ? "?force=true" : ""}`, { method: "DELETE" });
}

export function addDocumentLine(
  docId: number, body: Partial<RunCostLineRow>,
): Promise<RunCostLineRow> {
  return request(`/api/run-documents/${docId}/lines`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function voidCostLine(lineId: number): Promise<{ voided: number }> {
  return request(`/api/run-cost-lines/${lineId}`, { method: "DELETE" });
}

export function getRunActuals(runId: number, signal?: AbortSignal): Promise<RunActuals> {
  return request(`/api/runs/${runId}/actuals`, { signal });
}

export function getRunConsumption(runId: number, signal?: AbortSignal): Promise<ConsumptionRow[]> {
  return request(`/api/runs/${runId}/consumption`, { signal });
}

export function addRunConsumption(
  runId: number,
  body: { component_id?: number | null; mpn?: string; lcsc?: string; qty: number;
          unit_cost_usd?: number | null; basis?: string; consumed_at?: string; note?: string },
): Promise<{ id: number; unit_cost_usd: number; basis: string }> {
  return request(`/api/runs/${runId}/consumption`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function consumeFromBom(
  runId: number,
): Promise<{ created: number; unpriced: string[]; volume: number }> {
  return request(`/api/runs/${runId}/consumption/from-bom`, { method: "POST" });
}

export function deleteConsumption(consId: number): Promise<{ deleted: number }> {
  return request(`/api/consumption/${consId}`, { method: "DELETE" });
}

export function addStockAdjustment(
  projectId: number,
  body: { component_id?: number | null; mpn?: string; lcsc?: string; qty_delta: number;
          unit_cost_usd?: number | null; reason?: string; charge_run_id?: number | null;
          adjusted_at?: string; note?: string },
): Promise<{ id: number }> {
  return request(`/api/projects/${projectId}/stock-adjustments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getCostPool(
  projectId: number, signal?: AbortSignal,
): Promise<{ parts: CostPoolRow[]; total_value_usd: number }> {
  return request(`/api/projects/${projectId}/cost-pool`, { signal });
}

// -------------------------------------------------------- where-used & FX

export interface WhereUsedRow {
  project_id: number;
  project_name: string;
  snapshot_id: number;
  ref: string;
  sha: string;
  usages: { board: string; variant: string; refs: string; qty: number; dnp: boolean }[];
}

export function getWhereUsed(componentId: number, signal?: AbortSignal): Promise<WhereUsedRow[]> {
  return request(`/api/components/${componentId}/where-used`, { signal });
}

export interface FxRate {
  currency: string;
  rate_usd: number;
  source: string;
  updated_at: string;
}

export function getFxRates(signal?: AbortSignal): Promise<FxRate[]> {
  return request("/api/fx", { signal });
}

export function refreshFxRates(): Promise<{ updated: number; currencies: number }> {
  return request("/api/fx/refresh", { method: "POST" });
}

export function setFxRate(currency: string, rate_usd: number, source = "manual"): Promise<FxRate> {
  return request("/api/fx", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ currency, rate_usd, source }),
  });
}

// ------------------------------------------------------------ price points

export interface PricePoint {
  id: number;
  source: string;
  qty_from: number;
  unit_price: number;
  currency: string;
  updated_at: string;
}

export interface PricePointsResponse {
  points: PricePoint[];
  supply: {
    /** LCSC retail stock (lcsc.com webshop). */
    stock: number | null;
    /** JLCPCB assembly-parts stock (jlcpcb.com/parts) — a separate pool. */
    jlc_stock: number | null;
    moq: number | null;
    order_multiple: number | null;
    checked_at: string | null;
  } | null;
  /** Quantity held in the user's private JLC parts library. */
  private_qty: number;
}

export function getPricePoints(componentId: number, signal?: AbortSignal): Promise<PricePointsResponse> {
  return request(`/api/components/${componentId}/price-points`, { signal });
}

export function setPricePoints(
  componentId: number,
  points: { qty_from: number; unit_price: number; currency: string; source: string }[],
): Promise<PricePointsResponse> {
  return request(`/api/components/${componentId}/price-points`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(points),
  });
}

export function refreshPricePoints(componentId: number): Promise<PricePointsResponse> {
  return request(`/api/components/${componentId}/price-points/refresh`, { method: "POST" });
}

// --------------------------------------------------------- production files

export interface ProductionFileRow {
  id: number;
  filename: string;
  kind: string; // jlc_bom | jlc_cpl | gerber_zip | gerber | drill | other
  extracted: boolean;
  size_bytes: number;
}

export interface ProductionSet {
  id: number;
  version_no: number;
  source: string; // repo | upload | generated
  comment: string;
  created_at: string;
  files: ProductionFileRow[];
}

export interface JlcBomRow {
  comment: string;
  designators: string[];
  footprint: string;
  lcsc: string;
}

export interface ProductionInfo {
  sets: ProductionSet[];
  current_set_id: number | null;
  repo_available: boolean;
  jlc_bom: { rows: JlcBomRow[]; designators: string[] } | null;
  jlc_designators: string[];
}

export function getRunProduction(runId: number, signal?: AbortSignal): Promise<ProductionInfo> {
  return request(`/api/runs/${runId}/production`, { signal });
}

export function importProductionFromRepo(runId: number): Promise<ProductionSet> {
  return request(`/api/runs/${runId}/production/import-repo`, { method: "POST" });
}

export async function uploadProductionFiles(runId: number, files: File[]): Promise<ProductionSet> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return request(`/api/runs/${runId}/production/upload`, { method: "POST", body: form });
}

export function generateProductionFab(runId: number): Promise<ProductionSet> {
  return request(`/api/runs/${runId}/production/generate`, { method: "POST" });
}

export function productionFileUrl(fileId: number): string {
  return `${API_URL}/api/production-files/${fileId}`;
}

export function deleteProductionSet(setId: number): Promise<{ deleted: number }> {
  return request(`/api/production-sets/${setId}`, { method: "DELETE" });
}

/** Composite SVG of selected gerber layers — returns an object URL. */
export async function renderGerbers(
  setId: number,
  files: { file: string; color: string }[],
): Promise<string> {
  const res = await fetch(`${API_URL}/api/production-sets/${setId}/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files }),
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      // keep status text
    }
    throw new ApiError(res.status, detail);
  }
  return URL.createObjectURL(await res.blob());
}

// ------------------------------------------------------------- click maps

export interface MapBomInfo {
  component_id: number | null;
  component_name: string | null;
  lcsc: string;
  value: string;
  footprint: string;
  mpn: string;
  dnp: boolean;
}

export interface MapSymbol {
  ref: string;
  value: string;
  lib_id?: string;
  at: number[];
  bbox: number[]; // [x1,y1,x2,y2] mm in page/board coords
  side?: string;
  bom?: MapBomInfo;
}

export interface MapSubsheet {
  name: string;
  file: string;
  at: number[];
  size: number[];
  target_svg: string;
}

export interface MapSheet {
  size: number[]; // page [w,h] mm
  symbols: MapSymbol[];
  subsheets: MapSubsheet[];
}

export interface BoardMap {
  pcb: {
    origin: number[];
    size: number[];
    footprints: MapSymbol[];
  } | null;
  sheets: Record<string, MapSheet>;
}

export function getBoardMap(
  snapshotId: number,
  board: string,
  signal?: AbortSignal,
): Promise<BoardMap> {
  return request(`/api/snapshots/${snapshotId}/boards/${encodeURIComponent(board)}/map`, {
    signal,
  });
}

// ----------------------------------------------------- JLC private stock

export interface JlcStockRow {
  id: number;
  lcsc: string;
  description: string;
  mpn: string;
  manufacturer: string;
  package: string;
  qty: number;
  unit_price_usd: number | null;
  /** qty × unit price, converted to the response currency. */
  value: number | null;
  component_id: number | null;
  component_name: string | null;
}

export interface JlcStock {
  available: boolean;
  items: JlcStockRow[];
  currency: string;
  totals: {
    parts: number;
    quantity: number;
    value: number;
    value_usd: number;
    unvalued_parts: number;
  };
  last_sync: string | null;
}

export function getJlcStock(currency?: string, signal?: AbortSignal): Promise<JlcStock> {
  const qs = currency ? `?currency=${encodeURIComponent(currency)}` : "";
  return request(`/api/jlc/stock${qs}`, { signal });
}

export function syncJlcStock(): Promise<{ items: number; valued: number; synced_at: string }> {
  return request("/api/jlc/stock/sync", { method: "POST" });
}

export interface JlcUsageRow {
  project_id: number;
  project_name: string;
  parts: { lcsc: string; refs: string; qty_per_device: number; board: string; held: number }[];
}

export function getJlcStockUsage(signal?: AbortSignal): Promise<JlcUsageRow[]> {
  return request("/api/jlc/stock/usage", { signal });
}

// ------------------------------------------------------------- parts stock
// The same parts measured two ways: what JLC physically HOLDS at market price,
// and what the cost pool says was PAID for the unconsumed remainder. The gap
// between them is the point — see `run_actuals.parts_stock`.

export interface PartsStockRow {
  key: string;
  component_id: number | null;
  component_name: string | null;
  mpn: string;
  lcsc: string;
  description: string;
  /** money side: pool quantities */
  bought: number;
  drawn: number;
  lost: number;
  remaining_qty: number;
  paid_unit_usd: number | null;
  paid_value_usd: number;
  /** physical side: JLC consignment */
  held_qty: number;
  market_unit_usd: number | null;
  market_value_usd: number | null;
  /** the pool remainder priced at today's market — like-for-like with paid_value_usd */
  remaining_at_market_usd: number | null;
  delta_qty: number | null;
  delta_value_usd: number | null;
  /** both = measured twice; pool_only = paid for, JLC doesn't hold it;
   *  jlc_only = JLC holds it and we have NO purchase — a missing invoice */
  state: "both" | "pool_only" | "jlc_only";
  unknown_rate: boolean;
}

export interface PartsStock {
  parts: PartsStockRow[];
  totals: {
    parts: number;
    spent_usd: number | null;
    drawn_usd: number | null;
    adjusted_usd: number | null;
    remaining_at_cost_usd: number | null;
    comparable_cost_usd: number | null;
    comparable_market_usd: number | null;
    jlc_held_value_usd: number | null;
    jlc_held_qty: number;
    over_pool_parts: number;
    missing_invoice_parts: number;
    missing_invoice_value_usd: number | null;
    pool_only_parts: number;
    unvalued_parts: number;
  };
  last_sync: string | null;
}

export function getPartsStock(signal?: AbortSignal): Promise<PartsStock> {
  return request("/api/parts-stock", { signal });
}

/** One event in a part's stock ledger — a purchase, a run draw, or an adjustment. */
export interface PartLedgerEvent {
  date: string;
  kind: "buy" | "use" | "adj";
  ref: string;
  detail: string;
  qty_delta: number | null;
  unit_usd: number | null;
  value_delta_usd: number | null;
  balance_after: number | null;
  avg_usd_after: number | null;
  run_id: number | null;
  document_id: number | null;
  short: boolean;
}

export interface PartLedger {
  component_id: number | null;
  mpn: string;
  lcsc: string;
  events: PartLedgerEvent[];
  balance: number | null;
  value_usd: number | null;
  avg_usd: number | null;
  first_short: string | null;
}

/** Full event timeline for one part — stock over time, verifiable at any date. */
export function getPartsLedger(
  q: { component_id?: number | null; mpn?: string; lcsc?: string },
  signal?: AbortSignal,
): Promise<PartLedger> {
  const p = new URLSearchParams();
  if (q.component_id != null) p.set("component_id", String(q.component_id));
  if (q.mpn) p.set("mpn", q.mpn);
  if (q.lcsc) p.set("lcsc", q.lcsc);
  return request(`/api/parts-ledger?${p.toString()}`, { signal });
}

// ------------------------------------------------- JLC import decision queue
// One row per JLC ASSEMBLY ORDER, which is the unit that maps to a production
// run — never per invoice. A single JLC batch bills several assembly orders for
// different boards, so a per-document link cannot express the relationship.
export interface JlcQueueCandidate {
  run_id: number;
  run_label: string;
  run_qty: number | null;
  panel_factor: number;
  agree: number;
  voted: number;
  share: number;
  mean_frac: number | null;
  implied_devices: number;
  qty_matches: boolean;
  qty_delta: number | null;
  date_gap_days: number | null;
}

export interface JlcQueuePerDevice {
  lcsc: string;
  mpn: string;
  qty: number;
  money: number;
  /** null when no device count is known — then `qty` is the raw total. */
  per_device: number | null;
}

export interface JlcQueueOrder {
  smt_order_code: string;
  batch_num: string;
  invoice_no: string;
  invoice_date: string;
  board_codes: string[];
  /** JLC's own count — PANELS when the order was panelised, never devices. */
  jlc_number: number | null;
  /** Derived from BOM votes, not given by JLC. */
  panel_factor: number | null;
  implied_devices: number | null;
  money_usd: number | null;
  presale_usd: number | null;
  consumed_value_usd: number | null;
  lot_count: number | null;
  part_count: number;
  proposed_outcome: "link_run" | "external" | "needs_human";
  confidence: string;
  proposed_run_id: number | null;
  proposed_run_label: string;
  reason: string;
  collision_note: string;
  candidates: JlcQueueCandidate[];
  per_device: JlcQueuePerDevice[];
  decision: {
    outcome: string;
    run_id: number | null;
    panel_factor: number | null;
    decided_by: string;
    note: string;
    applied_at: string | null;
  } | null;
}

export interface JlcQueue {
  orders: JlcQueueOrder[];
  counts: {
    total: number;
    pending: number;
    decided: number;
    /** Invoiced value awaiting a decision — NOT the register's `unassigned`. */
    pending_invoiced_usd: number;
    /** What booking every pending order as external would remove from run costing. */
    pending_stock_value_usd: number;
  };
}

export function getJlcQueue(signal?: AbortSignal): Promise<JlcQueue> {
  return request("/api/jlc/import/queue", { signal });
}

export function syncJlcImport(): Promise<{
  batches_visible: number;
  fetched: number;
  already_staged: number;
  failed: number;
}> {
  return request("/api/jlc/import/sync", { method: "POST" });
}

export function setJlcDecision(
  smtOrderCode: string,
  body: { outcome: "link_run" | "external" | "pending"; run_id?: number | null; panel_factor?: number | null; note?: string },
): Promise<{ smt_order_code: string; outcome: string; run_id: number | null }> {
  return request(`/api/jlc/import/decision/${encodeURIComponent(smtOrderCode)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function clearJlcDecision(smtOrderCode: string): Promise<{ cleared: string }> {
  return request(`/api/jlc/import/decision/${encodeURIComponent(smtOrderCode)}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------- JLC apply + undo
// The endpoints that MOVE MONEY. Before these existed, importing a JLC month
// meant running Python inside the api container: `import_all.py`, `draws_apply.py`,
// `fix_alloc.py`, `mark_external.py` and seven more, plus raw SQL. Every one of
// them is replaced by a call below, and — unlike the scripts — every one is
// previewable with `dry_run` and reversible through the ledger.

/** What a document import or a decision would do. Produced by the REAL write
 *  path with `dry_run=true`, so the numbers shown are the numbers a real apply
 *  produces — not a second implementation that could disagree. */
export interface JlcApplyPreview {
  dry_run: true;
  plan?: Record<string, unknown>;
  lines?: unknown[];
  result?: Record<string, unknown>;
}

export interface JlcLineReclass {
  lines_seen: number;
  /** Lines whose BUCKET changed (`allocate` or `run_id`) — money actually moved. */
  rebucketed_count: number;
  rebucketed_value_usd: number;
  /** Lines where only `exclude_reason` was filled in. No money moved. Kept
   *  separate on purpose: one combined figure would claim a move that never
   *  happened. */
  reason_only_count: number;
  changes: {
    line_id: number;
    label: string;
    external_line_id: string;
    amount_usd: number;
    from: { allocate: string; exclude_reason: string; run_id: number | null };
    to: { allocate: string; exclude_reason: string; run_id: number | null };
  }[];
}

export interface JlcDecisionApplyResult {
  smt_order_code: string;
  outcome: string;
  run_id: number | null;
  dry_run: boolean;
  lines: JlcLineReclass;
  draws?: Record<string, unknown>;
  movements?: Record<string, unknown>;
  batch_id?: number;
  reversible?: boolean;
}

/** Import one staged assembly batch as a cost document. */
export function applyJlcDocument(
  externalId: string,
  dryRun = true,
): Promise<JlcApplyPreview & { batch_id?: number; document_id?: number }> {
  return request(
    `/api/jlc/import/documents/${encodeURIComponent(externalId)}/apply?dry_run=${dryRun}`,
    { method: "POST" },
  );
}

/** Import one JLC parts order (POB…) — the purchase whose lines ARE the lots. */
export function applyJlcParts(
  pob: string,
  dryRun = true,
): Promise<JlcApplyPreview & { batch_id?: number; document_id?: number }> {
  return request(`/api/jlc/import/parts/${encodeURIComponent(pob)}/apply?dry_run=${dryRun}`, {
    method: "POST",
  });
}

/** Move the money a decision implies: link the lines to the run and write
 *  lot-bound draws, or exclude them and book the stock out to nobody. */
export function applyJlcDecision(
  smtOrderCode: string,
  dryRun = true,
): Promise<JlcDecisionApplyResult> {
  return request(
    `/api/jlc/import/decision/${encodeURIComponent(smtOrderCode)}/apply?dry_run=${dryRun}`,
    { method: "POST" },
  );
}

/** Cache JLC's OWN BOM for one assembly order — the only source of
 *  `componentSource`, i.e. who actually supplied each part. Evidence, not
 *  money: without it, parts JLC supplied itself (`shop`) get charged to the
 *  pool a second time. */
export function fetchJlcOrderBom(smtOrderCode: string): Promise<{
  smt_order_code: string;
  batch: string;
  rows: number;
  by_component_source: Record<string, number>;
  shop_parts: { lcsc: string; mpn: string; qty: number; source: string }[];
}> {
  return request(
    `/api/jlc/import/orders/${encodeURIComponent(smtOrderCode)}/fetch-bom`,
    { method: "POST" },
  );
}

/** Void draws for parts JLC supplied ITSELF (`componentSource='shop'`), so
 *  they are not paid for twice. Needs the order's BOM fetched first. */
export function voidJlcShopDraws(
  smtOrderCode: string,
  dryRun = true,
): Promise<{
  smt_order_code: string;
  status: string;
  run_id?: number;
  shop_parts?: string[];
  would_void?: { consumption_id: number; lcsc: string; mpn: string; qty: number; value_usd: number }[];
  value_usd?: number;
  batch_id?: number;
  note?: string;
}> {
  return request(
    `/api/jlc/import/decision/${encodeURIComponent(smtOrderCode)}/void-shop-draws?dry_run=${dryRun}`,
    { method: "POST" },
  );
}

// ------------------------------------------------------------- write journal

export interface WriteBatch {
  id: number;
  kind: string;
  source_ref: string;
  actor: string;
  summary: Record<string, unknown>;
  identity_before: Record<string, number | boolean> | null;
  identity_after: Record<string, number | boolean> | null;
  created_at: string | null;
  reversed_at: string | null;
  reversed_by_batch_id: number | null;
  row_count: number;
  by_op: Record<string, number>;
  reversible?: boolean;
}

export function getWriteBatches(
  opts: { kind?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<{ batches: WriteBatch[]; total: number }> {
  const qs = new URLSearchParams();
  if (opts.kind) qs.set("kind", opts.kind);
  if (opts.limit) qs.set("limit", String(opts.limit));
  const q = qs.toString();
  return request(`/api/ledger/batches${q ? `?${q}` : ""}`, { signal });
}

export interface WriteBatchRow {
  id: number;
  table: string;
  row_id: number;
  op: string;
  before: Record<string, unknown> | null;
  after_hash: string | null;
}

/** One batch with its journalled rows and the current reversibility check. */
export function getWriteBatch(
  batchId: number,
  signal?: AbortSignal,
): Promise<WriteBatch & { rows: WriteBatchRow[]; check: { blockers: string[] } }> {
  return request(`/api/ledger/batches/${batchId}`, { signal });
}

/** Undo one batch. `dryRun` reports what it would do and every reason it might
 *  refuse. A refusal is a 409 — it names the rows edited since, or the later
 *  batch that has to be reversed first. */
export function reverseWriteBatch(
  batchId: number,
  dryRun = true,
): Promise<{
  status: "would_reverse" | "reversed" | "refused";
  batch_id: number;
  kind: string;
  source_ref: string;
  would: { delete: number; restore: number; reinsert: number };
  reverse_batch_id?: number;
  blockers: string[];
  blocking_batches: number[];
}> {
  return request(`/api/ledger/batches/${batchId}/reverse?dry_run=${dryRun}`, {
    method: "POST",
  });
}

// ------------------------------------------------------- JLC browser session
// Routed since the first day of the JLC work and never called from the browser,
// which is why "Sync from JLCPCB" could only fail into a bare error banner: the
// one thing a human must do — paste the cookies — had no control.

export interface JlcSessionState {
  /** Cookies are STORED. Says nothing about whether they still work — JLC
   *  expires a browser session in about 30 minutes of the token's life and
   *  answers HTTP 460 once it is dead. Use `checkJlcSession` for liveness. */
  configured: boolean;
  label?: string;
  updated_at?: string | null;
  /** Last time a real JLC call succeeded on these cookies. */
  last_ok_at: string | null;
  /** When the session was first seen DEAD, and what JLC said. */
  died_at?: string | null;
  last_error?: string;
  /** Successful keep-alive touches on the current session. Evidence that a
   *  periodic touch is holding it open, rather than an assumption. */
  keepalive_count?: number;
  age_hours?: number | null;
  /** Worked, and not seen dead since. `checkJlcSession` is the authority. */
  alive?: boolean;
}

export function getJlcSession(signal?: AbortSignal): Promise<JlcSessionState> {
  return request("/api/jlc/web/session", { signal });
}

/** Paste the whole `Cookie:` request header from a logged-in jlcpcb.com tab.
 *  It has to be the raw header, not `document.cookie`: `JLCPCB_SESSION_ID` is
 *  httpOnly and therefore invisible to page script. Stored Fernet-encrypted and
 *  never returned by any endpoint. */
export function putJlcSession(
  cookieHeader: string,
  label = "",
): Promise<JlcSessionState & { cookie_names?: string[] }> {
  return request("/api/jlc/web/session", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cookies: cookieHeader, label }),
  });
}

export function clearJlcSession(): Promise<JlcSessionState> {
  return request("/api/jlc/web/session", { method: "DELETE" });
}

export function checkJlcSession(): Promise<{
  ok: boolean;
  expired?: boolean;
  detail?: string;
}> {
  return request("/api/jlc/web/session/check", { method: "POST" });
}

/** Which additive startup DDL landed. A half-applied schema is otherwise silent,
 *  and a feature depending on a missing column fails far from the cause. */
export function getSchemaHealth(signal?: AbortSignal): Promise<{
  ok: boolean;
  statements: Record<string, string>;
  failed: Record<string, string>;
  note: string;
}> {
  return request("/api/health/schema", { signal });
}

// --------------------------------------------------------- stock adjustments
// `addRunConsumption` already covers the manual draw (RunCostsPanel's "Draw from
// pool"). Adjustments were write-only: one could be added and then never seen or
// removed, which is how five phantom rows survived.

export interface StockAdjustment {
  id: number;
  project_id: number | null;
  component_id: number | null;
  mpn: string;
  lcsc: string;
  qty_delta: number;
  unit_cost_usd: number | null;
  reason: string;
  charge_run_id: number | null;
  adjusted_at: string;
  import_ref: string;
  actor: string;
  note: string;
}

/** EVERY adjustment, including those belonging to no project — which the
 *  per-project listing cannot show, and which is exactly what a reconciliation
 *  pass writes. Five such rows once invented 6,368 units of stock and stayed
 *  invisible because nothing listed them. */
export function getAllStockAdjustments(
  reason = "",
  signal?: AbortSignal,
): Promise<{
  adjustments: StockAdjustment[];
  totals: {
    count: number;
    qty_added: number;
    qty_removed: number;
    by_reason: Record<string, number>;
    /** Positive quantity with no cost attached: stock conjured from nothing.
     *  Legitimate for a genuine opening balance, invisible to every value
     *  identity, and the signature of the defect above. */
    zero_cost_positive: number;
  };
}> {
  const qs = reason ? `?reason=${encodeURIComponent(reason)}` : "";
  return request(`/api/stock-adjustments${qs}`, { signal });
}

export function deleteStockAdjustment(adjId: number): Promise<{ deleted: number }> {
  return request(`/api/stock-adjustments/${adjId}`, { method: "DELETE" });
}

export interface JlcStagedRow {
  id: number;
  kind: string;
  external_id: string;
  invoice_no: string;
  doc_date: string;
  total_amount: number | null;
  presale_amount: number | null;
  /** `staged` until an apply stamps it. Left un-stamped by the 2026-07 backfill,
   *  which is why 37 rows read `staged` against 24 documents actually imported. */
  status: string;
  document_id: number | null;
  has_payload: boolean;
  /** The fetch SUCCEEDED and JLC returned nothing — no invoice issued for this
   *  batch yet. A failed fetch leaves `payload` NULL instead, and only that one
   *  is worth re-syncing. */
  payload_empty: boolean;
  fetched_at: string | null;
}

export function getJlcStaged(signal?: AbortSignal): Promise<JlcStagedRow[]> {
  return request("/api/jlc/import/staged", { signal });
}

// ------------------------------------------------------- JLC parts orders (lots)
// Live rather than staged: `sync` stages assembly batches only. These are the
// purchases whose lines ARE the lots every later draw binds to.

export interface JlcPartsOrder {
  pob: string;
  lots: number;
  cancelled_lots: number;
  paid_usd: number;
  document_id: number | null;
  /** A fuzzy reference match, REPORTED and never acted on: POB0202510222305546
   *  exists in this database as POB00202510222305546, and trusting exact match
   *  alone once created a second document for a purchase already recorded. */
  near_duplicate_document_id: number | null;
  near_duplicate_ref: string;
}

export function getJlcPartsOrders(signal?: AbortSignal): Promise<{
  orders: JlcPartsOrder[];
  totals: { orders: number; lots: number; imported: number; not_imported_usd: number };
}> {
  return request("/api/jlc/import/parts", { signal });
}

// ----------------------------------------------------------------- flasher
// Vocabulary (docs/flasher/design.md §13): a RELEASE is only the flash
// (firmware images at offsets); a DEPLOYMENT SCRIPT is the versioned
// config/test scenario that pins one release version + device file versions.

export interface FirmwareAssetRow {
  id: number;
  flashable?: boolean;
  /** recommended offset for this chip+kind ("" when the layout decides) */
  default_address?: string;
  /** deployment versions pinning it — the delete guard's answer */
  used_by?: number;
  filename: string;
  sha256: string;
  size_bytes: number;
  chip: string;
  kind: string;
  build_label: string;
  notes: string;
  uploaded_by: string;
  uploaded_at: string | null;
}

export interface DeploymentImageRow {
  firmware_asset_id: number;
  address: string;
  filename: string;
  kind: string;
  chip: string;
  size_bytes: number;
  sha256: string;
  build_label: string;
}

export interface DeviceFileVersionRow {
  id: number;
  version_no: number;
  status: string;
  sha256: string;
  size_bytes: number;
  comment: string;
  created_by: string;
  created_at: string | null;
  content?: string;
}

export interface DeviceFileRow {
  id: number;
  filename: string;
  description: string;
  current_version_id: number | null;
  versions: DeviceFileVersionRow[];
}

/** One berryware file pinned inside a deployment version. */
export interface DeploymentFileRow {
  device_file_version_id: number;
  device_file_id: number;
  filename: string;
  version_no: number;
  status: string;
  size_bytes: number;
  sha256: string;
  position: number;
  comment: string;
}

/** What moved between two versions — drives the timeline and the publish diff. */
export interface VersionChanges {
  firmware: string;
  files: string;
  procedure: string;
  params: string;
  summary: string;
  changed_files?: string[];
  added_files?: string[];
  removed_files?: string[];
}

export interface ValidationResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
}

/** THE revision: firmware + berryware + procedure + parameters in one row. */
export interface DeploymentVersionRow {
  id: number;
  deployment_id: number;
  version_no: number;
  status: string;
  comment: string;
  created_by: string;
  approved_by: string | null;
  transport_profile: string;
  monitor_baud: number;
  flash_config: Record<string, string> | null;
  param_set_id: number | null;
  param_defaults: Record<string, unknown> | null;
  firmware_fingerprint: string;
  files_fingerprint: string;
  files_label: string;
  berry_bundle_id: number | null;
  created_at: string | null;
  image_count: number;
  file_count: number;
  step_count: number;
  /** present on the deep payloads */
  images?: DeploymentImageRow[];
  files?: DeploymentFileRow[];
  steps?: Record<string, unknown>[];
  param_set_name?: string | null;
  changes?: VersionChanges;
}

export interface DeploymentChannelRow {
  name: string;
  deployment_version_id: number | null;
  version_no: number | null;
  status: string | null;
  updated_by: string;
  updated_at: string | null;
}

export interface DeploymentRow {
  id: number;
  name: string;
  description: string;
  chip: string;
  project_id: number;
  current_version_id: number | null;
  created_at: string | null;
  channels: DeploymentChannelRow[];
  versions: DeploymentVersionRow[];
  current?: DeploymentVersionRow;
}

export interface DeploymentVersionDetail extends DeploymentVersionRow {
  deployment: { id: number; name: string; chip: string; project_id: number };
  changes: VersionChanges;
  validation: ValidationResult;
  where_used: {
    runs: number;
    devices: number;
    batches: { id: number; label: string }[];
    channels: string[];
  };
}

export interface DiffSide<T> {
  before: T | null;
  after: T | null;
  state: "unchanged" | "changed" | "added" | "removed";
}

export interface DeploymentDiff {
  from: { id: number; version_no: number } | null;
  to: { id: number; version_no: number };
  images: (DiffSide<DeploymentImageRow> & { address: string })[];
  files: (DiffSide<DeploymentFileRow> & { filename: string })[];
  steps_changed: boolean;
  steps_before?: Record<string, unknown>[];
  steps_after?: Record<string, unknown>[];
  params_before?: { param_set_id: number | null; defaults: Record<string, unknown> | null };
  params_after?: { param_set_id: number | null; defaults: Record<string, unknown> | null };
  transport_before?: { profile: string; baud: number };
  transport_after?: { profile: string; baud: number };
  changes: VersionChanges;
}

/** Compose a draft. Every section left undefined is INHERITED from
 *  `from_version_id` — "bump the firmware" is a two-field request. */
export interface ComposeBody {
  from_version_id?: number | null;
  comment?: string;
  created_by?: string;
  images?: { firmware_asset_id: number; address: string }[];
  file_version_ids?: number[];
  files_label?: string;
  steps?: Record<string, unknown>[];
  param_set_id?: number | null;
  param_defaults?: Record<string, unknown> | null;
  transport_profile?: string;
  monitor_baud?: number;
  flash_config?: Record<string, string> | null;
  berry_bundle_id?: number | null;
  latest_files?: boolean;
}

export interface ParamSetRow {
  id: number;
  name: string;
  keys: string[];
  updated_by: string;
  updated_at: string | null;
}

export interface FlasherMeta {
  ops: string[];
  transport_profiles: string[];
  firmware_kinds: string[];
  /** the only parts in production */
  chips: string[];
  /** recommended flash offset per chip -> kind, from the partition maps */
  default_offsets: Record<string, Record<string, string>>;
  /** the functional-check vocabulary a step may claim with `check` */
  checks: { name: string; label: string; category: string; position: number }[];
  check_categories: string[];
}

/** One named functionality, proven or disproven by one run. Derived from the
 *  run's own steps and results — see `services/flasher/checks.py`. */
export interface RunCheckRow {
  name: string;
  label: string;
  category: string;
  status: string; // pass | fail | unknown
  detail: string;
  value: Record<string, unknown> | null;
  position: number;
  /** device grid only: which run decided this, and how the attempts went */
  run_id?: number;
  at?: string | null;
  attempts?: Record<string, number>;
}

export interface DeviceListRow {
  id: number;
  mac: string;
  serial: string;
  chip: string;
  tasmota_id: string;
  imei: string;
  iccid: string;
  imsi: string;
  modem_model: string;
  project: { id: number; name: string };
  batch: { id: number; label: string } | null;
  last_status: string;
  runs: number;
  /** newest outcome per check name, tallied */
  checks: { pass: number; fail: number; unknown: number };
  first_seen: string | null;
  last_seen: string | null;
  notes: string;
}

export interface ProgrammingRunSummary {
  id: number;
  status: string;
  operator: string;
  station: string;
  attempt_no: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  draft_run?: boolean;
  production_run: { id: number; label: string } | null;
  deployment: {
    version_id: number;
    name: string;
    deployment_id: number;
    version_no: number;
    status: string;
  } | null;
}

export interface DeviceConfigRow {
  key: string;
  value: string;
  is_secret: boolean;
  current: boolean;
  set_by_run_id: number | null;
  set_at: string | null;
}

export interface DeviceDetailPayload extends Omit<DeviceListRow, "batch" | "runs" | "checks"> {
  modem_fw: string;
  configs: DeviceConfigRow[];
  checks: RunCheckRow[];
  runs: ProgrammingRunSummary[];
}

export interface ProgrammingStepRow {
  idx: number;
  op: string;
  label: string;
  status: string;
  started_at: string | null;
  duration_ms: number | null;
  error: string | null;
  response: unknown;
  /** the functionality this step claims, if any */
  check?: string;
}

export interface ProgrammingRunDetail extends ProgrammingRunSummary {
  device: { id: number; mac: string; serial: string; tasmota_id: string } | null;
  mac_read: string;
  chip_read: string;
  firmware_fingerprint: string;
  files_fingerprint: string;
  release_override_reason: string;
  results: Record<string, unknown> | null;
  params_snapshot: Record<string, unknown> | null;
  client_info: Record<string, unknown> | null;
  checks: RunCheckRow[];
  steps: ProgrammingStepRow[];
}

export interface ProgrammingLogRow {
  seq: number;
  ts: string | null;
  device_ts: string;
  dir: string;
  text: string;
}

export interface BatchProgramming {
  planned: number;
  programmed_ok: number;
  failed_only: string[];
  extra: string[];
  missing: string[];
  unidentified_attempts: number;
  runs: ProgrammingRunSummary[];
  assigned_deployment_version_id: number | null;
  deployment_channel: string;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export function listFirmware(projectId: number, signal?: AbortSignal): Promise<FirmwareAssetRow[]> {
  return request(`/api/flasher/projects/${projectId}/firmware`, { signal });
}

export function uploadFirmware(
  projectId: number,
  file: File,
  meta: { kind: string; chip?: string; build_label?: string; notes?: string; uploaded_by?: string },
): Promise<FirmwareAssetRow & { existing: boolean; chip_detected: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", meta.kind);
  if (meta.chip) form.append("chip", meta.chip);
  if (meta.build_label) form.append("build_label", meta.build_label);
  if (meta.notes) form.append("notes", meta.notes);
  if (meta.uploaded_by) form.append("uploaded_by", meta.uploaded_by);
  return request(`/api/flasher/projects/${projectId}/firmware`, { method: "POST", body: form });
}

export function firmwareBinPath(assetId: number): string {
  return `${API_URL}/api/flasher/firmware/${assetId}/bin`;
}

export function listDeployments(projectId: number, signal?: AbortSignal): Promise<DeploymentRow[]> {
  return request(`/api/flasher/projects/${projectId}/deployments`, { signal });
}

export function getDeployment(id: number, signal?: AbortSignal): Promise<DeploymentRow> {
  return request(`/api/flasher/deployments/${id}`, { signal });
}

export function createDeployment(
  projectId: number,
  body: { name: string; description?: string; chip?: string },
): Promise<{ id: number }> {
  return request(`/api/flasher/projects/${projectId}/deployments`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function updateDeployment(
  id: number,
  body: { name: string; description?: string; chip?: string },
): Promise<DeploymentRow> {
  return request(`/api/flasher/deployments/${id}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/** Delete a deployment. The API refuses while any programming run records it,
 *  so history can never be orphaned by a cleanup. */
export function deleteDeployment(
  id: number,
): Promise<{ ok: boolean; deleted_versions: number; batches_cleared: number }> {
  return request(`/api/flasher/deployments/${id}`, { method: "DELETE" });
}

export function composeVersion(
  deploymentId: number,
  body: ComposeBody,
): Promise<DeploymentVersionRow & { validation: ValidationResult }> {
  return request(`/api/flasher/deployments/${deploymentId}/versions`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function getDeploymentVersion(
  versionId: number,
  signal?: AbortSignal,
): Promise<DeploymentVersionDetail> {
  return request(`/api/flasher/deployment-versions/${versionId}`, { signal });
}

export function patchDeploymentVersion(
  versionId: number,
  body: Omit<ComposeBody, "from_version_id" | "latest_files" | "created_by">,
): Promise<DeploymentVersionRow & { validation: ValidationResult }> {
  return request(`/api/flasher/deployment-versions/${versionId}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function getDeploymentDiff(
  versionId: number,
  against?: number,
  signal?: AbortSignal,
): Promise<DeploymentDiff> {
  const qs = against ? `?against=${against}` : "";
  return request(`/api/flasher/deployment-versions/${versionId}/diff${qs}`, { signal });
}

export function validateDeploymentVersion(
  versionId: number,
  signal?: AbortSignal,
): Promise<ValidationResult> {
  return request(`/api/flasher/deployment-versions/${versionId}/validate`, { signal });
}

export function publishDeploymentVersion(
  versionId: number,
  approvedBy = "",
): Promise<DeploymentVersionRow> {
  return request(`/api/flasher/deployment-versions/${versionId}/publish`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ approved_by: approvedBy }),
  });
}

export function rejectDeploymentVersion(versionId: number): Promise<{ ok: boolean }> {
  return request(`/api/flasher/deployment-versions/${versionId}/reject`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export function setDeploymentChannel(
  deploymentId: number,
  name: string,
  versionId: number | null,
  updatedBy = "",
): Promise<{ ok: boolean }> {
  return request(`/api/flasher/deployments/${deploymentId}/channels/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ deployment_version_id: versionId, updated_by: updatedBy }),
  });
}

export function listDeviceFiles(projectId: number, signal?: AbortSignal): Promise<DeviceFileRow[]> {
  return request(`/api/flasher/projects/${projectId}/device-files`, { signal });
}

export function createDeviceFileVersion(
  projectId: number,
  body: { filename: string; description?: string; content: string; comment?: string; created_by?: string },
): Promise<DeviceFileVersionRow & { file_id: number }> {
  return request(`/api/flasher/projects/${projectId}/device-files`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function getDeviceFileVersion(
  versionId: number,
  signal?: AbortSignal,
): Promise<DeviceFileVersionRow & { file_id: number; filename: string; content: string }> {
  return request(`/api/flasher/device-file-versions/${versionId}`, { signal });
}

export function publishDeviceFileVersion(
  versionId: number,
  approvedBy = "",
): Promise<DeviceFileVersionRow> {
  return request(`/api/flasher/device-file-versions/${versionId}/publish`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ approved_by: approvedBy }),
  });
}

export function rejectDeviceFileVersion(versionId: number): Promise<{ ok: boolean }> {
  return request(`/api/flasher/device-file-versions/${versionId}/reject`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

export interface BerryBundleRow {
  id: number;
  label: string;
  files_fingerprint: string;
  comment: string;
  created_by: string;
  created_at: string | null;
  file_count: number;
  used_by: number;
  files: {
    device_file_version_id: number;
    filename: string;
    version_no: number;
    size_bytes: number;
    sha256: string;
  }[];
}

export function listBerryBundles(projectId: number, signal?: AbortSignal): Promise<BerryBundleRow[]> {
  return request(`/api/flasher/projects/${projectId}/berry-bundles`, { signal });
}

export function createBerryBundle(
  projectId: number,
  body: { label: string; file_version_ids: number[]; comment?: string; created_by?: string },
): Promise<BerryBundleRow> {
  return request(`/api/flasher/projects/${projectId}/berry-bundles`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/** Rename or annotate. The file SET is the identity — a different set is a
 *  different bundle, so it is never editable here. */
export function patchBerryBundle(
  bundleId: number,
  body: { label?: string; comment?: string },
): Promise<BerryBundleRow> {
  return request(`/api/flasher/berry-bundles/${bundleId}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function deleteBerryBundle(bundleId: number): Promise<{ ok: boolean }> {
  return request(`/api/flasher/berry-bundles/${bundleId}`, { method: "DELETE" });
}

export function patchFirmware(
  assetId: number,
  body: { chip?: string; kind?: string; build_label?: string; notes?: string },
): Promise<FirmwareAssetRow> {
  return request(`/api/flasher/firmware/${assetId}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function deleteFirmware(assetId: number): Promise<{ ok: boolean }> {
  return request(`/api/flasher/firmware/${assetId}`, { method: "DELETE" });
}

export function getFirmwareUsage(
  assetId: number,
  signal?: AbortSignal,
): Promise<{ versions: { deployment: string; version_no: number; version_id: number }[] }> {
  return request(`/api/flasher/firmware/${assetId}/usage`, { signal });
}

export function deleteDeviceFileVersion(versionId: number): Promise<{ ok: boolean }> {
  return request(`/api/flasher/device-file-versions/${versionId}`, { method: "DELETE" });
}

export function getDeviceFileVersionUsage(
  versionId: number,
  signal?: AbortSignal,
): Promise<{
  versions: { deployment: string; version_no: number }[];
  bundles: { id: number; label: string }[];
}> {
  return request(`/api/flasher/device-file-versions/${versionId}/usage`, { signal });
}

export interface ImportedFile {
  filename: string;
  device_file_version_id: number;
  version_no: number;
  state: "unchanged" | "changed" | "new";
  size_bytes: number;
}

/** Import a whole berryware folder: unchanged files are reused, only real
 *  content changes mint a version. Returns the resolved set to pin. */
export function importDeviceFiles(
  projectId: number,
  files: File[],
  meta: { label?: string; created_by?: string; publish?: boolean } = {},
): Promise<{ label: string; bundle: BerryBundleRow | null; files: ImportedFile[]; changed: number }> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  if (meta.label) form.append("label", meta.label);
  if (meta.created_by) form.append("created_by", meta.created_by);
  form.append("publish", String(meta.publish ?? true));
  return request(`/api/flasher/projects/${projectId}/device-files/import`, {
    method: "POST",
    body: form,
  });
}

export function listParamSets(projectId: number, signal?: AbortSignal): Promise<ParamSetRow[]> {
  return request(`/api/flasher/projects/${projectId}/param-sets`, { signal });
}

export function putParamSet(
  projectId: number,
  name: string,
  values: Record<string, string | number>,
  updatedBy = "",
): Promise<{ id: number }> {
  return request(`/api/flasher/projects/${projectId}/param-sets/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ values, updated_by: updatedBy }),
  });
}

export function getParamSetValues(
  paramSetId: number,
  signal?: AbortSignal,
): Promise<{ id: number; name: string; values: Record<string, string | number> }> {
  return request(`/api/flasher/param-sets/${paramSetId}/values`, { signal });
}

export function deleteParamSet(paramSetId: number): Promise<{ ok: boolean }> {
  return request(`/api/flasher/param-sets/${paramSetId}`, { method: "DELETE" });
}

export function getFlasherMeta(signal?: AbortSignal): Promise<FlasherMeta> {
  return request("/api/flasher/meta", { signal });
}

/** The device list is the one list that pages on the SERVER — 5502 rows are
 *  1.98 MB and no rendering trick makes that arrive faster. Filtering and
 *  sorting therefore go to the server too: a client holding one page cannot
 *  honestly filter the rest. */
export interface DeviceListPage {
  items: DeviceListRow[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export function listDevices(
  filters: {
    project_id?: number;
    production_run_id?: number;
    status?: string;
    q?: string;
    limit?: number;
    offset?: number;
    sort?: string;
    dir?: "asc" | "desc";
    /** Per-column substring filters, `{column: text}` — sent as repeated
     *  `f=column:text` pairs and applied in SQL. */
    columns?: Record<string, string>;
  },
  signal?: AbortSignal,
): Promise<DeviceListPage> {
  const params = new URLSearchParams();
  if (filters.project_id) params.set("project_id", String(filters.project_id));
  if (filters.production_run_id) params.set("production_run_id", String(filters.production_run_id));
  if (filters.status) params.set("status", filters.status);
  if (filters.q) params.set("q", filters.q);
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.dir) params.set("dir", filters.dir);
  for (const [col, text] of Object.entries(filters.columns ?? {})) {
    if (text.trim()) params.append("f", `${col}:${text.trim()}`);
  }
  const qs = params.toString();
  return request(`/api/flasher/devices${qs ? `?${qs}` : ""}`, { signal });
}

export function getDevice(
  deviceId: number,
  reveal = false,
  signal?: AbortSignal,
): Promise<DeviceDetailPayload> {
  return request(`/api/flasher/devices/${deviceId}${reveal ? "?reveal=true" : ""}`, { signal });
}

export function patchDevice(deviceId: number, notes: string): Promise<{ ok: boolean }> {
  return request(`/api/flasher/devices/${deviceId}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify({ notes }),
  });
}

export function createProgrammingRun(body: {
  /** omit for a bench trial (allowed to run a draft version) */
  production_run_id?: number | null;
  deployment_version_id?: number | null;
  operator?: string;
  station?: string;
  override_reason?: string;
}): Promise<{ run_id: number; deployment_version_id: number; draft_run: boolean }> {
  return request("/api/flasher/runs", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function markRunAborted(runId: number): Promise<{ ok: boolean }> {
  return request(`/api/flasher/runs/${runId}/mark-aborted`, { method: "POST" });
}

export function getProgrammingRun(runId: number, signal?: AbortSignal): Promise<ProgrammingRunDetail> {
  return request(`/api/flasher/runs/${runId}`, { signal });
}

export function getProgrammingLogs(
  runId: number,
  after = 0,
  limit = 2000,
  dir?: string,
  signal?: AbortSignal,
): Promise<ProgrammingLogRow[]> {
  const params = new URLSearchParams({ after: String(after), limit: String(limit) });
  if (dir) params.set("dir", dir);
  return request(`/api/flasher/runs/${runId}/logs?${params}`, { signal });
}

export function getBatchProgramming(
  productionRunId: number,
  signal?: AbortSignal,
): Promise<BatchProgramming> {
  return request(`/api/flasher/production-runs/${productionRunId}/programming`, { signal });
}

export function assignBatchDeployment(
  productionRunId: number,
  body: { deployment_version_id?: number | null; deployment_channel?: string },
): Promise<{ ok: boolean }> {
  return request(`/api/flasher/production-runs/${productionRunId}/deployment`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function mosquittoExportPath(projectId: number): string {
  return `${API_URL}/api/flasher/projects/${projectId}/mosquitto`;
}

/** ws:// (or wss://) address of a programming run's engine socket.
 *  Handles both API_URL shapes: an absolute origin (docker dev sets
 *  VITE_API_URL=http://localhost:8020) swaps http(s) for ws(s); a path
 *  prefix (deployed same-origin build) rides the page's own host. */
export function flasherWsUrl(runId: number): string {
  const path = `/api/flasher/ws/${runId}`;
  if (/^https?:\/\//.test(API_URL)) return API_URL.replace(/^http/, "ws") + path;
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${API_URL}${path}`;
}

// ------------------------------------------------------------- review axis

/** Verification state of a version (see api/app/services/review.py).
 *
 * - `unreviewed` — nobody looked at this version yet.
 * - `failed`     — a machine check found a concrete violation.
 * - `partial`    — items skipped (unverifiable) or still unanswered.
 * - `checked`    — every applicable checklist item answered. */
export type ReviewState = "unreviewed" | "failed" | "partial" | "checked";

export type ReviewActor = "machine" | "agent" | "human";

export type ReviewKind = "component" | "symbol" | "footprint";

export type LifecycleState = "in_design" | "released" | "deprecated" | "obsolete";

export interface ChecklistItemDef {
  key: string;
  text: string;
  hint?: string;
  machine?: boolean;
  /** Present when the item is already answered on the current record. */
  answered?: {
    result: "checked" | "na" | "skipped" | "failed" | "flagged";
    note: string | null;
    actor: string;
    actor_type: ReviewActor;
    at: string;
    /** The answer this one replaced, kept so accepting a flag never erases
     *  what was flagged. A real finding (flagged/failed) outlives any number
     *  of later routine re-checks. */
    superseded?: {
      result: "checked" | "na" | "skipped" | "failed" | "flagged";
      note?: string | null;
      actor?: string;
      actor_type?: ReviewActor;
      at?: string;
      reason?: string;
    };
  };
}

export interface ReviewRecordItem {
  key: string;
  text?: string;
  result: "checked" | "na" | "skipped" | "failed" | "flagged";
  note?: string | null;
  actor: string;
  actor_type: ReviewActor;
  at: string;
}

export interface ReviewRecordRow {
  id: number;
  subject_kind: ReviewKind;
  subject_version_id: number;
  kind: "check" | "carry";
  carried_from_id: number | null;
  checklist_version_id: number | null;
  items: ReviewRecordItem[] | null;
  note: string | null;
  created_by: string;
  actor_type: ReviewActor;
  created_at: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
  revoke_reason: string | null;
}

export interface ReviewStateDetail {
  state: ReviewState;
  provenance: ReviewActor | null;
  record_id: number | null;
  answered: number;
  total: number;
  skipped: number;
  failed: number;
  /** Items verified and found WRONG, deliberately not fixed (subset of failed). */
  flagged?: number;
  unanswered: string[];
}

export interface ReviewDetail extends ReviewStateDetail {
  kind: ReviewKind;
  id: number;
  name: string;
  version_id: number | null;
  checklist_version_id: number | null;
  items: ChecklistItemDef[];
  /** The answers shown were recorded BEFORE the record that set the state —
   *  a one-click "Mark checked" carries no item breakdown of its own. */
  items_carried?: boolean;
  extra_items: ReviewRecordItem[];
  record: ReviewRecordRow | null;
  history: ReviewRecordRow[];
  blocked_items?: string[];
}

export function getReviewDetail(kind: ReviewKind, id: number, signal?: AbortSignal): Promise<ReviewDetail> {
  return request(`/api/reviews/${kind}/${id}`, { signal });
}

export interface ReviewCheckAnswer {
  key: string;
  /** "flagged" = verified and found wrong, recorded without fixing — note required. */
  result: "checked" | "na" | "skipped" | "flagged";
  note?: string;
  /** Required for a key the checklist does not define (a custom check added
   *  for this part alone): the record is the only place that wording lives. */
  text?: string;
  /** Skip only: a structured reason code so the health tab can aggregate WHY
   *  things are unverifiable ("html_datasheet", "no_land_pattern", …). */
  reason?: string;
}

export function recordReviewCheck(
  kind: ReviewKind,
  id: number,
  body: { items?: ReviewCheckAnswer[] | null; note?: string; one_click?: boolean },
): Promise<ReviewDetail> {
  return request(`/api/reviews/${kind}/${id}/check`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      items: body.items ?? null,
      note: body.note ?? null,
      one_click: body.one_click ?? false,
    }),
  });
}

export function revokeReviewCheck(kind: ReviewKind, id: number, reason: string): Promise<ReviewDetail> {
  return request(`/api/reviews/${kind}/${id}/revoke`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ reason }),
  });
}

export function setLifecycle(
  comp_id: number,
  state: LifecycleState,
  note?: string,
): Promise<{ component_id: number; lifecycle_state: LifecycleState; changed: boolean; hidden_from_kicad?: boolean }> {
  return request(`/api/components/${comp_id}/lifecycle`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify({ state, note: note ?? null }),
  });
}

export interface ReviewQueueComponent {
  id: number;
  name: string;
  version_no: number | null;
  category_path: string;
  review_state: ReviewState;
  provenance: ReviewActor | null;
  blockers: string[];
  signoff_state: SignoffState;
  lifecycle: LifecycleState;
  used_in: string[];
  /** An open agent-verification request exists for this subject. */
  agent_requested: boolean;
}

export interface ReviewQueueTemplate {
  id: number;
  name: string;
  kind: "symbol" | "footprint";
  review_state: ReviewState;
  provenance: ReviewActor | null;
  skipped: number;
  failed: number;
  unanswered: number;
  /** Cache key for templatePreviewUrl — see that function. */
  version_id: number | null;
  /** Live components pinning this drawing — on a non-checked row, the number
   *  of parts this one template is holding down. Sort by it: 18 failed
   *  symbols were dragging 159 components when this landed. */
  used_by: number;
  agent_requested: boolean;
}

export interface ReviewQueue {
  components: ReviewQueueComponent[];
  symbols: ReviewQueueTemplate[];
  footprints: ReviewQueueTemplate[];
  /** Set when the queue is scoped to one snapshot's BOM (review-before-build). */
  scope: { snapshot_id: number; sha: string; project: string; components: number } | null;
}

export function getReviewQueue(signal?: AbortSignal, snapshotId?: number): Promise<ReviewQueue> {
  const q = snapshotId ? `?snapshot_id=${snapshotId}` : "";
  return request(`/api/reviews/queue${q}`, { signal });
}

export interface ReviewHealth {
  components: {
    total: number;
    review: Record<string, number>;
    signoff: Record<string, number>;
    lifecycle: Record<string, number>;
  };
  used_not_signed: string[];
  used_deprecated: string[];
  top_skipped_items: { key: string; count: number }[];
  /** WHY items are skipped, from the structured reason a skip can carry. */
  skip_reasons: { reason: string; count: number }[];
  /** Machine failures + flags grouped by checklist key — the work plan view:
   *  one systemic fix clears a whole row. */
  failing_keys: Record<ReviewKind, { key: string; count: number }[]>;
  /** The second-pass worklist: every flagged item on a current version. */
  flagged: {
    kind: ReviewKind;
    id: number;
    name: string;
    key: string;
    note: string | null;
    actor: string;
    actor_type: ReviewActor;
    at: string;
  }[];
}

export function getReviewHealth(signal?: AbortSignal): Promise<ReviewHealth> {
  return request("/api/reviews/health", { signal });
}

// agent verification worklist

export interface ReviewRequestRow {
  id: number;
  kind: ReviewKind;
  subject_id: number;
  name: string;
  note: string | null;
  requested_by: string;
  requested_at: string;
  done_at: string | null;
  done_by: string | null;
}

/** Queue subjects for the agent to verify. Idempotent per open request. */
export function createReviewRequests(
  items: { kind: ReviewKind; id: number }[],
  note?: string,
): Promise<{ ok: true; added: number; already_queued_or_unpublished: number; open_total: number }> {
  return request("/api/reviews/requests", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ items, note: note ?? null }),
  });
}

export function listReviewRequests(
  includeDone = false,
  signal?: AbortSignal,
): Promise<ReviewRequestRow[]> {
  return request(`/api/reviews/requests?include_done=${includeDone}`, { signal });
}

export function withdrawReviewRequest(id: number): Promise<{ ok: true }> {
  return request(`/api/reviews/requests/${id}`, { method: "DELETE" });
}

/** One human gesture over every agent-checked subject: writes the same
 *  one-click confirmation "Mark checked" writes, library-wide. Touches
 *  nothing partial, failed or already human-confirmed. */
export function confirmAgentChecks(): Promise<{
  ok: true;
  confirmed: Record<ReviewKind, string[]>;
  total: number;
}> {
  return request("/api/reviews/confirm-agent", { method: "POST" });
}

// checklists

export interface ChecklistSummary {
  id: number;
  name: string;
  subject_kind: ReviewKind;
  category_id: number | null;
  category_path: string | null;
  description: string;
  version_no: number | null;
  item_count: number;
}

export interface ChecklistDetail {
  id: number;
  name: string;
  subject_kind: ReviewKind;
  category_id: number | null;
  description: string;
  version_no: number | null;
  items: { key: string; text: string; hint?: string; machine?: boolean }[];
  history: { version_no: number; created_at: string; created_by: string; comment: string | null; item_count: number }[];
}

export function listChecklists(signal?: AbortSignal): Promise<ChecklistSummary[]> {
  return request("/api/checklists", { signal });
}

export function getChecklist(id: number, signal?: AbortSignal): Promise<ChecklistDetail> {
  return request(`/api/checklists/${id}`, { signal });
}

export function saveChecklist(
  id: number,
  items: ChecklistDetail["items"],
  comment?: string,
  description?: string,
): Promise<ChecklistDetail> {
  return request(`/api/checklists/${id}`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ items, comment: comment ?? null, description: description ?? null }),
  });
}

export interface ChecklistMeta {
  subject_kinds: ReviewKind[];
  /** Keys `services/validator.py` answers on publish, per kind. `machine: true`
   *  on anything else makes an item nobody can ever answer — the API refuses it
   *  and the editor greys the flag out. */
  machine_keys: Record<string, string[]>;
}

export function getChecklistMeta(signal?: AbortSignal): Promise<ChecklistMeta> {
  return request("/api/checklists/meta", { signal });
}

export interface ResolvedChecklist {
  kind: ReviewKind;
  category_id: number | null;
  /** `from` names the checklist an item came from — the base one, or the
   *  category-scoped list that overrode it. */
  items: { key: string; text: string; hint?: string; machine?: boolean; from: string }[];
}

/** What a subject of this kind (in this category) is actually measured
 *  against: base checklist + every category-scoped one on the path. */
export function resolveChecklist(
  kind: ReviewKind,
  categoryId: number | null,
  signal?: AbortSignal,
): Promise<ResolvedChecklist> {
  const q = categoryId === null ? "" : `&category_id=${categoryId}`;
  return request(`/api/checklists/resolve?kind=${kind}${q}`, { signal });
}

export interface ChecklistVersionDetail {
  id: number;
  name: string;
  version_no: number;
  created_at: string;
  created_by: string;
  comment: string | null;
  items: ChecklistDetail["items"];
}

/** A past version's items — load one to read it or to put it back (saving
 *  republishes it as a new version; the history is append-only). */
export function getChecklistVersion(
  id: number,
  versionNo: number,
  signal?: AbortSignal,
): Promise<ChecklistVersionDetail> {
  return request(`/api/checklists/${id}/versions/${versionNo}`, { signal });
}

export function createChecklist(body: {
  name: string;
  subject_kind: ReviewKind;
  category_id: number | null;
  description: string;
  items: ChecklistDetail["items"];
}): Promise<ChecklistDetail> {
  return request("/api/checklists", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/** Category-scoped lists only — the base checklist of a kind cannot be
 *  deleted, and past verifications keep their own snapshot either way. */
export function deleteChecklist(id: number): Promise<{ ok: true; deleted: string }> {
  return request(`/api/checklists/${id}`, { method: "DELETE" });
}

// project design review

export interface ProjectReviewRow {
  board: string;
  refs: string;
  qty: number;
  value: string;
  footprint: string;
  lcsc: string;
  mpn: string;
  lib_version: string;
  component_id: number | null;
  component_name: string | null;
  current_version_no: number | null;
  review_state: ReviewState | null;
  review_blockers: string[];
  signoff_state: SignoffState | null;
  lifecycle: LifecycleState | null;
  matched: boolean;
}

export interface ProjectReview {
  project_id: number;
  project_name: string;
  sha: string;
  ref_name: string;
  snapshot_id: number;
  rows: ProjectReviewRow[];
  unsigned: string[];
  unreviewed: string[];
  deprecated: string[];
  unmatched_lines: number;
  reviewed: boolean;
  last_review: { id: number; reviewed_by: string; reviewed_at: string; note: string | null; sha: string } | null;
  changed_since_review: string[];
  clean: boolean;
  past_reviews: {
    id: number;
    sha: string;
    reviewed_by: string;
    reviewed_at: string;
    note: string | null;
    summary_counts: Record<string, number> | null;
  }[];
}

export function getProjectReview(projectId: number, sha?: string, signal?: AbortSignal): Promise<ProjectReview> {
  const q = sha ? `?sha=${encodeURIComponent(sha)}` : "";
  return request(`/api/projects/${projectId}/review${q}`, { signal });
}

export function completeProjectReview(projectId: number, sha: string, note?: string): Promise<ProjectReview> {
  return request(`/api/projects/${projectId}/review/complete`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ sha, note: note ?? null }),
  });
}

// ─── The change feed ───────────────────────────────────────────────────────
// What moved in the library lately, and who moved it. The list is a page of
// one-line rows; a row's diff is a SECOND request, made when it is expanded.
// Nothing here fetches a diff eagerly — there are ~18k events and rendering a
// symbol costs a kicad-cli invocation.

export type ChangeKind = "component" | "symbol" | "footprint" | "skill" | "model3d" | "event";

export interface ChangeRow {
  /** `kind:id` — stable across pages, used as the table's row key. */
  key: string;
  kind: ChangeKind;
  id: number;
  entity_id: string;
  /** What the row POINTS AT — the thing with a page. Resolved server-side
   *  because an audit row's `entity_id` names a VERSION, not the parent.
   *  `null` means there is nothing to link (a 3D upload, a deleted subject). */
  subject_kind: "component" | "symbol" | "footprint" | "skill" | null;
  subject_id: number | null;
  name: string;
  action: string;
  action_label: string | null;
  actor: string;
  ts: string;
  version_no: number | null;
  comment: string | null;
  /** False for 3D uploads and audit events: there is no predecessor to diff. */
  diffable: boolean;
}

export interface ChangePage {
  items: ChangeRow[];
  /** Pass back as `cursor`; null means the feed is exhausted. */
  next_cursor: string | null;
  has_more: boolean;
}

export interface ChangeFieldDiff {
  label: string;
  before: string;
  after: string;
}

export interface ChangePropDiff {
  key: string;
  before?: string;
  after?: string;
}

export interface ChangeRowDiff {
  /** "Pins" for a symbol, "Pads" for a footprint. */
  label: string;
  added: { id: string; after: Record<string, string> }[];
  removed: { id: string; before: Record<string, string> }[];
  changed: { id: string; before: Record<string, string>; after: Record<string, string> }[];
  unchanged: number;
}

export interface ChangeDetailPayload {
  kind: ChangeKind;
  id: number;
  name: string;
  created_at: string;
  created_by?: string;
  comment?: string | null;
  version_no?: number;
  version_id?: number;
  prev_version_no?: number | null;
  prev_version_id?: number | null;
  first_version?: boolean;
  // component
  fields?: ChangeFieldDiff[];
  properties?: {
    added: ChangePropDiff[];
    removed: ChangePropDiff[];
    changed: ChangePropDiff[];
    unchanged: number;
  };
  // symbol / footprint
  before_svg?: string | null;
  after_svg?: string;
  rows?: ChangeRowDiff;
  material_changed?: boolean;
  recheck_required?: boolean | null;
  // skill
  diff?: string[];
  diff_truncated?: boolean;
  added_lines?: number;
  removed_lines?: number;
  // model3d
  sha256?: string;
  size_bytes?: number;
  // event
  action?: string;
  actor?: string;
  entity_type?: string;
  entity_id?: string | null;
  details?: { key: string; value: unknown }[];
}

export function listChanges(
  opts: { cursor?: string | null; limit?: number; kinds?: ChangeKind[]; actor?: string; q?: string },
  signal?: AbortSignal,
): Promise<ChangePage> {
  const params = new URLSearchParams();
  if (opts.cursor) params.set("cursor", opts.cursor);
  if (opts.limit) params.set("limit", String(opts.limit));
  // Repeated `kind` params — FastAPI reads them as a list.
  (opts.kinds ?? []).forEach((k) => params.append("kind", k));
  if (opts.actor) params.set("actor", opts.actor);
  if (opts.q) params.set("q", opts.q);
  const qs = params.toString();
  return request(`/api/changes${qs ? `?${qs}` : ""}`, { signal });
}

export function getChangeDetail(
  kind: ChangeKind,
  id: number,
  signal?: AbortSignal,
): Promise<ChangeDetailPayload> {
  return request(`/api/changes/${kind}/${id}`, { signal });
}

/** A specific VERSION of a template, rendered. Unlike `templatePreviewUrl`,
 *  whose `v` is only a cache key, the version here genuinely selects what is
 *  drawn — which is what a before/after pane needs. Version rows are immutable,
 *  so the server answers `immutable` and the browser holds it for a year. */
export function templateVersionPreviewUrl(
  kind: "symbol" | "footprint",
  id: number,
  versionNo: number,
): string {
  return `${API_URL}/api/${kind}s/${id}/versions/${versionNo}/preview.svg`;
}

/** Fetch a same-origin SVG as TEXT.
 *
 *  The before/after panes need the render's own `width`/`height`, which
 *  kicad-cli emits in MILLIMETRES — that is what lets both versions be drawn
 *  at one shared scale so a difference overlay lines up. An `<img>` would show
 *  the picture but never tell the page how big the drawing is. */
export async function fetchSvgText(path: string, signal?: AbortSignal): Promise<string> {
  const res = await fetch(`${API_URL}${path}`, { credentials: "include", signal });
  if (!res.ok) throw new ApiError(res.status, `render failed (${res.status})`);
  return res.text();
}

// --------------------------------------------------------------- simulation

/** A simulation source: a board's schematic at an ingested commit, or a sheet
 *  set the user dropped in the browser. Both feed the same pipeline. */
export type SimSourceRef =
  | { kind: "snapshot"; snapshotId: number; board: string }
  | { kind: "upload"; uploadId: string };

function simBase(src: SimSourceRef): string {
  return src.kind === "snapshot"
    ? `/api/sim/snapshot/${src.snapshotId}/${encodeURIComponent(src.board)}`
    : `/api/sim/upload/${encodeURIComponent(src.uploadId)}`;
}

/** One sheet INSTANCE. A sheet file placed twice appears twice, with
 *  different paths and different net names. */
export interface SimSheet {
  name: string;
  /** Instance path — the identifier every other call takes. */
  path: string;
  page: string;
  depth: number;
  rel: string;
  error?: string;
}

export interface SimSheetList {
  source: { kind: string; label: string };
  sheets: SimSheet[];
}

export interface SimWire {
  id: string;
  pts: number[][];
  net: string | null;
}

export interface SimPin {
  ref: string;
  pin: string;
  name: string;
  type: string;
  /** Connection point (where the wire meets the pin). */
  at: number[];
  /** Body end of the pin stub — the direction a current arrow runs. */
  root: number[];
  power: boolean;
  net: string | null;
  group: string;
}

export interface SimSymbol {
  ref: string;
  value: string;
  lib_id: string;
  at: number[];
  angle: number;
  bbox: number[] | null;
  power: boolean;
  sim: Record<string, string>;
}

export interface SimGroup {
  id: string;
  pins: { ref: string; pin: string }[];
  labels: string[];
  wires: string[];
  net: string | null;
  /** Vector name in the run payload (`v(<spice>)` without the wrapper). */
  spice?: string;
  /** ngspice aliases ground to node 0 and emits no vector for it. */
  ground?: boolean;
  /** Named from a label rather than from the netlist — not a simulated node. */
  derived?: boolean;
}

export interface SimGeometry {
  size: number[];
  instance_path: string;
  wires: (SimWire & { group: string })[];
  junctions: { at: number[]; net: string | null; group: string }[];
  labels: { id: string; text: string; kind: string; at: number[]; net: string | null }[];
  pins: SimPin[];
  symbols: SimSymbol[];
  subsheets: { name: string; file: string; at: number[]; size: number[] }[];
  texts: { at: number[]; text: string; directive: boolean }[];
  groups: SimGroup[];
  warnings: string[];
  sheet: { name: string; path: string; depth: number };
  source: { kind: string; label: string };
}

export interface SimNet {
  name: string;
  code: string;
  pins: { ref: string; pin: string }[];
  spice: string;
  ground: boolean;
}

export async function uploadSimSheets(
  files: File[],
  root = "",
  signal?: AbortSignal,
): Promise<{ id: string; root: string; files: string[] }> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  if (root) form.append("root", root);
  return request("/api/sim/uploads", { method: "POST", body: form, signal });
}

export async function getSimSheets(src: SimSourceRef, signal?: AbortSignal): Promise<SimSheetList> {
  return request(`${simBase(src)}/sheets`, { signal });
}

export async function getSimGeometry(
  src: SimSourceRef,
  sheet: string,
  signal?: AbortSignal,
): Promise<SimGeometry> {
  const qs = sheet ? `?sheet=${encodeURIComponent(sheet)}` : "";
  return request(`${simBase(src)}/geometry${qs}`, { signal });
}

export async function getSimNetlist(
  src: SimSourceRef,
  signal?: AbortSignal,
): Promise<{ spice: string; nets: SimNet[] }> {
  return request(`${simBase(src)}/netlist`, { signal });
}

/** URL of the sheet drawing — kicad-cli's own render, whose viewBox is in
 *  millimetres and shares the geometry's coordinate space. */
export function simSheetSvgUrl(src: SimSourceRef, sheet: string): string {
  const qs = sheet ? `?sheet=${encodeURIComponent(sheet)}` : "";
  return `${API_URL}${simBase(src)}/sheet.svg${qs}`;
}

/** Run one scenario. The answer is the binary 7SIM payload, not JSON —
 *  thousands of points across a dozen vectors are float arrays, and that is
 *  what the plotter wants. Decode it with `decodeSimPayload`. */
export async function runSimulation(
  src: SimSourceRef,
  body: { sheet?: string; control?: string | null; analysis?: string; timeout?: number },
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${simBase(src)}/run`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw new ApiError(0, `Cannot reach API at ${apiOrigin()} (${errorMessage(err)})`);
  }
  if (!res.ok) {
    let detail = "";
    try {
      const b = (await res.json()) as { detail?: unknown };
      if (typeof b.detail === "string") detail = b.detail;
    } catch {
      // a non-JSON error body — fall through to the status line
    }
    throw new ApiError(res.status, detail || `${res.status} ${res.statusText}`);
  }
  return res.arrayBuffer();
}
