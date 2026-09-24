/** Typed client for the Project Management Platform API.
 *
 * Shapes mirror the FastAPI routers in platform/api/app/routers/
 * (categories.py, components.py, import_station.py).
 */
import { APP_BASE } from "./appbase";
import type { LibSymbol, SchTheme, SheetDrawing } from "./sim/draw/types";
import type { PaletteEntry, SchDoc } from "./sim/edit/doc";

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

/** The API address as an ABSOLUTE url, the way THIS browser reaches it.
 *
 * The flasher sends it to the engine, which needs an address a DEVICE on WiFi
 * can also fetch from. A relative API_URL resolves against the current page,
 * so a deployment under /lib yields "https://host/lib". A VITE_API_URL that
 * names a loopback port yields that port, and the engine drops it — see
 * `_resolve_base_url` in api/app/services/flasher/engine.py.
 */
export const apiBaseUrl = (): string => {
  if (typeof window === "undefined") return API_URL;
  return new URL(API_URL || "/", window.location.href).href.replace(/\/+$/, "");
};

/** The app's own mount point as an absolute url.
 *
 * The dev server proxies /api (see vite.config.ts) and the deployed image is
 * same-origin, so this address reaches the API in both — including on a dev
 * machine, where API_URL points at a loopback port no device can use. Opening
 * the bench by the machine's LAN address is therefore all the flasher needs.
 */
export const sameOriginBase = (): string => {
  if (typeof window === "undefined") return APP_BASE;
  return new URL(APP_BASE || "/", window.location.href).href.replace(/\/+$/, "");
};

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
  /** Revision label parsed from the document ("Rev. B", "SLVSF14B"), or null. */
  doc_revision: string | null;
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
  /** Revision label of the CURRENT stored copy, or null when none parsed. */
  doc_revision: string | null;
  /** Other components whose current copy is the very same stored file. */
  shared_with: string[];
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

/** What a rename did: the new name, and every component republished to follow it. */
export interface RenameResult {
  ok: true;
  kind: "footprint" | "symbol";
  id: number;
  old_name: string;
  new_name: string;
  version_no: number;
  components: {
    component: string;
    version_no: number;
    signoff: { carried: boolean; reason?: string } | null;
    review_carry: { carried: boolean; reason?: string } | null;
  }[];
  categories_updated: string[];
  mirror_file_removed: boolean;
  rebuilt_libraries: string[];
  mirror_warnings: string[];
}

/**
 * Renames a footprint or a base symbol and moves every reference with it.
 *
 * NOT a way to correct a drawing: it publishes one version whose only change is
 * the name, and republishes each component that references it. Verification and
 * sign-off carry, because nothing reaching a board changed. A board already laid
 * out keeps the OLD library id until its owner updates the project from the
 * schematic.
 */
export function renameTemplate(
  kind: TemplateKind,
  id: number,
  name: string,
  comment: string,
): Promise<RenameResult> {
  return request(`/api/${kind}/${id}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, comment }),
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
  kind: "primitive" | "part" | "composed";
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

/** One instance inside a composed model. `nodes` is {model port: node},
 *  where a node is a symbol PIN NUMBER or an internal net written "@name".
 *  `params` is {model param: binding} — see SimBinding. */
export interface SimBlock {
  ref: string;
  model: string;
  nodes: Record<string, string>;
  params?: Record<string, string>;
}

/** A tie inside a composed model: package copper, or a termination. Two
 *  symbol pins joined by real resistance, never by sharing one port —
 *  the schematic may put them on different nets. */
export interface SimTie {
  ref: string;
  a: string;
  b: string;
  value: string;
}

export interface SimComposition {
  blocks: SimBlock[];
  resistors: SimTie[];
  /** Pins left out ON PURPOSE. The composed form of the "-" sentinel: a pin
   *  that is neither wired nor listed here is an error, not an omission. */
  unmodelled: string[];
  /** Wrapper parameter defaults that differ from the block model's own. */
  defaults: Record<string, string>;
}

export const SIM_SHARED = "$shared";
export const SIM_OWN = "$own";

export interface SimBlockSpec {
  name: string;
  kind: string;
  ports: string[];
  params: Record<string, string>;
}

export interface SymbolSimLinkInfo {
  symbol: { id: number; name: string };
  pins: SymbolSimPin[];
  link: {
    model_id: number;
    model_name: string;
    pin_map: Record<string, string>;
    /** "model" links one hand-written subcircuit; "composed" builds it from
     *  blocks and derives the pin map. */
    mode: string;
    composition: SimComposition | null;
    updated_at: string | null;
    updated_by: string;
    /** Human-readable reasons the stored map may no longer mean what its
     *  author intended. Non-empty = the mirror WITHHOLDS the Sim fields.
     *  In composed mode these are the reasons the design no longer builds. */
    stale: string[];
  } | null;
  models: { id: number; name: string; kind: string; ports: string[];
            params: Record<string, string> }[];
  /** What a composition may use as a block — every model except the generated
   *  wrappers, which belong to one symbol each. */
  blocks: SimBlockSpec[];
  /** The name the generated wrapper takes for this symbol. */
  wrapper_name: string;
  /** The not-connected sentinel a pin can map to ("-"). */
  nc: string;
}

export interface SimCompositionPreview {
  name: string;
  params: Record<string, string>;
  source_text: string;
  ports: string[];
  pin_map: Record<string, string>;
  sim_pins: string;
  errors: string[];
  warnings: string[];
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

/** The .subckt a composition WOULD publish. Writes nothing — the editor shows
 *  it live, because a generated netlist nobody reads is one nobody checks. */
export function previewSimComposition(
  id: number,
  composition: SimComposition,
  signal?: AbortSignal,
): Promise<SimCompositionPreview> {
  return request(`/api/symbols/${id}/sim-composition/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(composition),
    signal,
  });
}

/** PUBLISH the composition: generates the wrapper, versions it, links it and
 *  rebuilds the mirror. */
export function saveSimComposition(
  id: number,
  composition: SimComposition,
  comment = "",
): Promise<SimLinkSaveResult & { source_text: string; version_no: number }> {
  return request(`/api/symbols/${id}/sim-composition`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...composition, comment }),
  });
}

/** Remove a sim model outright. Refused while any symbol links it or any
 *  other model instantiates it. */
export function deleteSimModel(id: number): Promise<{ ok: true; model: string }> {
  return request(`/api/sim-models/${id}`, { method: "DELETE" });
}

/** Render UNSAVED geometry so the paste box can show it before filing.
 *  Returns an object URL the caller must revoke, and the symbol's unit count.
 *  Writes nothing.
 *
 *  `unit` is 1-based, as KiCad numbers them. A blob: URL carries no response
 *  headers, so the paste box cannot learn the count the way every other
 *  preview does — it has to come back here, and the caller re-POSTs to page. */
export async function renderTemplateSource(
  kind: TemplateKind,
  source_text: string,
  signal?: AbortSignal,
  unit?: number,
): Promise<{ url: string; units: number }> {
  const res = await fetch(`${API_URL}/api/${kind}/preview.svg`, {
    method: "POST",
    // The API is default-deny and a dev server is cross-origin, so the session
    // cookie has to be asked for — see `request()` above.
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_text, unit }),
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
  const units = Number(res.headers.get("X-Unit-Count") ?? "1");
  return {
    url: URL.createObjectURL(await res.blob()),
    units: Number.isFinite(units) && units > 0 ? units : 1,
  };
}

// -------------------------------------------------------------- datasheets

export interface DatasheetFetchResult {
  id: number;
  /** "new_version" | "unchanged" | "restamped" (same text, re-signed bytes —
   *  nothing stored) | "skipped_unstable_non_pdf" | "no_url" */
  result: string;
  version_no?: number;
  component_bumped_to?: number | null;
  /** new_version only: the bytes were already held for another component. */
  relinked?: boolean;
  doc_revision?: string | null;
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
  /** "system" | "light" | "dark" — see `theme.ts`. Carried here, and not on
   *  `/api/account`, because the gate's fetch is the only one that has
   *  happened by the time the theme must be on the page. */
  theme: string;
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

/** Save the signed-in user's light/dark choice. `theme.ts` owns the rest. */
export function setOwnTheme(theme: string): Promise<{ theme: string }> {
  return request("/api/account/theme", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ theme }),
  });
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

// ------------------------------------------------------- own account

/** The signed-in user's own record, tokens revealed. `PlatformUser` already
 *  describes the shape — this is the same payload the admin endpoints return,
 *  for one's own row. */
export function getAccount(signal?: AbortSignal): Promise<PlatformUser> {
  return request<PlatformUser>("/api/account", { signal });
}

export function addOwnToken(label = ""): Promise<PlatformUser> {
  return request<PlatformUser>("/api/account/tokens", {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

export function revokeOwnToken(tokenId: number): Promise<PlatformUser> {
  return request<PlatformUser>(`/api/account/tokens/${tokenId}`, { method: "DELETE" });
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
  /** Re-signed PDFs with identical text: nothing stored. */
  restamped: number;
  /** New versions that reused bytes already held for another component. */
  relinked: number;
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
  storage: {
    documents: number;
    document_bytes: number;
    versions: number;
    documents_shared_by_several_datasheets: number;
    hosts_learned: number;
  };
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
  /** `board` is a design; `harness` is a simulation project — a root sheet
   *  carrying SPICE directives, classified at ingest. A snapshot from before
   *  2026-09-11 is classified on first read, so treat a missing value as a
   *  board. */
  kind?: "board" | "harness";
  directives?: number;
  variants: { name: string; description: string }[];
  layers: { name: string; type: string; user_name: string }[];
}

/** The design boards of a snapshot — what the project view, the BOM and a
 *  production run mean by "board". Simulation harnesses live under the
 *  Simulator, which lists them itself. */
export function designBoards(s: { boards: SnapshotBoard[] } | null | undefined): SnapshotBoard[] {
  return (s?.boards ?? []).filter((b) => b.kind !== "harness");
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

// ------------------------------------------------------- git credentials

/** A named git ACCOUNT, assignable to any number of projects. The token is
 *  never returned — only whether one is stored and what the last check said. */
export interface GitCredential {
  id: number;
  name: string;
  host: string;
  username: string;
  description: string;
  has_token: boolean;
  checked_at: string | null;
  /** null = never checked, or checked while no project used it. */
  check_ok: boolean | null;
  check_detail: string;
  created_at: string;
  created_by: string;
  projects: { id: number; name: string }[];
}

export interface GitCredentialCheck extends GitCredential {
  results: { project: string; project_id: number; ok: boolean; detail: string }[];
}

export function getGitCredentials(signal?: AbortSignal): Promise<GitCredential[]> {
  return request<GitCredential[]>("/api/git-credentials", { signal });
}

export function createGitCredential(body: {
  name: string; token: string; host?: string; username?: string; description?: string;
}): Promise<GitCredential> {
  return request<GitCredential>("/api/git-credentials", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateGitCredential(
  id: number,
  body: { name?: string; token?: string; host?: string; username?: string; description?: string },
): Promise<GitCredential> {
  return request<GitCredential>(`/api/git-credentials/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteGitCredential(id: number): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/api/git-credentials/${id}`, { method: "DELETE" });
}

export function checkGitCredential(id: number): Promise<GitCredentialCheck> {
  return request<GitCredentialCheck>(`/api/git-credentials/${id}/check`, { method: "POST" });
}

export interface ProjectInfo {
  id: number;
  name: string;
  git_url: string;
  has_token: boolean;
  /** Which secret is in force: a named account, this project's own, or none. */
  token_source: "credential" | "project" | "none";
  git_credential_id: number | null;
  git_credential: { id: number; name: string } | null;
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
  git_credential_id?: number | null;
  git_token?: string | null;
  default_branch?: string;
  display_currency?: string | null;
  description?: string;
}

export interface ProjectPatchBody {
  name?: string;
  git_url?: string;
  /** "" clears the stored token; omit to leave unchanged. */
  /** 0 unassigns; omit to leave unchanged. */
  git_credential_id?: number | null;
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
  /** what the batch is set to be programmed with: a pinned version, or a
   *  channel to follow. Both empty = nothing assigned, so whatever the bench
   *  picks is not an override. */
  deployment_version_id?: number | null;
  deployment_channel?: string;
  /** must its units pass the project's test? */
  requires_test?: boolean;
  /** the sale side: price PER DEVICE, units billed, and the customer order */
  qty_sold?: number | null;
  sale_unit_price?: number | null;
  /** empty inherits the project's display currency */
  sale_currency?: string;
  customer?: string;
  order_ref?: string;
  order_date?: string;
  created_at: string;
  /** the project's NAME, on the list endpoints only */
  project?: string;
  /** THE BOOKS (decision 0044). Set means this batch's cost is settled: every
   *  supplier document charging it, written before this moment, is read-only,
   *  and the only way to move the figure is a dated correction document.
   *  `closed_cost_usd` / `closed_units` are what it cost at that moment, so a
   *  later correction shows as a variance instead of as the figure it always
   *  was. */
  closed_at?: string | null;
  closed_by?: string;
  closed_cost_usd?: number | null;
  closed_units?: number | null;
  attachment_count: number;
  /** Devices this batch MADE (`DeviceUnit.production_run_id`), not the retired
   *  `run_devices` registry. */
  device_count: number;
  effective?: RunEffective | null;
  overrides?: Record<string, unknown>;
  attachments?: RunAttachmentRow[];
  devices?: RunDeviceRow[];
  /** decision 0003: where this batch's units went, and what is still on the shelf */
  sales?: RunSales;
}

export interface RunSales {
  qty_sold_derived: number;
  orders: {
    order_id: number;
    order_ref: string;
    customer: string;
    order_line_id: number;
    product: string;
    qty_from_run: number;
  }[];
  stock: FinishedStockRow | null;
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
  /** attach, re-point or detach the snapshot the run's planned BOM comes from;
   *  it must belong to the same project, be `ready`, and build the run's board.
   *  The server refuses (409) while `b<id>` overrides are keyed to the old
   *  snapshot's BOM lines. `null` DETACHES — omit to leave it alone. */
  snapshot_id?: number | null;
  /** sale side. Only fields actually present are applied, so patching a label
   *  can never blank a price. `null` clears one deliberately. */
  sale_unit_price?: number | null;
  sale_currency?: string;
  qty_sold?: number | null;
  qty_good?: number | null;
  customer?: string;
  order_ref?: string;
  order_date?: string;
  /** must a unit of this batch pass the project's test to count as
   *  programmed? Only runs made AFTER the change see it — every programming
   *  run keeps its own copy of the answer. */
  requires_test?: boolean;
}

export function getRuns(projectId: number, signal?: AbortSignal): Promise<RunInfo[]> {
  return request(`/api/projects/${projectId}/runs`, { signal });
}

/** Every batch, across every project, newest run date first. The project tab
 *  answers "what has this product built"; this answers "what is in production
 *  anywhere", which had no home — the only cross-project list was the invoice
 *  register's, so a batch nobody had billed yet was invisible. */
export function getAllRuns(signal?: AbortSignal): Promise<RunInfo[]> {
  return request("/api/runs", { signal });
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

/** Close the books on a batch (decision 0044) — its documents become read-only
 *  and its cost is snapshotted, so a later correction reads as a variance. */
export function closeRun(runId: number, body: { reason?: string } = {}):
  Promise<RunInfo> {
  return request(`/api/runs/${runId}/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Reopen a closed batch, making its documents editable again. The snapshot
 *  taken at close is cleared: a batch closed twice has a new "what it cost when
 *  the books closed", and the audit row keeps both. */
export function reopenRun(runId: number, body: { reason?: string } = {}):
  Promise<RunInfo> {
  return request(`/api/runs/${runId}/reopen`, {
    method: "POST",
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
// Supplier documents entered AFTER a run. A position on a STOCK step
// (`parts:pool`, `parts:prepaid`, `parts:attrition`, `pcba:parts`) with no run
// feeds the component cost pool; runs draw from it (consumption) at a moving
// average. Attrition is recorded as a stock adjustment, optionally charged to a
// run.

/** The coarse money bucket. DERIVED on the server from the position's step
 *  (`cost_steps.kind_of`) since decision 0047 — it is not a field any more and
 *  cannot be sent. Read it to label a row; never write it. */
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
  /** derived from `plan_key` on the server — read-only (decision 0047) */
  kind: CostLineKind;
  /** an explicit link to one planned cost item. Its own field since decision
   *  0047: it used to be written into `plan_key`, which now says what the
   *  position IS, so linking a part line to a cost item dropped it out of the
   *  pool. */
  plan_item_id?: number | null;
  basis: "per_device" | "per_run";
  label: string;
  qty: number;
  /** qty x run units for a per_device line — what the money is charged on */
  qty_effective?: number;
  unit_price: number;
  line_total: number | null;
  currency: string;
  /** "none" | "pooled" | "by_value" | "by_qty" | "excluded" — the HOW axis for a
   *  position that goes to stock, and the marker for one charged to nobody
   *  (decision 0045) */
  allocate: string;
  /** why a position is charged to nobody, "" otherwise */
  exclude_reason?: string;
  component_id: number | null;
  /** the linked library part's name, "" when the line is not linked */
  component_name?: string;
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

export interface DocumentLock {
  run_id: number;
  label: string;
  closed_at: string | null;
  closed_by: string;
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
  /** Batches whose books are CLOSED that this document charges (decision 0044).
   *  Non-empty means every write path refuses it and the way to change what it
   *  says is a correction document. Computed server-side on every read, so
   *  reopening a batch simply empties it. */
  locked?: DocumentLock[];
  /** this document CORRECTS that one */
  corrects_document_id?: number | null;
  /** documents that correct THIS one (full view only) */
  corrected_by?: { id: number; doc_number: string; doc_date: string }[];
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
    /** set = this batch's books are closed (decision 0044) */
    closed_at: string | null;
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
    /** children claiming MORE than the header they split; sub-cent by
     *  construction, but it has to be in the identity or it cannot close */
    overallocated_usd?: number | null;
    /** what our lines add up to, against `total_usd` which is what was printed */
    lines_total_usd?: number | null;
    /** THE INVARIANT: lines minus every bucket. Non-zero means a bug in
     *  `run_actuals`, and it is now exactly 0 (decision 0048). */
    gap_usd: number | null;
    /** `printed - lines`: money that left the company and is on no line. Real,
     *  small, and NOT fixable by editing a line — suppliers print rounded
     *  totals. `issues.untranscribed` names every document. */
    untranscribed_usd?: number | null;
    /** why the excluded money is excluded */
    excluded_by_reason_usd?: Record<string, number | null>;
    /** how much of it says nothing — `legacy_unstated` is "never given" */
    excluded_unstated_usd?: number | null;
    unknown_rates: string[];
    by_supplier_usd: Record<string, number | null>;
  };
  by_project_usd: Record<string, number | null>;
  by_run_usd: Record<string, {
    direct_usd: number | null;
    components_usd: number | null;
    total_usd: number | null;
    /** devices recorded as produced on the batch */
    produced: number;
    /** what ONE of them cost — the figure a shipped unit carries onto its
     *  order. Null until the batch has device records. A batch has no revenue
     *  and no margin (decision 0043). */
    unit_cost_usd: number | null;
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
  basis?: "per_device" | "per_run";
  amount?: number;
  qty?: number;
  unit_price?: number;
  run_id?: number | null;
  project_id?: number | null;
  /** "excluded" records the share without charging it to anyone */
  allocate?: string;
  /** ...and WHY. The API refuses `allocate: "excluded"` without one. */
  exclude_reason?: string;
  mpn?: string;
  lcsc?: string;
  /** the library part this share bought, when it bought one */
  component_id?: number | null;
  component_name?: string;
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
  // `kind` is NOT writable — it is derived from `plan_key` on the server
  // (decision 0047).
  body: Partial<Pick<RunCostLineRow,
    "run_id" | "project_id" | "label" | "basis" | "qty" | "unit_price" |
    "allocate" | "exclude_reason" | "notes" |
    "plan_key" | "plan_kind" | "plan_ref" | "plan_item_id" |
    "component_id" | "mpn" | "lcsc">>,
): Promise<RunCostLineRow> {
  return request(`/api/run-cost-lines/${lineId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Apply every staged line edit on a document as ONE transaction.
 *
 *  A per-field save cannot express a SWAP: moving the component mapping of
 *  position A onto B and B's onto A is legal, but either half alone strands the
 *  draws priced against it. The server guards the batch's NET effect and writes
 *  all of it or none (decision 0040).
 */
export function editDocumentLines(
  docId: number,
  body: {
    /** the header fields, changed in the same transaction as the positions */
    document?: Partial<Pick<RunCostDocumentRow,
      "supplier" | "doc_number" | "external_id" | "doc_date" | "currency" |
      "total_amount" | "doc_type" | "notes" | "paid_at" | "fx_rate_usd">>;
    updates?: (Partial<RunCostLineRow> & { id: number })[];
    creates?: Record<string, unknown>[];
    deletes?: number[];
  },
): Promise<{ updated: number; voided: number; created: number; document: RunCostDocumentRow }> {
  return request(`/api/run-documents/${docId}/lines`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Write a CORRECTION of a document (decision 0044).
 *
 *  The only way to change what a CLOSED batch cost. The original is never
 *  touched — it keeps the figures it was printed with — and the correction
 *  stands beside it, dated today, carrying what actually changed. A credit is a
 *  negative line. It is an ordinary document in every other respect.
 */
export function createCorrection(
  docId: number,
  body: {
    doc_date?: string;
    doc_number?: string;
    notes?: string;
    total_amount?: number | null;
    /** resolve FX at the correction's own date instead of inheriting the
     *  original's pinned rate. Off by default: a correction to a EUR invoice is
     *  the same purchase transcribed better, so it must convert at the rate that
     *  invoice was pinned at. */
    own_fx?: boolean;
    lines?: Record<string, unknown>[];
  } = {},
): Promise<RunCostDocumentRow> {
  return request(`/api/run-documents/${docId}/correction`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export interface SupplyCoverageRow {
  lcsc: string;
  mpn: string;
  sources: string[];
  orders: string[];
  /** what the supplier says came out of OUR stock, so what we must have drawn */
  expected_from_pool: number;
  /** what the supplier supplied itself, billed inside the assembly fee */
  from_supplier: number;
  total: number;
  drawn: number;
  delta: number;
  supplier_mismatch: boolean;
  /** pieces this batch bought directly, outside the pool */
  bought_for_batch?: number;
  verdict:
    | "ok"
    | "no_draw"
    | "over_drawn"
    | "short"
    | "drawn_but_supplier_supplied"
    | "bought_for_batch_and_drawn"
    | "supplier_numbers_disagree";
}

export interface SupplyCoverage {
  run_id: number;
  /** false when no linked order has a cached supplier BOM — no verdict is made up */
  known: boolean;
  /** the double-supply half needs no supplier BOM and still ran */
  checked_without_bom: boolean;
  orders: string[];
  orders_without_bom: string[];
  rows: SupplyCoverageRow[];
  unexpected_draws: { lcsc: string; drawn: number }[];
  counts: Record<string, number>;
}

export interface BatchSupplyRow {
  key: string;
  lcsc: string;
  mpn: string;
  component_id: number | null;
  qty: number;
  amount: number;
  amount_usd: number;
  unit_usd: number | null;
  currency: string;
  suppliers: string[];
  lines: number[];
}

/** Parts bought straight for this batch, which never entered the shared pool. */
export function getBatchSupply(
  runId: number, signal?: AbortSignal,
): Promise<{ rows: BatchSupplyRow[] }> {
  return request(`/api/runs/${runId}/batch-supply`, { signal });
}

/** Is every part this batch used accounted for exactly once? The supplier's own
 *  BOM is the expectation (decision 0041). */
export function getSupplyCoverage(runId: number, signal?: AbortSignal): Promise<SupplyCoverage> {
  return request(`/api/runs/${runId}/supply-coverage`, { signal });
}

export interface SupplierBreakdown {
  ok: boolean;
  reason?: string;
  smt_order_code?: string;
  children: {
    lcsc: string; mpn: string; designator: string; source: string;
    qty_supplied: number; unit_price: number; amount: number;
    qty_from_pool: number; qty_total: number; loss: number;
    supplier_mismatch: boolean; price_checks: boolean;
  }[];
  parts_total?: number;
  printed_total?: number;
  residual?: number;
  reconciles?: boolean;
  mismatched_rows?: string[];
  price_check_failed?: string[];
}

/** What the supplier's own BOM says a parts lump bought. Reads only. */
export function getSupplierBreakdown(
  lineId: number, signal?: AbortSignal,
): Promise<SupplierBreakdown> {
  return request(`/api/run-cost-lines/${lineId}/supplier-breakdown`, { signal });
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
  /** the actual total in USD. The `total` beside it is in the project's DISPLAY
   *  currency, which is editable, so only this one can be compared against a
   *  batch's `closed_cost_usd` (decision 0044). */
  total_usd?: number | null;
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
  /** units that PASSED, derived from the device records when the batch has any
   *  (decision 0030) — the denominator of every per-device figure */
  qty_good: number | null;
  /** "devices" = counted from `produced` events; "typed" = the legacy field,
   *  or the boards ordered from JLC when that is empty too */
  qty_good_source?: "devices" | "typed";
  /** what is still stored on the run, for the legacy editor only */
  qty_good_typed?: number | null;
  /** What ONE device of this batch cost, over the devices recorded as produced.
   *  Null until it has device records — a cost divided by a PLANNED quantity is
   *  an estimate, and this figure is carried onto real orders.
   *
   *  It is the ONLY thing a batch contributes to a sale. Revenue and margin
   *  belong to the order; the two meet per unit (decision 0043). */
  per_device_cost: number | null;
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

/** A part FITTED on a batch where the design specifies another one.
 *
 *  Per batch and per designator. The design is never rewritten — the snapshot
 *  records what was specified, this records what went on the board. */
export interface RunSubstitution {
  /** what a READER should see: the library's manufacturer part number when the
   *  part is in the library, else exactly the string that was entered */
  specified_name?: string;
  fitted_name?: string;
  /** true when `*_name` came from the LIBRARY, so nothing may override it */
  specified_in_library?: boolean;
  fitted_in_library?: boolean;
  id: number;
  run_id: number;
  board: string;
  variant: string;
  designator: string;
  /** the supplier's own reference for the same position, when it differs */
  supplier_designator: string;
  specified_lcsc: string;
  specified_mpn: string;
  specified_component_id: number | null;
  fitted_lcsc: string;
  fitted_mpn: string;
  fitted_component_id: number | null;
  qty_per_device: number;
  /** WHO DECIDED: "supplier" — the factory changed it; "us" — we asked for it */
  source: string;
  /** WHO SUPPLIED it: "supplier" (their own shelf, billed inside the assembly
   *  fee, so no pool draw exists), "pool" (our consigned stock), or "both".
   *  Stored, never inferred from a missing draw — a part we supplied and never
   *  drew is a missing draw, and reading it the other way would hide it. */
  supplied_by: string;
  /** JLC's own word: "shop" | "preSale" | "preSaleAndShop" */
  supplier_source: string;
  evidence: string;
  note: string;
  /** false while the schematic still specifies the superseded part */
  design_updated: boolean;
  decided_by: string;
  decided_at: string | null;
}

/** A position the supplier's own BOM says changed, not yet recorded. */
export interface SubstitutionCandidate {
  run_id: number;
  run_label: string;
  project_id: number;
  order: string;
  batch: string;
  when: string;
  /** the supplier's reference — their stored BOM may use the board's older numbering */
  supplier_designator: string;
  /** the DESIGN's reference, recovered through the part the design still names */
  designator: string;
  specified_lcsc: string;
  specified_mpn: string;
  specified_component_id: number | null;
  fitted_lcsc: string;
  fitted_mpn: string;
  fitted_describe: string;
  qty_per_device: number;
  board: string;
  variant: string;
  /** JLC's own word: "update" means a human changed the line, "auto" means their
   *  matcher resolved the code we uploaded */
  match_type: string;
  supplier_source: string;
  /** "supplier" | "pool" | "both", derived from `supplier_source` */
  supplied_by: string;
  /** the superseded part is still in the latest snapshot — the actionable ones */
  still_in_design: boolean;
  evidence: string;
}

/** A recorded substitution whose design has not caught up — the standing
 *  finding that stops the superseded part being bought again. */
export interface SubstitutionDrift {
  substitution_id: number;
  run_id: number;
  run_label: string;
  project_id: number;
  designator: string;
  specified_lcsc: string;
  specified_mpn: string;
  fitted_lcsc: string;
  fitted_mpn: string;
  specified_still_held: number;
}

/** A design position this batch shows no sign of fitting: absent from the
 *  supplier's own BOM for the batch and from every draw. */
export interface UnusedPosition {
  lcsc: string;
  mpn: string;
  refs: string;
  qty_per_device: number;
}

export function getRunSubstitutions(
  runId: number,
  signal?: AbortSignal,
): Promise<{
  substitutions: RunSubstitution[];
  /** false when no supplier BOM is cached for the batch — then the absence of
   *  a part means nothing and `unused` is empty by construction */
  has_supplier_bom: boolean;
  unused: UnusedPosition[];
}> {
  return request(`/api/runs/${runId}/substitutions`, { signal });
}

export function addRunSubstitution(
  runId: number,
  body: {
    designator: string;
    fitted_lcsc?: string;
    fitted_mpn?: string;
    fitted_component_id?: number | null;
    specified_lcsc?: string;
    specified_mpn?: string;
    specified_component_id?: number | null;
    qty_per_device?: number;
    source?: string;
    supplied_by?: string;
    supplier_source?: string;
    supplier_designator?: string;
    evidence?: string;
    note?: string;
    design_updated?: boolean;
  },
): Promise<RunSubstitution & { batch_id: number }> {
  return request(`/api/runs/${runId}/substitutions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateRunSubstitution(
  subId: number,
  q: { design_updated?: boolean; note?: string },
): Promise<RunSubstitution> {
  const p = new URLSearchParams();
  if (q.design_updated !== undefined) p.set("design_updated", String(q.design_updated));
  if (q.note !== undefined) p.set("note", q.note);
  return request(`/api/substitutions/${subId}?${p.toString()}`, { method: "PUT" });
}

export function deleteRunSubstitution(subId: number): Promise<{ status: string }> {
  return request(`/api/substitutions/${subId}`, { method: "DELETE" });
}

export function getDetectedSubstitutions(
  signal?: AbortSignal,
): Promise<{ candidates: SubstitutionCandidate[]; drift: SubstitutionDrift[] }> {
  return request("/api/substitutions/detected", { signal });
}

/** Set how much of ONE part a batch used, as an ABSOLUTE figure — the
 *  end-of-production workflow. Idempotent: sending the same number twice
 *  changes nothing, and correcting it later is the same call, so a mistake
 *  never needs a compensating adjustment. Refuses a part JLC reported itself. */
export function setUsedQty(
  runId: number,
  body: { component_id?: number | null; mpn?: string; lcsc?: string; qty: number;
          consumed_at?: string; note?: string },
): Promise<{ status: "created" | "updated" | "removed" | "unchanged"; id?: number;
             qty: number; was?: number; unit_cost_usd?: number; basis?: string }> {
  return request(`/api/runs/${runId}/consumption/for-part`, {
    method: "PUT",
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

export function syncJlcStock(): Promise<{
  items: number;
  valued: number;
  synced_at: string;
  /** JLC's per-part movement ledger, fetched with the balance. */
  ledger?: JlcLedgerSync | { error: string };
}> {
  return request("/api/jlc/stock/sync", { method: "POST" });
}

export interface JlcLedgerSync {
  parts: number;
  rows_added: number;
  replays_to_balance: number;
  does_not_replay: string[];
  synced_at: string;
}

/** One movement in JLCPCB's OWN ledger for a consigned part. */
export interface JlcLedgerRow {
  changed_at: string;
  change_qty: number;
  qty_before: number;
  qty_after: number;
  paid_usd: number;
  business_code: string;
  business_type: number;
  /** JLC cancelled this movement — it states a quantity but nothing moved. */
  void: boolean;
  remark: string;
}

export interface JlcPartLedger {
  lcsc: string;
  mpn: string;
  rows: JlcLedgerRow[];
  balance: number;
}

/** A movement JLC recorded that the platform has no event for. */
export interface JlcUnexplainedRow {
  lcsc: string;
  mpn: string;
  changed_at: string;
  change_qty: number;
  qty_after: number;
  business_code: string;
  kind: "smt_order" | "parts_order" | "warehouse" | "other";
  paid_usd: number;
  remark: string;
}

/** A purchase WE booked that JLC's ledger never received — a cancelled lot. */
export interface JlcUnconfirmedLine {
  lcsc: string;
  parts_order: string;
  line_ids: number[];
  booked_qty: number;
  ledger_receipt_qty: number;
  missing_qty: number;
  usd: number;
}

export interface JlcLedgerBookable {
  change_key_id: number;
  lcsc: string;
  mpn: string;
  qty: number;
  date: string;
  business_code: string;
  remark: string;
}

export interface JlcLedgerReport {
  jlc_rows_we_cannot_explain: JlcUnexplainedRow[];
  our_lines_jlc_never_received: JlcUnconfirmedLine[];
  bookable: JlcLedgerBookable[];
  totals: {
    parts: number;
    ledger_rows: number;
    unexplained_rows: number;
    netted_out_rows: number;
    unconfirmed_lines: number;
    unconfirmed_qty: number;
  };
}

export function getJlcLedgerReport(signal?: AbortSignal): Promise<JlcLedgerReport> {
  return request("/api/jlc/stock/ledger", { signal });
}

export function getJlcPartLedger(lcsc: string, signal?: AbortSignal): Promise<JlcPartLedger> {
  return request(`/api/jlc/stock/ledger/${encodeURIComponent(lcsc)}`, { signal });
}

/** Write chosen ledger movements as uncharged draws. Dry run unless told. */
export function bookJlcLedgerRows(
  ids: number[],
  dryRun = true,
): Promise<{
  dry_run: boolean;
  written: (JlcLedgerBookable & { unit_cost_usd: number; usd: number })[];
  refused: (JlcLedgerBookable & { why: string })[];
  totals: { rows: number; qty: number; usd: number };
  batch_id?: number;
}> {
  const p = new URLSearchParams({ dry_run: String(dryRun) });
  if (ids.length) p.set("change_key_ids", ids.join(","));
  return request(`/api/jlc/stock/ledger/book?${p.toString()}`, { method: "POST" });
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
  /** written off — genuine attrition, and a defect signal */
  lost: number;
  /** consumed by ANOTHER project's assembly order. Not a loss, so it is kept off
   *  `lost`: counting the two together reported 1,094 written-off pieces when
   *  the real attrition was zero. */
  external: number;
  remaining_qty: number;
  /** what the pool said we had at the MOMENT JLC counted — `delta_qty` compares
   *  this against `held_qty`, because comparing today's pool against a snapshot
   *  measures elapsed time rather than disagreement */
  remaining_at_sync_qty: number;
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
  /** Where the part is used, from each project's latest READY snapshot — one
   *  entry per project AND board, since a component appears on several boards of
   *  one project under different reference designators. */
  projects: PartUsage[];
  project_count: number;
  /** Summed over the boards that use it: what ONE device of everything costs. */
  qty_per_device: number;
  /** How many devices the stock on hand covers — JLC's count for a consigned
   *  part, our own remainder for one JLC never sees. NULL when nothing uses it. */
  devices_coverable: number | null;
}

export interface PartUsage {
  project_id: number;
  project_name: string;
  board: string;
  refs: string;
  qty_per_device: number;
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
    /** the date every quantity comparison is made AS OF, in JLC's calendar */
    compared_as_of: string | null;
    /** stock events recorded after the snapshot — the count is that far behind */
    events_since_sync: number;
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
  /** What the INVOICE bills — PANELS when the order was panelised, never
   *  devices. Never multiply this by `panel_factor` and call the answer
   *  `implied_devices`: that is not where the backend gets it from. */
  jlc_number: number | null;
  /** Boards JLC ASSEMBLED (`allPatchNum`), in panels when panelised — what
   *  `implied_devices` is computed from. It equals the billed `jlc_number` on
   *  every order checked (46 of 46, 2026-09-24). */
  panels_assembled: number | null;
  /** Boards JLC FABRICATED for the order (`pasteNumber`). Larger than
   *  `panels_assembled` when only part of them was populated. */
  panels_fabricated: number | null;
  /** `allPatchNum`, or `pasteNumber` on a count cached before 2026-09-24 that
   *  the next sync has not re-read yet. */
  panels_source: string;
  panel_factor: number | null;
  /** Where `panel_factor` came from: JLC's own panelisation, our BOM vote, or
   *  a person's decision. "derived from the BOM" is true for ONE of the three. */
  panel_source: string;
  implied_devices: number | null;
  money_usd: number | null;
  presale_usd: number | null;
  consumed_value_usd: number | null;
  lot_count: number | null;
  part_count: number;
  proposed_outcome: "link_run" | "external" | "needs_human";
  /** "decided" once a decision is recorded — the proposal then restates it. */
  confidence: string;
  decided: boolean;
  /** A decision that was never applied has written NOTHING — no draw, no charge.
   *  Treating it as settled is what hid 441 consigned pieces for three weeks. */
  applied: boolean;
  /** JLC's own BOM is cached, so `componentSource` (who supplied each part) is known. */
  bom_fetched: boolean;
  /** What JLC itself reported, kept when a decision overrides `panel_factor`. */
  jlc_panel_factor: number | null;
  /** Parts JLC sourced from its own stock — not itemised, so the BOM vote is a floor. */
  jlc_sourced_usd: number | null;
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
    /** Decided but never applied — nothing written, and NOT a kind of "decided". */
    stranded: number;
    stranded_stock_value_usd: number;
    /** Orders whose JLC BOM was never fetched, so who supplied each part is unknown. */
    no_bom: number;
    no_bom_invoiced_usd: number;
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
  /** Batches JLC reports as cancelled — skipped, never invoiced, not an error. */
  cancelled: number;
  fee_info_fetched: number;
  /** Assembly-order BOMs cached this sync — evidence only, no money moves. */
  boms_fetched: number;
  /** Batches whose cached device count was re-read from `allPatchNum`. */
  panels_refreshed: number;
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

/** Re-state an imported parts order from what JLC says today — how a lot that
 *  was awaiting delivery becomes stock once it arrives. */
export function refreshJlcParts(
  pob: string,
  dryRun = true,
): Promise<{
  status: "dry_run" | "refreshed" | "unchanged" | "refused" | "not_imported";
  document_id: number | null;
  changes?: { line_id: number; lot_ref: string; was: Record<string, unknown>; now: Record<string, unknown> }[];
  /** Draws bound to a lot whose price changed, moved with it. */
  repriced_draws?: { consumption_id: number; run_id: number | null; lcsc: string; qty: number;
    lot_unit_was: number; lot_unit_now: number; delta_usd: number }[];
  blockers?: string[];
  batch_id?: number;
}> {
  return request(`/api/jlc/import/parts/${encodeURIComponent(pob)}/refresh?dry_run=${dryRun}`, {
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
  /** The signed-in person who ran it (decision 0050); older batches may say "user". */
  actor: string;
  user_id: number | null;
  /** Joins the batch to its rows in Admin → Activity. Null before 2026-09-24. */
  request_id: string | null;
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
  /** OUR lifecycle: `staged` until an apply stamps it `imported`. Left
   *  un-stamped by the 2026-07 backfill, which is why 37 rows read `staged`
   *  against 24 documents actually imported. */
  status: string;
  /** JLC's OWN status for the batch, from the order listing:
   *  `shipped` | `inProduction` | `cancelled` | `waitPay` | `waitReview`.
   *  Empty on a row synced before this was captured. */
  jlc_status: string;
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
  /** Paid lots JLC is still sourcing. They import as money awaiting delivery,
   *  never as stock, until a refresh sees them completed. */
  awaiting_lots: number;
  awaiting_usd: number;
  /** Lines on the imported document still marked awaiting delivery. */
  awaiting_on_document: number;
  /** The document is behind JLC: a lot it holds as awaiting has arrived, or
   *  JLC re-settled a lot's price (refund or supplement) since the import. */
  refresh_due: boolean;
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

/** The short form a version carries for a pinned set: enough to label a
 *  pill and link to the release. */
export interface FileSetRef {
  id: number;
  kind: string;
  label: string;
  fingerprint: string;
  file_count: number;
}

/** One file of a set, or one file a version pins — the same row either way.
 *  `set_id` is what the device URL names; there is no per-file version. */
export interface VersionFileRow {
  set_id: number;
  filename: string;
  kind: string;
  position: number;
  size_bytes: number;
  sha256: string;
  binary: boolean;
  blob_id: number;
  /** on a set's own listing: the newest older set of the same kind that
   *  carried this name, and whether the content is the same */
  previous?: { set_id: number; label: string; same: boolean } | null;
  /** on the entry endpoint: the text, or "" for a binary */
  content?: string;
}

/** A RELEASE: an immutable manifest of files, platform wide, identified by
 *  its fingerprint. `berryware` is what the device downloads; `artwork` is
 *  what the laser engraves (one drawing per set). Decision 0029. */
export interface FileSetRow {
  id: number;
  kind: string;
  label: string;
  fingerprint: string;
  comment: string;
  created_by: string;
  created_at: string | null;
  file_count: number;
  size_bytes: number;
  /** the manifest's names, in download order — an artwork set has one */
  filenames: string[];
  /** deployment versions pinning it — draft or published, current or not */
  used_by: number;
  /** deep form only */
  users?: FileSetUser[];
  files?: VersionFileRow[];
}

export interface FileSetUser {
  version_id: number;
  version_no: number;
  status: string;
  deployment: string;
  deployment_id: number;
  project: string;
  project_id: number;
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
  /** the berryware release and the artwork drawing this version pins */
  file_set: FileSetRef | null;
  artwork_set: FileSetRef | null;
  created_at: string | null;
  image_count: number;
  file_count: number;
  /** what the pinned files are, as one word for a label: "berryware",
   *  "artwork", "mixed" or "" when nothing is pinned */
  files_kind: string;
  step_count: number;
  /** true when the procedure has an `lte_sim_pin` step — the bench shows its
   *  SIM PIN box only then. */
  needs_sim_pin: boolean;
  /** present on the deep payloads */
  images?: DeploymentImageRow[];
  files?: VersionFileRow[];
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
  /** What this procedure is: "flash" | "test" | "mark". Decides which button
   *  the bench offers, so a rename cannot take the Test button away. */
  kind: string;
  /** On a TEST deployment: the DEFAULT for a NEW batch of this project. The
   *  rule itself lives on the batch and is copied onto every programming run,
   *  so changing this never re-judges devices already made. */
  active: boolean;
  /** The parameter set this deployment WORKS AGAINST — the default its next
   *  version inherits. It is not the authority for a run: each version pins its
   *  own set at creation and keeps it, so changing this never rewrites what a
   *  published version used. `-1` on a PATCH clears it; omitting it leaves it. */
  param_set_id: number | null;
  param_set_name: string | null;
  project_id: number;
  current_version_id: number | null;
  created_at: string | null;
  channels: DeploymentChannelRow[];
  versions: DeploymentVersionRow[];
  current?: DeploymentVersionRow;
}

export interface DeploymentVersionDetail extends DeploymentVersionRow {
  deployment: {
    id: number; name: string; chip: string; project_id: number;
    /** "flash" | "test" | "mark" — what an empty files card says is missing */
    kind: string;
    /** The deployment's CURRENT default set. A published version keeps the one
     *  it was made with, so these can differ and the card says when they do. */
    param_set_id: number | null;
  };
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
  files: (DiffSide<VersionFileRow> & { filename: string })[];
  file_set_before?: FileSetRef | null;
  file_set_after?: FileSetRef | null;
  artwork_set_before?: FileSetRef | null;
  artwork_set_after?: FileSetRef | null;
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
  images?: { firmware_asset_id: number; address: string }[];
  /** the sets to pin; null clears, undefined inherits (on compose) or leaves alone (on patch) */
  file_set_id?: number | null;
  artwork_set_id?: number | null;
  steps?: Record<string, unknown>[];
  param_set_id?: number | null;
  param_defaults?: Record<string, unknown> | null;
  transport_profile?: string;
  monitor_baud?: number;
  flash_config?: Record<string, string> | null;
}

/** One published version that needs a key from this set. */
export interface ParamUse {
  deployment: string;
  deployment_id: number;
  version_id: number;
  version_no: number;
}

export interface ParamSetRow {
  id: number;
  name: string;
  keys: string[];
  /** key -> the PUBLISHED versions that declare it. Removing a key listed here
   *  is refused by the server, which names the versions (decision 0024). */
  used_by: Record<string, ParamUse[]>;
  /** 0 = never edited since the revision log existed, not "revision zero". */
  revision_no: number;
  updated_by: string;
  updated_at: string | null;
}

/** One recorded edit. `changed` names the keys whose VALUE moved and stops
 *  there — a rotated secret must not outlive its rotation in a log. */
export interface ParamRevisionRow {
  id: number;
  revision_no: number;
  keys_added: string[];
  keys_removed: string[];
  changed: string[];
  values_public: Record<string, string>;
  /** False for a revision recorded before the values were kept — there is
   *  nothing to restore, and the page must not offer a button that would put
   *  an empty set over every parameter in the project. */
  restorable: boolean;
  note: string;
  updated_by: string;
  created_at: string | null;
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
  /** The transport profiles in full — baud, reset style, monitor signals. The
   *  bench keeps NO copy of these: a setting that decides what happens to a
   *  device lives on the platform, and a step's `baud` overrides the profile
   *  (decision 2026-09-17). */
  transports: Record<string, {
    label: string;
    before: "default_reset" | "usb_reset";
    flash_baud: number;
    monitor_signals: { dataTerminalReady: boolean; requestToSend: boolean } | null;
    reenumerates_on_reset: boolean;
  }>;
  /** Bauds a step may name. Anything else corrupts the transfer after the erase. */
  flash_bauds: number[];
  /** What a marking template says where the serial goes, when a step names
   *  nothing. */
  mark_placeholders: string[];
  /** The bounds the engine enforces on anything that goes ON a part. */
  serial_len: { min: number; max: number };
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
  /** Decision 0003: in_stock / shipped / returned / disposed, or "" for a device no batch has claimed. */
  state: string;
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

export interface DeviceRunBrief {
  id: number;
  status: string;
  /** flash | test | mark | erase */
  act: string;
  attempt_no: number;
  deployment: string | null;
  at: string | null;
}

export interface DeviceDetailPayload extends Omit<DeviceListRow, "batch" | "runs" | "checks"> {
  modem_fw: string;
  /** THE identity rows to draw, in order, label included. The page renders
   *  what it is given and hardcodes no field names: which rows exist depends on
   *  the PRODUCT (a Dongle_V2 has no modem), and the server decides from the
   *  project's procedures and its devices. */
  identity: { key: string; label: string; value: string }[];
  /** ONLY the values the last run to configure the device wrote. */
  configs: DeviceConfigRow[];
  config_run_id: number | null;
  /** how many earlier values exist and are not in `configs` */
  config_superseded: number;
  checks: RunCheckRow[];
  /** which run the grid above came from — the newest one, whatever its status */
  checks_run: {
    id: number;
    status: string;
    /** what that run WAS: flash (the config procedure) | test */
    act: string;
    attempt_no: number;
    started_at: string | null;
  } | null;
  /** Is this device programmed: the newest config run passed, an ACTIVE test
   *  passed after it, and nothing erased it since. Marking is never part of
   *  the answer. `reason` is a sentence, already written for the reader. */
  verdict: {
    programmed: boolean;
    requires_test: boolean;
    reason: string;
    config_run: DeviceRunBrief | null;
    test_run: DeviceRunBrief | null;
    erased_after: DeviceRunBrief | null;
  };
  /** What the MQTT broker says about this device RIGHT NOW — a different axis
   *  from `checks`, which is history the bench proved and cannot change.
   *  `null` means the broker has never been heard to mention this device: it
   *  may never have been deployed, or the monitor may be off. That is NOT the
   *  same as `online: false`, which is the broker saying the device is gone. */
  presence: DevicePresence | null;
  runs: ProgrammingRunSummary[];
}

/** One device as the fleet MQTT broker sees it. Every field is a cache of the
 *  newest message on that device's topic — see api/app/services/mqtt_monitor.py. */
export interface DevicePresence {
  topic: string;
  /** true = Online, false = Offline, null = an LWT we could not read. */
  online: boolean | null;
  lwt: string;
  /** ANY message from the device, so it survives a device that dropped off
   *  without publishing a clean "Offline". This is the honest "last online". */
  last_seen_at: string | null;
  last_online_at: string | null;
  last_offline_at: string | null;
  first_seen_at: string | null;
  temperature_c: number | null;
  temperature_at: string | null;
  wifi_ping_ms: number | null;
  inverter: string;
  inverter_sn: string;
  dongle_version: string;
  persist: Record<string, unknown> | null;
  persist_at: string | null;
  updated_at: string | null;
  /** The MAC the topic encodes, when it encodes one ("" for the 6-hex V2-era
   *  topics, which carry only the last three bytes). Shown so a mismatch
   *  against the programmed MAC is visible rather than silent. */
  mac_from_topic: string;
  /** The MAC the DEVICE ITSELF reported (stat/<id>/STATUS5 -> StatusNET.Mac).
   *  Stronger evidence than the topic, and empty until something asks a device
   *  for its status — the platform never asks. */
  reported_mac: string;
  /** Where in the payload it was found, e.g. "StatusNET.Mac". */
  reported_mac_field: string;
  reported_mac_at: string | null;
}

/** A device of one project, with the broker's view attached. */
export interface ProjectDeviceRow {
  id: number;
  tasmota_id: string;
  mac: string;
  serial: string;
  state: string;
  /** WHAT the device is, beside WHERE `state` says it is: ok | faulty |
   *  prototype | unidentified. Only `ok` may ship. */
  condition: string;
  last_status: string;
  production_run_id: number | null;
  /** {status: count} over every programming attempt on this device. */
  attempts: Record<string, number>;
  presence: {
    online: boolean | null;
    last_seen_at: string | null;
    last_online_at: string | null;
    temperature_c: number | null;
    wifi_ping_ms: number | null;
    inverter: string;
    inverter_sn: string;
    dongle_version: string;
  } | null;
}

export interface ProjectDevicesPayload {
  items: ProjectDeviceRow[];
  /** Counted over the WHOLE project, never over the filtered page. */
  summary: { total: number; online: number; offline: number; unknown: number };
  truncated: boolean;
}

/** With `runId` this is the BATCH's device list, and `summary` is scoped to it.
 *  A batch's devices are found by `DeviceUnit.production_run_id`, never by
 *  `programming_runs.production_run_id` — the run holds a copy of the same
 *  choice, and the copy is NULL on 6,139 of 6,443 rows. */
export function getProjectDevices(
  projectId: number,
  opts: { state?: string; condition?: string; runId?: number; presence?: string; q?: string } = {},
  signal?: AbortSignal,
): Promise<ProjectDevicesPayload> {
  const qs = new URLSearchParams();
  if (opts.state) qs.set("state", opts.state);
  if (opts.condition) qs.set("condition", opts.condition);
  if (opts.runId != null) qs.set("run_id", String(opts.runId));
  if (opts.presence) qs.set("presence", opts.presence);
  if (opts.q) qs.set("q", opts.q);
  const tail = qs.toString();
  return request(`/api/projects/${projectId}/devices${tail ? `?${tail}` : ""}`, { signal });
}

// ------------------------------------------------------------------ MQTT
// ADMIN ONLY. Every route below answers 403 to a non-admin. The broker
// password is never returned by the API — `password_set` is all there is, and
// an omitted `password` on save keeps the stored one (send "" to clear it).

export interface MqttConfigPayload {
  enabled: boolean;
  host: string;
  port: number;
  tls: boolean;
  username: string;
  password_set: boolean;
  flush_s: number;
  keepalive_s: number;
  client_id: string;
  updated_by: string;
  updated_at: string | null;
}

export interface MqttStatusPayload {
  monitor: {
    enabled: boolean;
    connected: boolean;
    host: string;
    started_at: string | null;
    connected_at: string | null;
    last_message_at: string | null;
    last_flush_at: string | null;
    messages: number;
    flushed: number;
    errors: number;
    last_error: string;
    subscriptions: string[];
  };
  configured: MqttConfigPayload;
  topics: number;
  online: number;
  offline: number;
  unlinked: number;
  /** Devices whose programmed MAC disagrees with the broker's. Never repaired
   *  automatically — a disagreement needs a person. */
  mac_mismatches: number;
}

export interface MacMismatchRow {
  device_id: number;
  topic: string;
  programmed_mac: string;
  broker_mac: string;
  /** "device_report" (the device answered a status query) or "mqtt_topic". */
  source: string;
  reported_mac_field: string;
  online: boolean | null;
  last_seen_at: string | null;
}

export function getMacMismatches(signal?: AbortSignal): Promise<{ items: MacMismatchRow[] }> {
  return request("/api/mqtt/mac-mismatches", { signal });
}

export interface MqttUnlinkedRow {
  topic: string;
  online: boolean | null;
  last_seen_at: string | null;
  first_seen_at: string | null;
  inverter: string;
  inverter_sn: string;
  dongle_version: string;
  mac_from_topic: string;
}

export function getMqttStatus(signal?: AbortSignal): Promise<MqttStatusPayload> {
  return request("/api/mqtt/status", { signal });
}

/** Omit `password` to keep the stored one; pass "" to clear it. */
export function saveMqttConfig(
  body: Partial<Omit<MqttConfigPayload, "password_set" | "updated_by" | "updated_at">> & {
    password?: string;
  },
): Promise<MqttConfigPayload & { restart_required: boolean; running: boolean }> {
  return request("/api/mqtt/config", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function getMqttUnlinked(signal?: AbortSignal): Promise<{ items: MqttUnlinkedRow[] }> {
  return request("/api/mqtt/unlinked", { signal });
}

/** Re-link presence rows AND fill missing device MACs. Never overwrites one. */
export function linkMqttDevices(): Promise<{ linked: number; macs_filled: number }> {
  return request("/api/mqtt/link", { method: "POST" });
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
  meta: { kind: string; chip?: string; build_label?: string; notes?: string },
): Promise<FirmwareAssetRow & { existing: boolean; chip_detected: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", meta.kind);
  if (meta.chip) form.append("chip", meta.chip);
  if (meta.build_label) form.append("build_label", meta.build_label);
  if (meta.notes) form.append("notes", meta.notes);
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
  body: { name: string; description?: string; chip?: string; param_set_id?: number },
): Promise<{ id: number }> {
  return request(`/api/flasher/projects/${projectId}/deployments`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function updateDeployment(
  id: number,
  body: {
    name: string; description?: string; chip?: string; kind?: string;
    active?: boolean; param_set_id?: number;
  },
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
  body: Omit<ComposeBody, "from_version_id" | "latest_files">,
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

/** Delete a DRAFT nothing has used, so discarding one leaves no trace. Refused
 *  for a published version, and for a draft any programming run records —
 *  `rejectDeploymentVersion` keeps that one as history instead. */
export function deleteDeploymentVersion(versionId: number): Promise<{ ok: boolean }> {
  return request(`/api/flasher/deployment-versions/${versionId}`, { method: "DELETE" });
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

/** Every set on the platform, newest first — optionally one kind. */
export function listFileSets(kind?: string, signal?: AbortSignal): Promise<FileSetRow[]> {
  return request(`/api/flasher/file-sets${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`, { signal });
}

export function getFileSet(setId: number, signal?: AbortSignal): Promise<FileSetRow> {
  return request(`/api/flasher/file-sets/${setId}`, { signal });
}

/** One file's text, for a preview or the LightBurn thumbnail. */
export function getFileSetEntry(
  setId: number,
  filename: string,
  signal?: AbortSignal,
): Promise<VersionFileRow & { content: string }> {
  return request(`/api/flasher/file-sets/${setId}/entries/${encodeURIComponent(filename)}`, { signal });
}

/** The bytes of one file of a set — what the device downloads and what the
 *  bench fetches to mark. Unauthenticated on purpose (the device sends no
 *  headers), so it needs no credentials to link to. */
export function fileSetFilePath(setId: number, filename: string): string {
  return `${API_URL}/api/flasher/files/${setId}/${encodeURIComponent(filename)}`;
}

/** Rename or annotate. The manifest is the identity and never changes — a
 *  different set of files is a different set (derive one). */
export function patchFileSet(
  setId: number,
  body: { label?: string; comment?: string },
): Promise<FileSetRow> {
  return request(`/api/flasher/file-sets/${setId}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function deleteFileSet(setId: number): Promise<{ ok: boolean; blobs_pruned: number }> {
  return request(`/api/flasher/file-sets/${setId}`, { method: "DELETE" });
}

export interface ImportedFile {
  filename: string;
  size_bytes: number;
  sha256: string;
  /** whether the bytes were new to the platform */
  state: "new" | "existing";
}

export interface FileSetImportResult {
  set: FileSetRow;
  /** false when the exact manifest already existed and was reused */
  created: boolean;
  files: ImportedFile[];
  changes: { replaced?: string[]; added?: string[]; removed?: string[]; borrowed?: string[] };
}

/** A whole folder or one file, the same path: unchanged bytes are reused
 *  and the manifest becomes a set — or finds the one that already exists.
 *  `kind: "artwork"` is what the marking step's upload asks for; the server
 *  refuses anything that is not a LightBurn file. */
export function importFileSet(
  files: File[],
  meta: { label?: string; comment?: string; kind?: string } = {},
): Promise<FileSetImportResult> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  if (meta.label) form.append("label", meta.label);
  if (meta.comment) form.append("comment", meta.comment);
  if (meta.kind) form.append("kind", meta.kind);
  return request(`/api/flasher/file-sets/import`, { method: "POST", body: form });
}

/** A new set from an existing one: swap or add files by upload, borrow files
 *  from any other set, leave some out. The base is untouched. */
export function deriveFileSet(
  setId: number,
  body: {
    files?: File[];
    remove?: string[];
    take?: { set_id: number; filename: string }[];
    label?: string;
    comment?: string;
  },
): Promise<FileSetImportResult> {
  const form = new FormData();
  for (const f of body.files ?? []) form.append("files", f);
  form.append("remove", JSON.stringify(body.remove ?? []));
  form.append("take", JSON.stringify(body.take ?? []));
  if (body.label) form.append("label", body.label);
  if (body.comment) form.append("comment", body.comment);
  return request(`/api/flasher/file-sets/${setId}/derive`, { method: "POST", body: form });
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

export function listParamSets(projectId: number, signal?: AbortSignal): Promise<ParamSetRow[]> {
  return request(`/api/flasher/projects/${projectId}/param-sets`, { signal });
}

export function listParamRevisions(
  paramSetId: number,
  signal?: AbortSignal,
): Promise<ParamRevisionRow[]> {
  return request(`/api/flasher/param-sets/${paramSetId}/revisions`, { signal });
}

/** Put the values back to what a revision left, as a NEW revision. History is
 *  append-only: reverting r5 to r2 writes r6 and the record still says r3-r5
 *  happened and that somebody undid them. */
export function revertParamSet(
  paramSetId: number,
  revisionNo: number,
  opts: { note?: string; force?: boolean } = {},
): Promise<{ id: number; revision_no: number; reverted_to: number }> {
  return request(`/api/flasher/param-sets/${paramSetId}/revert`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      revision_no: revisionNo, note: opts.note ?? "", force: opts.force ?? false,
    }),
  });
}

export function putParamSet(
  projectId: number,
  name: string,
  values: Record<string, string | number>,
  updatedBy = "",
  opts: { note?: string; force?: boolean } = {},
): Promise<{ id: number; revision_no: number }> {
  return request(`/api/flasher/projects/${projectId}/param-sets/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      values, updated_by: updatedBy,
      note: opts.note ?? "", force: opts.force ?? false,
    }),
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
  /** NO operator: the server stamps the run with the signed-in account. */
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

/** The broker password file for every device, or one project's. */
export function mosquittoExportPath(projectId?: number | null): string {
  const qs = projectId == null ? "" : `?project_id=${projectId}`;
  return `${API_URL}/api/flasher/mosquitto${qs}`;
}

/** ws:// (or wss://) address of a programming run's engine socket.
 *  Handles both API_URL shapes: an absolute origin (docker dev sets
 *  VITE_API_URL=http://localhost:8020) swaps http(s) for ws(s); a path
 *  prefix (deployed same-origin build) rides the page's own host. */
/** Download URL for the macOS profile that grants this origin serial access.
 *
 *  A plain <a href>, not a request(): the browser must fetch it itself so the
 *  file downloads, and so the API sees the bench's real Origin header — the
 *  profile is generated FOR that origin, and one written for the wrong address
 *  silently does nothing.
 */
export interface BenchRunIn {
  action: string;
  project_id: number;
  mac: string;
  chip: string;
  status: string;
  error?: string;
  station?: string;
  started_at?: string;
  log?: { dir: string; text: string }[];
  /** What the action produced — `{ marked: "D4E9F4F4DFD4" }` for a mark. */
  results?: Record<string, unknown>;
}

/** Record a bench action that ran no procedure — an erase, or a mark typed by
 *  hand — in the same history as the programming runs. Only called once a MAC
 *  is known: without one there is no device to attach it to. */
export const createBenchRun = (body: BenchRunIn) =>
  request<{ run_id: number; device_unit_id: number }>("/api/flasher/bench-runs", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const benchPolicyUrl = (): string => `${API_URL}/api/flasher/bench-policy.mobileconfig`;

/** The bench agent, as a zip the operator can expand and double-click. A
 *  plain <a href download> like the profile: the browser must fetch it itself
 *  so the API sees the bench's real Origin, which is baked into the launcher. */
export const benchAgentUrl = (): string => `${API_URL}/api/flasher/agent.zip`;

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
 * - `partial`    — checklist items are still unanswered.
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
  /** The named variant of `key` that this subject resolved to. Part of an
   *  exception's identity, so a waiver on the NMOS rule does not excuse the
   *  PNP one. */
  variant?: string;
  /** Answered by the RECORD for a judgment item, and by computed conformance
   *  for a machine one — the card merges the two for display and the shapes
   *  must match. Add a field here whenever `_detail` starts sending one: a
   *  type that is behind is how `superseded` stayed invisible for a week. */
  answered?: {
    /** `skipped` was retired 2026-09-13 and is read-only history. */
    result: "checked" | "na" | "skipped" | "failed" | "flagged";
    note: string | null;
    actor: string;
    actor_type: ReviewActor;
    at: string | null;
    /** The severity the check carried when this was answered. A `failed` at
     *  `warning` is worth seeing and does not fail the part. Absent on rows
     *  written before 2026-09-14, read as `error`. */
    severity?: "error" | "warning" | "ignore";
    /** Why it does not apply, as a code — `waived`, `feature_absent`, … */
    reason?: string | null;
    /** Set when a standing exception is what closed this item. The row offers
     *  no second exception while it holds. */
    exception_id?: number | null;
    /** The answer this one replaced, kept so accepting a flag never erases
     *  what was flagged. A real finding (flagged/failed) outlives any number
     *  of later routine re-checks. */
    superseded?: {
      /** `skipped` was retired 2026-09-13 and is read-only history. */
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
  /** `skipped` was retired 2026-09-13 and is read-only history. */
  result: "checked" | "na" | "skipped" | "failed" | "flagged";
  note?: string | null;
  /** The severity the check carried WHEN THIS WAS ANSWERED, stamped on the
   *  answer. Re-reading today's checklist instead would let an edit silently
   *  rewrite what a past record means — the same reason a record snapshots the
   *  list it was measured against. Absent on rows written before 2026-09-14,
   *  which are read as `error`. */
  severity?: "error" | "warning" | "ignore";
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
  /** Failures of WARNING-severity checks. Worth seeing; they do not make the
   *  subject failed, which is what lets a new check ship at all. */
  warnings?: number;
  /** Judgment items a standing exception closes. They LEAVE the denominator —
   *  `total` does not include them — because an exception says the question is
   *  not about this part, never that somebody looked. Reported on its own so a
   *  part closed by exceptions never reads like a part that was judged. */
  excused?: number;
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
  /** Checks the owner switched OFF for this subject in the checklist. Not run,
   *  not measured, and not work for anybody — shown so "why is this not
   *  checked" has an answer on the card. */
  switched_off?: { key: string; text: string; machine: boolean }[];
  /** Not switched off — not about parts like this one. Its `when` predicate
   *  did not match. A different statement, and never shown as the other. */
  inapplicable?: { key: string; text: string; when: Record<string, string> }[];
  /** Standing decisions in force on this subject. Reported even when stale,
   *  with the reason — an exception that has quietly stopped applying is
   *  exactly what somebody needs to see. */
  exceptions?: ReviewException[];
  record: ReviewRecordRow | null;
  history: ReviewRecordRow[];
  blocked_items?: string[];
}

export function getReviewDetail(kind: ReviewKind, id: number, signal?: AbortSignal): Promise<ReviewDetail> {
  return request(`/api/reviews/${kind}/${id}`, { signal });
}

export interface ReviewCheckAnswer {
  key: string;
  /** "flagged" = verified and found wrong, recorded without fixing — note required.
   *  An item nobody could verify is LEFT UNANSWERED; there is no "skipped".
   *
   *  `na` is still ACCEPTED by the API and is how an agent says "does not
   *  apply", but it is no longer stored as an answer: since 2026-09-14 the
   *  backend converts it into a standing exception pinned to the drawing (or,
   *  for a component, to its own fields), so it needs a `reason` AND a `note`
   *  and it outlives the version. The review card does not send it — it calls
   *  `grantReviewException` directly, where the scope can be asked. */
  result: "checked" | "na" | "flagged";
  note?: string;
  /** Required for a key the checklist does not define (a custom check added
   *  for this part alone): the record is the only place that wording lives. */
  text?: string;
  /** `na` only, and REQUIRED there above the machine tier: which way the item
   *  does not apply ("feature_absent", "kind_exempt", "waived", "other"). It
   *  becomes the exception's reason, so the health tab can aggregate it
   *  instead of re-reading free text. */
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
  /** The facts under the one-word state. `conforms: null` means the automatic
   *  checks have not been worked out for this version yet — never "conforms".
   *  `judged`/`judged_of` counts JUDGMENT items only; an excused item leaves
   *  the denominator, because an exception says the question is not about this
   *  subject, never that somebody looked. */
  conforms: boolean | null;
  judged: number;
  judged_of: number;
  excused: number;
  warnings: number;
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
  /** The facts under the one-word state. `conforms: null` means the automatic
   *  checks have not been worked out for this version yet — never "conforms".
   *  `judged`/`judged_of` counts JUDGMENT items only; an excused item leaves
   *  the denominator, because an exception says the question is not about this
   *  subject, never that somebody looked. */
  conforms: boolean | null;
  judged: number;
  judged_of: number;
  excused: number;
  warnings: number;

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
  top_na_items: { key: string; count: number }[];
  /** WHICH WAY items do not apply, from the reason code `na` carries. */
  na_reasons: { reason: string; count: number }[];
  /** Retired 2026-09-13, still counted: items answered `skipped` on an older
   *  record, which now read as unanswered and are real open work. */
  legacy_skipped_items: { key: string; count: number }[];
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

export type CheckParamValue = number | boolean | string | string[] | Record<string, string>;

export interface ChecklistItem {
  key: string;
  text: string;
  hint?: string;
  machine?: boolean;
  /** What this automatic check measures against, on the check that uses it.
   *  Versioned with the checklist and snapshotted into the review record, so a
   *  past verification says what it was measured against. The item's `text` is
   *  written from these, so the sentence and the comparison cannot disagree.
   *  The DEFAULT's type is the parameter's type: a positive number, a switch,
   *  a name, a list of property names, or property -> regular expression. */
  params?: Record<string, CheckParamValue>;
  /** Which subjects this check is ABOUT. Every entry must match (AND), each
   *  value a regular expression over one fact. A bare name is a component
   *  property (`comp_type`); a `$` name is a structural fact
   *  (`$category`, `$base_symbol`, `$purchasable`, …). An item whose predicate
   *  a part does not satisfy is not expected of it at all — which is NOT the
   *  same as being switched off, and the card says which. */
  when?: Record<string, string>;
  /** Several items may share a key only as distinct NAMED variants. The name is
   *  the variant's identity — stable under reordering, unlike a list index —
   *  and its label: the Scope column reads `Transistors.NMOS` from it. A key
   *  with variants must split on ONE field with distinct literal values plus at
   *  most one variant with no `when` (the fallback), which is what lets
   *  resolution avoid an ordering rule and a sorted table avoid lying about
   *  precedence. */
  variant?: string;
  /** A DECLARATIVE check: one fact, one assertion. The validator answers any
   *  item carrying it, whatever its key — the second door to `machine: true`,
   *  since an author-chosen key cannot be in `validator.MACHINE_KEYS`. Its
   *  `text` is generated from it, so the sentence cannot disagree with the
   *  rule. The ceiling is deliberate: one assertion, no booleans, no arithmetic
   *  between facts. Needing more means it has become a rules language. */
  assert?: {
    fact: string;
    one_of?: string[];
    matches?: string;
    equals?: string;
    at_least?: number;
    at_most?: number;
    present?: boolean;
  };
  /** What a FAILURE of this check means, and — at `ignore` — whether it runs
   *  here at all. One control with three values, not a switch beside a
   *  severity. It applies at this level AND BELOW, which is how a category list
   *  says a base check does not apply to its parts; the merge is otherwise
   *  additive. `error` is the default and is not stored. */
  severity?: "error" | "warning" | "ignore";
  /** Retired spelling of `severity: "ignore"`, still READ on rows written
   *  before 2026-09-14. Never written. */
  disabled?: boolean;
}

export interface ChecklistDetail {
  id: number;
  name: string;
  subject_kind: ReviewKind;
  category_id: number | null;
  description: string;
  version_no: number | null;
  items: ChecklistItem[];
  /** What a category-scoped list inherits from the lists above it, each item
   *  tagged with the list it came from. Empty for a base list. */
  inherited: (ChecklistItem & { from: string })[];
  history: { version_no: number; created_at: string; created_by: string; comment: string | null; item_count: number }[];
}

/** One editing SCOPE — a (kind, category) pair — whether or not a checklist row
 *  exists for it yet. The editor is three sidebar entries and a category
 *  picker, so a category that has never stated anything still has to show what
 *  it inherits; the row is created on the first save, not by opening a
 *  dropdown. */
export interface ChecklistScope {
  id: number | null;
  name: string;
  subject_kind: ReviewKind;
  category_id: number | null;
  category_path: string | null;
  description: string;
  version_no: number | null;
  items: ChecklistItem[];
  inherited: (ChecklistItem & { from: string })[];
  /** False when this scope states nothing yet. */
  exists: boolean;
  history: ChecklistDetail["history"];
}

/** Every scope with the items it STATES — the one-table editor's data. Not the
 *  cross product of every check with every scope: a category contributes only
 *  what it changes, which is also the answer to "what does this category do
 *  differently". */
export interface ChecklistScopeRows {
  scopes: {
    id: number;
    name: string;
    subject_kind: ReviewKind;
    category_id: number | null;
    category_path: string | null;
    version_no: number | null;
    items: ChecklistItem[];
  }[];
}

/** How the live parts in a scope fall across one key's variants. A non-zero
 *  `no_match` on a settled category means the discriminator is not reliable —
 *  `comp_type` is free text and already carries a misspelling — and that
 *  category wants a subcategory rather than a predicate. */
export interface VariantCoverage {
  key: string;
  category_id: number | null;
  total: number;
  counts: { variant: string; count: number }[];
  no_match: number;
}

export function getChecklistCoverage(
  kind: ReviewKind,
  key: string,
  categoryId: number | null,
  signal?: AbortSignal,
): Promise<VariantCoverage> {
  const q = categoryId === null ? "" : `&category_id=${categoryId}`;
  return request(`/api/checklists/coverage?kind=${kind}&key=${encodeURIComponent(key)}${q}`, {
    signal,
  });
}

export function getAllChecklists(signal?: AbortSignal): Promise<ChecklistScopeRows> {
  return request("/api/checklists/all", { signal });
}

export function getChecklistScope(
  kind: ReviewKind,
  categoryId: number | null,
  signal?: AbortSignal,
): Promise<ChecklistScope> {
  const q = categoryId === null ? "" : `&category_id=${categoryId}`;
  return request(`/api/checklists/scope?kind=${kind}${q}`, { signal });
}

/** Publish this scope's checklist, creating it if it is the first thing the
 *  scope has stated. Saving an EMPTY list on a category DELETES the row — "adds
 *  nothing" and "has an empty list" must not be two states. */
export function saveChecklistScope(
  kind: ReviewKind,
  categoryId: number | null,
  items: ChecklistItem[],
  comment?: string,
  description?: string,
): Promise<ChecklistScope> {
  return request("/api/checklists/scope", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({
      kind,
      category_id: categoryId,
      items,
      comment: comment ?? null,
      description: description ?? null,
    }),
  });
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
  /** The CATALOGUE of automatic checks — `validator.MACHINE_CHECKS`. The
   *  validator owns an automatic check's wording, so the editor renders these
   *  read-only with an on/off switch, and the API rewrites the stored text from
   *  here on every save. */
  machine_checks: Record<
    string,
    {
      key: string;
      text: string;
      hint?: string;
      /** Present only for a check that takes settings. */
      params?: Record<string, CheckParamValue>;
      /** `services/validator.py`'s own values, so a changed one shows as changed. */
      defaults?: Record<string, CheckParamValue>;
    }[]
  >;
  /** The fact vocabulary, per subject kind — what a `when` predicate or an
   *  `assert` may name besides a component property. The editor held its own
   *  copy of this list until 2026-09-14, which is how a fact could exist in
   *  the backend and be unselectable in the UI. */
  facts: Record<string, ChecklistFact[]>;
  /** The assertions a declarative check may make, from the validator. */
  assertions: string[];
}

/** One entry in the fact vocabulary. `$`-prefixed, unlike a component property,
 *  so a misspelling is REFUSED on save instead of silently matching nothing. */
export interface ChecklistFact {
  name: string;
  /** One line saying what it reads. Shown beside the name in the picker. */
  what: string;
  /** Which subject kinds carry it. */
  kinds: string[];
  /** True when it is computed from a drawing on demand rather than read off
   *  the row. Costs nothing until a check names it. */
  lazy?: boolean;
}

export function getChecklistMeta(signal?: AbortSignal): Promise<ChecklistMeta> {
  return request("/api/checklists/meta", { signal });
}

export interface ResolvedChecklist {
  kind: ReviewKind;
  category_id: number | null;
  /** `from` names the checklist an item came from — the base one, or the
   *  category-scoped list that overrode it. */
  items: (ChecklistItem & { from: string })[];
  /** Switched off somewhere on the path — shown, not hidden, so "why does this
   *  part not get that check" is answerable from the same screen. */
  disabled: (ChecklistItem & { from: string })[];
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

export interface ComponentRuleSet {
  required_properties?: string[] | null;
  non_empty_properties?: string[] | null;
  manufacturer_properties?: string[] | null;
  property_patterns?: Record<string, string> | null;
}

export interface ComponentRules {
  category_id: number | null;
  /** What a component in this scope is actually measured against. */
  effective: ComponentRuleSet;
  /** What it would be if this scope stated nothing — the parent category, or
   *  the library-wide block. */
  inherited: ComponentRuleSet;
  /** What THIS scope states for itself. A key absent here is inherited. */
  own: ComponentRuleSet;
  has_row: boolean;
}

/** The property rules a component is measured against, for one scope. Omit the
 *  category for the library-wide block every category starts from. */
export function getComponentRules(
  categoryId: number | null,
  signal?: AbortSignal,
): Promise<ComponentRules> {
  const q = categoryId === null ? "" : `?category_id=${categoryId}`;
  return request(`/api/component-rules${q}`, { signal });
}

/** A key sent as `null` stops being stated at this scope, so it inherits again.
 *  A key sent as a value REPLACES the whole list for this scope. */
export function saveComponentRules(
  categoryId: number | null,
  body: ComponentRuleSet,
): Promise<ComponentRules> {
  return request("/api/component-rules", {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ ...body, category_id: categoryId }),
  });
}


/** A standing decision that one check does not apply to this subject.
 *
 *  The durable half of an `na` answer: answering `na` closes the item on ONE
 *  version, and a pad move takes it with it. An exception outlives the version
 *  and dies only when it is revoked or when a fact it NAMED changes. */
export interface ReviewException {
  id: number;
  subject_kind: ReviewKind;
  subject_id: number;
  key: string;
  variant: string | null;
  reason: string;
  note: string;
  evidence: string | null;
  /** The facts it was granted against, `{fact: value}`. Empty means "this part,
   *  always"; `{$material_sha: …}` means "this drawing only". */
  depends_on: Record<string, string>;
  scope: string;
  created_by: string;
  actor_type: ReviewActor;
  created_at: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
  revoke_reason: string | null;
  /** Why it no longer applies, or null while it holds. */
  stale_reason: string | null;
}

export function listReviewExceptions(
  kind: ReviewKind,
  id: number,
  signal?: AbortSignal,
): Promise<ReviewException[]> {
  return request(`/api/reviews/${kind}/${id}/exceptions`, { signal });
}

/** `scope`: "drawing" pins the material fingerprint and dies when the copper
 *  moves; "always" pins nothing and is a decision about the part itself. The
 *  choice is asked rather than inferred — a blanket waiver silently covering a
 *  future edit is the failure this is designed to prevent.
 *
 *  `pin` overrides the preset with an explicit fact list, for the case neither
 *  fits. A COMPONENT is the case: its `$material_sha` is the symbol's and the
 *  footprint's, so "while the drawing is unchanged" says nothing about the
 *  component's own fields — `["$property_sha"]` is what pins those. */
export function grantReviewException(
  kind: ReviewKind,
  id: number,
  body: { key: string; reason: string; note: string; scope?: "drawing" | "always";
          pin?: string[]; variant?: string; evidence?: string },
): Promise<ReviewDetail & { exception: ReviewException }> {
  return request(`/api/reviews/${kind}/${id}/exceptions`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/** One standing exception, with the subject it is on. The register's row. */
export interface ReviewExceptionRow extends ReviewException {
  subject_name: string | null;
  /** The subject has been deleted. The row is still reported: a decision with
   *  nothing left to apply to is exactly what a register exists to surface. */
  subject_gone: boolean;
}

/** Every standing decision in the library. An exception was visible only on its
 *  own subject's card until 2026-09-14, so nothing could answer "what have we
 *  excused, and does it still hold". */
export function listAllReviewExceptions(
  includeRevoked = false,
  signal?: AbortSignal,
): Promise<ReviewExceptionRow[]> {
  return request(`/api/reviews/exceptions?include_revoked=${includeRevoked}`, { signal });
}

/** Every subject one check currently fails. The health panel groups failures by
 *  KEY because that is the work plan — "fp.model3d on 61 footprints" is one job
 *  and "218 failed parts" is a wall — and this is what a number opens. */
export interface FailingSubjects {
  kind: ReviewKind;
  key: string;
  subjects: {
    id: number;
    name: string;
    kind: ReviewKind;
    note: string | null;
    severity: "error" | "warning" | "ignore";
    text: string;
    variant: string | null;
  }[];
}

export function getFailingSubjects(
  kind: ReviewKind,
  key: string,
  signal?: AbortSignal,
): Promise<FailingSubjects> {
  return request(`/api/reviews/failing/${kind}/${encodeURIComponent(key)}`, { signal });
}

export function revokeReviewException(
  kind: ReviewKind,
  id: number,
  excId: number,
  reason: string,
): Promise<ReviewDetail> {
  return request(
    `/api/reviews/${kind}/${id}/exceptions/${excId}?reason=${encodeURIComponent(reason)}`,
    { method: "DELETE" },
  );
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
  return (await fetchSvgUnits(path, signal)).text;
}

/** The same render, plus how many units the symbol has.
 *
 *  `X-Unit-Count` is set by every symbol render (routers/libraries.py) and
 *  listed in the API's CORS `expose_headers` — without that listing a
 *  cross-origin dev browser is handed `null` here and every multi-unit symbol
 *  silently loses its pager in dev while keeping it in production. Anything
 *  that is not a symbol simply reports 1. */
export async function fetchSvgUnits(
  path: string,
  signal?: AbortSignal,
): Promise<{ text: string; units: number }> {
  const res = await fetch(`${API_URL}${path}`, { credentials: "include", signal });
  if (!res.ok) throw new ApiError(res.status, `render failed (${res.status})`);
  const units = Number(res.headers.get("X-Unit-Count") ?? "1");
  return { text: await res.text(), units: Number.isFinite(units) && units > 0 ? units : 1 };
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
  /** How much is DRAWN here. A harness root is SPICE text and one sheet box,
   *  so these decide which sheet is worth opening. */
  symbols: number;
  wires: number;
  directives: number;
  error?: string;
}

/** A KiCad project inside one commit, and whether it is a simulation
 *  harness — a design repository keeps one `_sim` project per block. */
export interface SimProject {
  board: string;
  simulation: boolean;
  directives: number;
  has_schematic: boolean;
}

export async function getSimProjects(
  snapshotId: number,
  signal?: AbortSignal,
): Promise<{ projects: SimProject[] }> {
  return request(`/api/sim/snapshot/${snapshotId}/projects`, { signal });
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
  /** Every field on the placement, hidden ones included — what the part says
   *  about itself. The part dialog shows it. */
  props: { k: string; v: string }[];
  at: number[];
  angle: number;
  bbox: number[] | null;
  power: boolean;
  sim: Record<string, string>;
  /** What `alter` has to be given to change this part while it runs. Usually
   *  the reference, but `Sim.Device` prefixes it — a switch drawn `SW1` is
   *  `rsw1` in the netlist. */
  spice: string;
  index: number;
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
  /** Everything needed to DRAW the sheet, from the same parse as the nets. */
  draw: SheetDrawing;
  wires: (SimWire & { group: string })[];
  junctions: { at: number[]; net: string | null; group: string }[];
  labels: { id: string; text: string; kind: string; at: number[]; net: string | null }[];
  pins: SimPin[];
  symbols: SimSymbol[];
  subsheets: { name: string; file: string; uuid: string; at: number[]; size: number[] }[];
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

export interface SimTextItem {
  id: string;
  kind: "control" | "analysis" | "stimulus" | "note";
  title: string;
  text: string;
  at: number[];
  /** How many PASS/FAIL lines the block prints, for a `.control`. */
  checks?: number;
}

export interface SimScenarios {
  scenarios: SimTextItem[];
  analyses: SimTextItem[];
  stimulus: SimTextItem[];
  notes: SimTextItem[];
  analysis_forms: unknown[];
}

/** What the harness offers to run, read off its own text items. */
export async function getSimScenarios(
  src: SimSourceRef,
  signal?: AbortSignal,
): Promise<SimScenarios> {
  return request(`${simBase(src)}/scenarios`, { signal });
}

/** The parts a schematic drawn in the browser starts with, with the graphics
 *  to draw each one. */
export async function getSimPalette(signal?: AbortSignal): Promise<{
  parts: PaletteEntry[];
  libs: Record<string, LibSymbol>;
  switch: { open: string; closed: string; open_r: string; closed_r: string };
}> {
  return request("/api/sim/palette", { signal });
}

/** Save a drawn schematic. It becomes an ordinary upload source, so the
 *  circuit runs through the same pipeline as one drawn in KiCad — and `sch`
 *  is the real `.kicad_sch`, which is what the user downloads. */
export async function saveSketch(
  doc: SchDoc,
  /** Rewrite this sketch in place. The editor saves on every pause in typing,
   *  and a new source per keystroke would fill the disk and move the address
   *  bar under the user. */
  id = "",
  signal?: AbortSignal,
): Promise<{ id: string; root: string; files: string[]; sch: string }> {
  return request(`/api/sim/sketch${id ? `?id=${encodeURIComponent(id)}` : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(doc),
    signal,
  });
}

/** The document a sketch was drawn from — 404 when the source came from
 *  KiCad rather than the editor. */
/** The worked example, saved as an ordinary sketch. An empty sheet teaches
 *  nothing, and the parts that carry a model are the ones nobody guesses how
 *  to wire. */
export async function openSimExample(
  signal?: AbortSignal,
): Promise<{ id: string; root: string; files: string[]; sch: string }> {
  return request("/api/sim/example", { method: "POST", signal });
}

export async function getSketch(uploadId: string, signal?: AbortSignal): Promise<SchDoc> {
  return request(`/api/sim/upload/${encodeURIComponent(uploadId)}/sketch`, { signal });
}

/** Where a run named by `job` has got to.
 *
 *  ngspice says so itself: during a transient it prints the simulated time it
 *  has reached, and the process that owns it records that. A verdict harness
 *  solves the same transient TWICE — once for the rawfile, once for the
 *  `meas` verdicts — so `sweep`/`sweeps` say which pass this is and the
 *  `fraction` already spans both.
 *
 *  An empty object is NO NEWS, never a failure: a run that has not reached
 *  the solver, or one whose record has expired. */
export interface SimProgress {
  phase?: "netlisting" | "solving" | "reading" | "done" | "failed";
  fraction?: number;
  /** Simulated seconds reached, and the transient's stop time. */
  t?: number;
  tstop?: number | null;
  sweep?: number;
  sweeps?: number;
  /** Wall-clock seconds since the run was first heard from. */
  elapsed?: number;
}

export async function getSimProgress(job: string, signal?: AbortSignal): Promise<SimProgress> {
  return request(`/api/sim/progress/${encodeURIComponent(job)}`, { signal });
}

/** The schematic colours. Read from the same theme file kicad-cli renders
 *  the project's schematic tab with, so both views agree. */
export async function getSimTheme(signal?: AbortSignal): Promise<{ name: string; schematic: SchTheme }> {
  return request("/api/sim/theme", { signal });
}

/** Run one scenario. The answer is the binary 7SIM payload, not JSON —
 *  thousands of points across a dozen vectors are float arrays, and that is
 *  what the plotter wants. Decode it with `decodeSimPayload`.
 *
 *  A run has no sheet: it is always the whole project from its root, so the
 *  harness that a `_sim` project wraps around a block goes with it. */
export async function runSimulation(
  src: SimSourceRef,
  body: { control?: string | null; analysis?: string; timeout?: number; job?: string },
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

// ---------------------------------------------------------------- field solver
// 2D quasi-TEM solver for PCB transmission lines (api/app/routers/field_solver.py).

export interface FsLayer {
  type: "copper" | "dielectric";
  name?: string;
  label?: string;
  material?: string | null;
  thickness_mm: number;
  eps_r?: number;
  tand?: number;
  /** Copper weight where the fab publishes it ("1oz"). Never derived from thickness:
   *  an etched half-ounce inner measures 0.0152 mm and would round to the wrong one. */
  weight?: string;
}

export interface FsStackup {
  id: string;
  name: string;
  manufacturer: string;
  source: string;
  verified: boolean;
  builtin: boolean;
  /** The mask MATERIAL id, or null for a stackup built without one. The coating
   *  geometry is not here — it lives in `mask_geom`. The type used to claim an object
   *  with the geometry inlined, which no endpoint has ever sent: the editor read
   *  fields that did not exist (empty boxes) and wrote an object back where the server
   *  expects an id. */
  soldermask: string | null;
  finish: { type: string; thickness_um: number; assumed?: boolean } | null;
  layers: FsLayer[];
  total_mm: number;
  mask_geom: Record<string, number>;
  /** The outer layers PER FACE. `soldermask`, `finish` and `silkscreen` above are the
   *  TOP face, kept because the solver only ever coats the top. */
  faces?: {
    top?: { silkscreen?: unknown; soldermask?: string | null; finish?: FsStackup["finish"] };
    bottom?: { silkscreen?: unknown; soldermask?: string | null; finish?: FsStackup["finish"] };
  };
  silkscreen?: unknown;
  /** The drawable top-to-bottom row list, built by the same code as the comparison. */
  stack: FsStackRow[];
}

export interface FsMaterial {
  id: string;
  name: string;
  manufacturer: string;
  /** What it IS: "dielectric" or "conductor". */
  kind: string;
  /** Where it may be PUT: "laminate", "soldermask", "conductor", "ambient". A mask
   *  and air are both dielectrics and neither belongs in a stackup gap. */
  use: string;
  source: string;
  points: { f_hz: number; dk: number; tand: number; tand_assumed?: boolean }[];
}

export interface FsRuleSet {
  id: string;
  name: string;
  builtin: boolean;
  manufacturer?: string;
  source?: string;
  via_sizes?: { name: string; hole: number; pad: number }[];
  [key: string]: unknown;
}

export interface FsFinish {
  type: string;
  thickness_um: number;
  source: string;
}

/** One conductor or dielectric outline of the solved cross-section, in mm. */
export interface FsRegion {
  points: [number, number][];
  kind: string;
  name: string;
  role?: string;
  eps?: number;
}

export interface FsGeometry {
  regions: FsRegion[];
  overlays?: { points: [number, number][]; kind: string }[];
  xmin: number;
  xmax: number;
  ymin: number;
  ymax: number;
  notes: string[];
}

export interface FsField {
  nodes: [number, number][];
  tris: [number, number, number][];
  phi: number[];
  phi_air: number[];
  region_of: number[];
  conductor_of: number[];
  i_signal: number;
}

export interface FsSummary {
  Z0?: number | null;
  eps_eff?: number;
  delay_ps_per_mm?: number;
  alpha_db_m?: number;
  alpha_c_db_m?: number;
  alpha_d_db_m?: number;
  Zdiff?: number;
  Zodd?: number;
  Zeven?: number;
  Zcomm?: number;
  Z0_single?: number | null;
  coupling_k?: number;
  eps_eff_odd?: number;
  eps_eff_even?: number;
  delay_odd_ps_per_mm?: number;
  alpha_odd_db_m?: number;
  alpha_odd_c_db_m?: number;
  alpha_odd_d_db_m?: number;
}

export interface FsSweepPoint {
  f: number;
  modes: {
    eps_eff: number;
    alpha_db_m: number;
    alpha_c_db_m: number;
    alpha_d_db_m: number;
    z: Record<string, number | null>;
    v: number[];
  }[];
}

export interface FsResult {
  design: { C: number[][]; L: number[][] };
  summary: FsSummary;
  sweep: FsSweepPoint[];
  C0: number[][];
  mesh: { nodes: number; elements: number };
  notes: string[];
  geometry: FsGeometry;
  field?: FsField;
}

export interface FsFrame {
  f: number;
  phi: number[];
  i_signal: number;
  z?: number;
  eps_eff?: number;
  alpha_db_m?: number;
}

export interface FsSearchRow {
  w: number;
  s: number | null;
  gap: number | null;
  fence_distance: number | null;
  via_rows: number[] | null;
  soldermask: boolean;
  dev_pct: number;
  within: boolean;
  eps_eff?: number;
  alpha_db_m?: number;
  alpha_odd_db_m?: number;
  Zodd?: number;
  [key: string]: unknown;
}

export interface FsSearchResult {
  key: string;
  target: number;
  tolerance_pct: number;
  step: number | null;
  rows: FsSearchRow[];
  note: string;
}

export interface FsJobStatus {
  id: string;
  kind: string;
  state: "running" | "done" | "error" | "cancelled";
  message: string;
  fraction: number;
  phase?: string;
  error?: string;
  partial_no?: number;
  frames_f?: number[];
  result?: unknown;
  frames?: FsFrame[];
}

const fsJson = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export function fsMaterials(signal?: AbortSignal): Promise<FsMaterial[]> {
  return request("/api/fieldsolver/materials", { signal });
}

export function fsStackups(signal?: AbortSignal): Promise<FsStackup[]> {
  return request("/api/fieldsolver/stackups", { signal });
}

export function fsSaveStackup(body: unknown): Promise<FsStackup> {
  return request("/api/fieldsolver/stackups", fsJson(body));
}

export function fsDeleteStackup(id: string): Promise<{ ok: boolean }> {
  return request(`/api/fieldsolver/stackups/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function fsRules(signal?: AbortSignal): Promise<FsRuleSet[]> {
  return request("/api/fieldsolver/rules", { signal });
}

export function fsSaveRules(body: unknown): Promise<FsRuleSet> {
  return request("/api/fieldsolver/rules", fsJson(body));
}

export function fsDeleteRules(id: string): Promise<{ ok: boolean }> {
  return request(`/api/fieldsolver/rules/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function fsFinishes(signal?: AbortSignal): Promise<FsFinish[]> {
  return request("/api/fieldsolver/finishes", { signal });
}

export function fsGeometry(params: unknown, signal?: AbortSignal): Promise<FsGeometry> {
  return request("/api/fieldsolver/geometry", { ...fsJson(params), signal });
}

export function fsCheck(params: unknown, rule: string, signal?: AbortSignal): Promise<string[]> {
  return request(`/api/fieldsolver/check?rule=${encodeURIComponent(rule)}`, { ...fsJson(params), signal });
}

export function fsStartJob(kind: string, payload: unknown): Promise<{ id: string }> {
  return request("/api/fieldsolver/jobs", fsJson({ kind, payload }));
}

export function fsJobStatus(id: string, full = true): Promise<FsJobStatus> {
  return request(`/api/fieldsolver/jobs/${id}?full=${full ? 1 : 0}`);
}

export function fsJobPartial(id: string): Promise<FsResult> {
  return request(`/api/fieldsolver/jobs/${id}/partial`);
}

export function fsJobFrames(id: string, after: number): Promise<{ frames: FsFrame[] }> {
  return request(`/api/fieldsolver/jobs/${id}/frames?after=${after}`);
}

export function fsCancelJob(id: string): Promise<unknown> {
  return request(`/api/fieldsolver/jobs/${id}`, { method: "DELETE" });
}

/** A board's impedance work at one commit: the stackup it is built on, the
 *  impedance profiles it carries, and whatever the .kicad_pcb says about itself. */
export interface FsBoardProfile {
  id: number;
  position: number;
  name: string;
  config: Record<string, unknown>;
  result: Record<string, unknown> | null;
  solved_at: string | null;
  stackup_key: string;
  /** The result was computed against a different stackup than the board now uses. */
  outdated: boolean;
  created_by: string | null;
  updated_at: string | null;
}

export interface FsBoardState {
  revision: {
    id: number;
    board: string;
    stackup_key: string;
    mask_color: string;
    silk_color: string;
    anchor_sha: string;
    anchor_ref: string;
    anchor_committed_at: string | null;
  } | null;
  stackup: FsStackup | null;
  profiles: FsBoardProfile[];
  board_file: FsBoardFile | null;
  /** Plain-language differences between the board file and the assigned stackup. */
  mismatch: string[];
  /** The per-layer table behind `mismatch` — see services/field_state.py. */
  comparison: FsComparison;
  /** Why there is no `board_file`, when there is none. Empty when there is one. */
  board_file_note: string;
}

export interface FsBoardSheet {
  type: string;
  label: string;
  thickness_mm: number;
  eps_r: number | null;
  tand: number | null;
}

export interface FsBoardFile {
  copper_layers: number;
  /** Copper plus dielectric, the way a fab states a stackup. Mask excluded. */
  total_mm: number;
  /** Solder mask, both sides together. KiCad states it, a fab does not. */
  mask_mm: number;
  mask_top_mm: number | null;
  mask_bot_mm: number | null;
  finish: string;
  layers: { name: string; type: string; thickness_mm: number; sheets?: FsBoardSheet[] }[];
  copper: { name: string; thickness_mm: number }[];
  gaps: { above: string; below: string; thickness_mm: number; sheets: FsBoardSheet[] }[];
}

/** One thing compared. `ok` is null when a side does not state a value. */
export interface FsComparisonRow {
  what: string;
  board: string | number | null;
  stackup: string | number | null;
  ok: boolean | null;
  unit: string;
}

/** One side of a stack row — what the board file says, or what the stackup says. */
export interface FsStackFace {
  name: string;
  material: string;
  thickness_mm: number | null;
  dk: number | null;
  tand: number | null;
  weight: string;
  type: string;
}

/** One drawable layer, with the two sides already aligned by the backend.
 *
 *  `severity` is what the table paints: "differs" decides the verdict, "note" is a
 *  difference shown on purpose that does NOT (the surface finish), "none" is a row
 *  nothing could be compared on. See services/field_state.py: stack_rows. */
export interface FsStackRow {
  kind: "overlay" | "mask" | "finish" | "paste" | "copper" | "core" | "prepreg" | "dielectric";
  index: number | null;
  board: FsStackFace | null;
  stackup: FsStackFace | null;
  ok: Record<string, boolean | null>;
  advisory: Record<string, boolean | null>;
  row_ok: boolean | null;
  severity: "match" | "differs" | "note" | "none";
  note: string;
}

export interface FsComparison {
  verdict: "match" | "differs" | "unknown";
  differences: string[];
  rows: FsComparisonRow[];
  /** The same comparison drawn as a stackup, top to bottom. */
  stack: FsStackRow[];
  notes: string[];
  tolerance: { copper_mm: number; dielectric_mm: number; eps_r: number; tand: number };
}

export function fsBoardState(
  projectId: number,
  board: string,
  snapshotId: number | null,
  signal?: AbortSignal,
): Promise<FsBoardState> {
  const q = new URLSearchParams();
  if (board) q.set("board", board);
  if (snapshotId) q.set("snapshot_id", String(snapshotId));
  return request(`/api/fieldsolver/projects/${projectId}/board?${q}`, { signal });
}

export interface FsColor {
  id: string;
  name: string;
  hex: string;
  ink: string;
}

export interface FsColors {
  soldermask: FsColor[];
  silkscreen: FsColor[];
  /** JLCPCB does not offer the silkscreen as a free choice: white on every mask
   *  except a white one, where it is black. The page follows this unless overridden. */
  silkscreen_rule: { default: string; by_mask: Record<string, string>; source: string };
}

export function fsColors(signal?: AbortSignal): Promise<FsColors> {
  return request(`/api/fieldsolver/colors`, { signal });
}

/** Board appearance. PROJECT data — a colour is never written to a stackup, or the
 *  library would fill with one variant per colour that the solver cannot tell apart. */
export function fsSetAppearance(
  projectId: number,
  body: { mask_color: string; silk_color: string; board?: string; snapshot_id?: number | null },
): Promise<FsBoardState> {
  return request(`/api/fieldsolver/projects/${projectId}/appearance`, fsJson(body));
}

export function fsAssignStackup(
  projectId: number,
  body: { stackup_key: string; board?: string; snapshot_id?: number | null },
): Promise<FsBoardState> {
  return request(`/api/fieldsolver/projects/${projectId}/stackup`, fsJson(body));
}

/** The solver page as one person left it. Scratch space, one row per user — the
 *  moment work matters it is saved to a project, which is versioned. */
export function fsGetWorkspace(signal?: AbortSignal): Promise<{ data: unknown | null; updated_at: string | null }> {
  return request(`/api/fieldsolver/workspace`, { signal });
}

export function fsPutWorkspace(data: unknown): Promise<{ ok: boolean }> {
  return request(`/api/fieldsolver/workspace`, { ...fsJson(data), method: "PUT" });
}

/** Save several profiles to a board at once, all or nothing.
 *
 *  Refuses — writing NOTHING — when the board's assigned stackup is not the one the
 *  profiles were built on. Pass `assign_stackup` to assign it to a board that carries
 *  none as part of the same action. */
export function fsSaveProfiles(
  projectId: number,
  body: {
    profiles: { name: string; config: Record<string, unknown>; result?: Record<string, unknown> | null }[];
    board?: string;
    snapshot_id?: number | null;
    stackup_key?: string;
    assign_stackup?: boolean;
  },
): Promise<FsBoardState & { saved: { added: number; replaced: number } }> {
  return request(`/api/fieldsolver/projects/${projectId}/profiles/batch`, fsJson(body));
}

export function fsSaveProfile(
  projectId: number,
  body: {
    name: string;
    config: Record<string, unknown>;
    result?: Record<string, unknown> | null;
    board?: string;
    snapshot_id?: number | null;
    profile_id?: number | null;
  },
): Promise<FsBoardState> {
  return request(`/api/fieldsolver/projects/${projectId}/profiles`, fsJson(body));
}

export function fsDeleteProfile(
  projectId: number,
  profileId: number,
  board: string,
  snapshotId: number | null,
): Promise<FsBoardState> {
  const q = new URLSearchParams();
  if (board) q.set("board", board);
  if (snapshotId) q.set("snapshot_id", String(snapshotId));
  return request(`/api/fieldsolver/projects/${projectId}/profiles/${profileId}?${q}`, { method: "DELETE" });
}

// ------------------------------------------------------------ sales orders
// Decision record 0003: orders above the project, invoices per order,
// shipments whose content is a set of devices, and a per-device history.

export interface CustomerRow {
  id: number;
  name: string;
  tax_id: string;
  address: string;
  payment_terms_days: number;
  notes: string;
  created_at: string | null;
}

export interface OrderLineRow {
  id: number;
  project_id: number;
  project: string;
  board: string;
  variant: string;
  product: string;
  qty_ordered: number;
  unit_price: number;
  net_total: number | null;
  /** devices delivered on this line, replacements excluded */
  qty_shipped: number;
  qty_open: number;
  qty_replacements: number;
  qty_returned: number;
  qty_allocated: number;
  migrated_from_run_id: number | null;
}

export interface OrderInvoiceRow {
  id: number;
  order_id: number;
  kind: "proforma" | "advance" | "final" | "correction";
  number: string;
  issue_date: string;
  due_date: string;
  net_amount: number;
  currency: string;
  paid_at: string;
  attachment_id: number | null;
  notes: string;
}

export interface ShipmentDeviceRow {
  device_id: number;
  serial: string;
  mac: string;
  state: string;
  order_line_id: number;
  auto: boolean;
  replaces_device_id: number | null;
  run_id: number | null;
}

export interface ShipmentRow {
  id: number;
  order_id: number;
  kind: "delivery" | "return";
  shipped_at: string;
  delivery_note: string;
  tracking: string;
  notes: string;
  qty: number;
  per_line: Record<string, number>;
  devices: ShipmentDeviceRow[];
  /** deliveries on this shipment that an `unshipped` event took back */
  reversed: number;
  /** false while ANY device event names the shipment, reversed or not — the
   *  delete endpoint refuses those, so the button must not offer it */
  deletable: boolean;
}

export interface OrderEconomics {
  currency: string;
  revenue_net: number | null;
  revenue_basis: "invoices" | "order";
  revenue_usd: number | null;
  devices_cost_usd: number | null;
  repair_cost_usd: number | null;
  cost_usd: number | null;
  margin_usd: number | null;
  margin_pct: number | null;
  shipped_devices: number;
  replacements: number;
  uncosted_units: number;
  unknown_currencies: string[];
}

export interface OrderRow {
  id: number;
  customer_id: number;
  customer: string;
  order_ref: string;
  order_date: string;
  currency: string;
  vat_pct: number;
  status: "open" | "partial" | "fulfilled" | "cancelled";
  cancelled: boolean;
  notes: string;
  created_at: string | null;
  lines: OrderLineRow[];
  qty_ordered: number;
  qty_shipped: number;
  total_net: number | null;
  invoiced_net: number | null;
  invoice_gap: number | null;
  invoice_count: number;
  unpaid_count: number;
  invoices?: OrderInvoiceRow[];
  shipments?: ShipmentRow[];
  economics?: OrderEconomics;
}

export interface OrderLineIn {
  project_id: number;
  board?: string;
  variant?: string;
  product?: string;
  qty_ordered: number;
  unit_price: number;
}

export interface OrderCreate {
  customer_id?: number | null;
  customer?: string;
  order_ref?: string;
  order_date?: string;
  currency?: string;
  vat_pct?: number;
  notes?: string;
  lines: OrderLineIn[];
}

export interface OrderPatchBody {
  customer_id?: number;
  customer?: string; // create-or-find by name when no id
  order_ref?: string;
  order_date?: string;
  currency?: string;
  vat_pct?: number;
  notes?: string;
  cancelled?: boolean;
}

export interface InvoiceIn {
  kind: OrderInvoiceRow["kind"];
  number: string;
  issue_date: string;
  due_date?: string;
  net_amount: number;
  currency?: string;
  paid_at?: string;
  notes?: string;
}

/** A shipment line NAMES DEVICES. There is no quantity here, and there is no
 *  quantity on the API either: `qty`, `qty_unserialized`, `run_ids` and
 *  `source_run_id` are refused by name with 422 (decision 0049). Declaring one
 *  here would only let the browser build a request the server rejects. */
export interface ShipmentLineIn {
  order_line_id: number;
  device_ids?: number[];
  /** what a scanner read; resolved to device ids server-side */
  serials?: string[];
  replaces_device_id?: number | null;
  note?: string;
}

export interface ShipmentIn {
  shipped_at?: string;
  delivery_note?: string;
  tracking?: string;
  notes?: string;
  lines: ShipmentLineIn[];
}

/** One batch's finished devices, counted from the device records and nothing
 *  else (decision 0003 §8, narrowed by 0049). */
export interface FinishedStockRow {
  run_id: number;
  label: string;
  project_id: number;
  project: string;
  board: string;
  variant: string;
  run_date: string;
  status: string;
  /** devices that PASSED, counted from the device records. A batch with no
   *  device records is 0, never its typed quantity. */
  built: number;
  /** the quantity typed on the run — boards ordered or assembled, not devices */
  qty_recorded: number;
  devices_produced: number;
  /** everything on the shelf, whatever its condition */
  devices_in_stock: number;
  /** what a shipment may draw: in stock AND condition `ok` */
  devices_available: number;
  /** on the shelf but not sellable, by condition — {faulty: 32} */
  devices_held: Record<string, number>;
  devices_shipped: number;
  stock: number;
  /** `stock` minus the units held back */
  available: number;
  unit_cost_usd?: number | null;
  stock_value_usd?: number | null;
}

export interface FinishedStock {
  runs: FinishedStockRow[];
  totals: {
    stock: number;
    devices_in_stock: number;
    /** devices on the shelf that name NO batch, so no row above holds them */
    no_batch: number;
    stock_value_usd: number | null;
  };
}

export interface DeviceEventRow {
  id: number;
  kind: "produced" | "allocated" | "shipped" | "unshipped" | "returned" | "repaired" | "disposed";
  at: string | null;
  actor: string;
  note: string;
  reason: string;
  auto: boolean;
  production_run_id: number | null;
  production_run: string | null;
  order_line_id: number | null;
  order_id: number | null;
  order_ref: string | null;
  customer: string | null;
  product: string | null;
  shipment_id: number | null;
  replaces_device_id: number | null;
  replaces_serial: string | null;
  cost_lines: {
    id: number;
    kind: "labour" | "material";
    amount: number;
    currency: string;
    component_id: number | null;
    qty: number;
    note: string;
  }[];
}

export interface DeviceHistory {
  device_id: number;
  state: string;
  production_run_id: number | null;
  production_run: string | null;
  events: DeviceEventRow[];
}

export function listCustomers(signal?: AbortSignal): Promise<CustomerRow[]> {
  return request(`/api/customers`, { signal });
}

export function createCustomer(body: Omit<CustomerRow, "id" | "created_at">): Promise<CustomerRow> {
  return request(`/api/customers`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
}

export function updateCustomer(
  id: number,
  body: Partial<Omit<CustomerRow, "id" | "created_at">>,
): Promise<CustomerRow> {
  return request(`/api/customers/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) });
}

export function listOrders(signal?: AbortSignal, projectId?: number): Promise<OrderRow[]> {
  return request(`/api/orders${projectId ? `?project_id=${projectId}` : ""}`, { signal });
}

/** Open order quantity against the shelf and the planned batches, per project. */
export interface DemandRow {
  project_id: number;
  project: string;
  open: number;
  open_orders: number;
  on_shelf: number;
  planned: number;
  planned_runs: { run_id: number; label: string; qty: number; run_date: string }[];
  shortfall: number;
  surplus: number;
}

export function getDemand(projectId?: number, signal?: AbortSignal): Promise<DemandRow[]> {
  return request(`/api/demand${projectId ? `?project_id=${projectId}` : ""}`, { signal });
}

export function createOrder(body: OrderCreate): Promise<OrderRow> {
  return request(`/api/orders`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
}

export function getOrder(id: number, signal?: AbortSignal): Promise<OrderRow> {
  return request(`/api/orders/${id}`, { signal });
}

export function updateOrder(id: number, body: OrderPatchBody): Promise<OrderRow> {
  return request(`/api/orders/${id}`, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(body) });
}

export function deleteOrder(id: number): Promise<{ deleted: number }> {
  return request(`/api/orders/${id}`, { method: "DELETE" });
}

export function addOrderLine(orderId: number, body: OrderLineIn): Promise<OrderRow> {
  return request(`/api/orders/${orderId}/lines`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function updateOrderLine(lineId: number, body: Partial<OrderLineIn>): Promise<OrderRow> {
  return request(`/api/order-lines/${lineId}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function deleteOrderLine(lineId: number): Promise<OrderRow> {
  return request(`/api/order-lines/${lineId}`, { method: "DELETE" });
}

export function addOrderInvoice(orderId: number, body: InvoiceIn): Promise<OrderRow> {
  return request(`/api/orders/${orderId}/invoices`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function updateOrderInvoice(invoiceId: number, body: Partial<InvoiceIn>): Promise<OrderRow> {
  return request(`/api/order-invoices/${invoiceId}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function deleteOrderInvoice(invoiceId: number): Promise<OrderRow> {
  return request(`/api/order-invoices/${invoiceId}`, { method: "DELETE" });
}

export function getOrderStockOptions(
  orderId: number,
  signal?: AbortSignal,
): Promise<Record<string, FinishedStockRow[]>> {
  return request(`/api/orders/${orderId}/stock-options`, { signal });
}

export function createShipment(orderId: number, body: ShipmentIn): Promise<OrderRow> {
  return request(`/api/orders/${orderId}/shipments`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function deleteShipment(shipmentId: number): Promise<OrderRow> {
  return request(`/api/shipments/${shipmentId}`, { method: "DELETE" });
}

/** What reversing a shipment would take back (decision 0028). */
export interface ShipmentReversal {
  dry_run: boolean;
  shipment_id: number;
  order_id: number;
  devices: { device_id: number; order_line_id: number | null }[];
}

export function reverseShipment(
  shipmentId: number,
  body: { note?: string; dry_run: boolean },
): Promise<ShipmentReversal> {
  return request(`/api/shipments/${shipmentId}/reverse`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}


/** The shelf per PRODUCT, counted from the DEVICE RECORDS. */
export interface ProductStockRow {
  project_id: number;
  project: string;
  /** every device we hold, whatever condition */
  in_stock: number;
  /** condition `ok` — the only devices a shipment may draw */
  available: number;
  /** present but not sellable, by condition — {faulty: 35, prototype: 12} */
  held: Record<string, number>;
  shipped: number;
  allocated: number;
  /** at each batch's own per-device actual; an unbatched device adds nothing */
  value_usd: number | null;
  /** on the shelf and naming no batch, so no per-batch figure can see them */
  no_batch: number;
  batches: number;
}

export function getProductStock(signal?: AbortSignal): Promise<{ products: ProductStockRow[] }> {
  return request("/api/finished-products", { signal });
}

export function getFinishedStock(projectId?: number, signal?: AbortSignal): Promise<FinishedStock> {
  return request(`/api/finished-stock${projectId ? `?project_id=${projectId}` : ""}`, { signal });
}

export function getDeviceHistory(deviceId: number, signal?: AbortSignal): Promise<DeviceHistory> {
  return request(`/api/devices/${deviceId}/history`, { signal });
}

export function returnDevice(
  deviceId: number,
  body: { order_line_id?: number | null; reason?: string; returned_at?: string; shipment_id?: number | null; note?: string },
): Promise<DeviceHistory> {
  return request(`/api/devices/${deviceId}/return`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function repairDevice(
  deviceId: number,
  body: {
    outcome: "to_stock" | "dispose";
    repaired_at?: string;
    cost_lines?: { kind: "labour" | "material"; amount: number; currency?: string; component_id?: number | null; qty?: number; note?: string }[];
    note?: string;
  },
): Promise<DeviceHistory> {
  return request(`/api/devices/${deviceId}/repair`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function disposeDevice(
  deviceId: number,
  body: { reason?: string; disposed_at?: string; note?: string },
): Promise<DeviceHistory> {
  return request(`/api/devices/${deviceId}/dispose`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

export function linkDevicesToRun(runId: number, deviceIds: number[]): Promise<{ linked: number; skipped: { id: number; reason: string }[] }> {
  return request(`/api/runs/${runId}/produced`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ device_ids: deviceIds }),
  });
}

// ------------------------------------------------------------------ activity
// Admin → Activity: the whole audit log, including the rows the tracker writes
// for every write call (`request`) and every database row it changed (`row.*`).
// Decision 0050; `api/app/routers/activity.py`.

export type ActivityKind = "request" | "event" | "row";

export interface ActivityRow {
  id: number;
  ts: string;
  kind: ActivityKind;
  actor: string;
  user_id: number | null;
  username: string;
  user_display: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  request_id: string | null;
  /** Free-form. A `request` row: method, path, query, status, duration_ms, ip,
   *  user_agent, auth_via. A `row.update`: column -> [old, new]. A
   *  `row.insert`/`row.delete`: column -> value. An event: whatever it wrote. */
  details: unknown;
  /** Only on a `request` row: what that request wrote besides itself. */
  counts?: { rows: number; events: number };
}

export interface ActivityPage {
  rows: ActivityRow[];
  next_before_id: number | null;
}

export function listActivity(
  opts: {
    kinds: ActivityKind[];
    who?: string;
    q?: string;
    requestId?: string;
    beforeId?: number | null;
    limit?: number;
  },
  signal?: AbortSignal,
): Promise<ActivityPage> {
  const params = new URLSearchParams();
  params.set("kind", opts.kinds.join(","));
  if (opts.who) params.set("who", opts.who);
  if (opts.q) params.set("q", opts.q);
  if (opts.requestId) params.set("request_id", opts.requestId);
  if (opts.beforeId) params.set("before_id", String(opts.beforeId));
  if (opts.limit) params.set("limit", String(opts.limit));
  return request(`/api/activity?${params.toString()}`, { signal });
}

/** The undoable batch a request ran, as Production → Write log lists it. */
export interface ActivityWriteBatch {
  id: number;
  kind: string;
  source_ref: string;
  reversed_at: string | null;
  reversed_by_batch_id: number | null;
}

export function getActivityRequest(
  requestId: string,
  signal?: AbortSignal,
): Promise<{ rows: ActivityRow[]; write_batches: ActivityWriteBatch[] }> {
  return request(`/api/activity/requests/${encodeURIComponent(requestId)}`, { signal });
}
