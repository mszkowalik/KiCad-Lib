/** Typed client for the Project Management Platform API.
 *
 * Shapes mirror the FastAPI routers in platform/api/app/routers/
 * (categories.py, components.py, import_station.py).
 */

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

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
}

export interface ComponentListResponse {
  total: number;
  page: number;
  page_size: number;
  items: ComponentListItem[];
}

export interface PinnedRef {
  name: string;
  version_no: number;
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
  current_version_no: number | null;
  versions: VersionSummary[];
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
}

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
  name: string;
  version_no: number | null;
  pin_count: number | null;
}

export interface FootprintListItem {
  name: string;
  version_no: number | null;
  pad_count: number | null;
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

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw new ApiError(0, `Cannot reach API at ${API_URL} (${errorMessage(err)})`);
  }
  if (!res.ok) {
    let detail = "";
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
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
    throw new ApiError(res.status, detail || `${res.status} ${res.statusText}`);
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
  /** PCM repository URL — add in KiCad's Plugin and Content Manager. */
  pcm_repo_url: string;
  token_hint: string;
}

export interface DatasheetFetchStatus {
  running: boolean;
  mode: string | null;
  done: number;
  total: number;
  new_versions: number;
  unchanged: number;
  errors: number;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
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
 *  Deliberately no timeout — the browser's own limit applies. */
export function jaravisChat(messages: ChatMessage[]): Promise<ChatResponse> {
  return request("/api/jaravis/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });
}

// ---------------------------------------------------------------- comments

/** Free-form component-scoped note (not versioned). */
export interface ComponentComment {
  id: number;
  component_id: number;
  author: string;
  body: string;
  created_at: string;
}

export function getComments(compId: number, signal?: AbortSignal): Promise<ComponentComment[]> {
  return request(`/api/components/${compId}/comments`, { signal });
}

export function addComment(compId: number, body: string): Promise<ComponentComment> {
  return request(`/api/components/${compId}/comments`, {
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

/** Creates a new skill (409 on duplicate name). */
export function createSkill(name: string, content: string): Promise<SkillSaveResponse> {
  return request("/api/skills", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, content }),
  });
}

// --------------------------------------------------------------- proposals

export interface ComponentProposal {
  kind: "component";
  proposal_id: number;
  component_id: number;
  component_name: string;
  version_no: number;
  is_new_component: boolean;
  base_component: string;
  category_path: string;
  created_by: string | null;
  created_at: string;
  comment: string | null;
  status: string;
}

export interface SkillProposal {
  kind: "skill";
  proposal_id: number;
  skill_id: number;
  skill_name: string;
  /** Equals skill_name — provided by the API to keep table display simple. */
  component_name: string;
  version_no: number;
  created_by: string | null;
  created_at: string;
  comment: string | null;
  status: string;
}

/** Symbol / footprint geometry proposal (drafted by Jaravis). */
export interface GeometryProposal {
  kind: "symbol" | "footprint";
  proposal_id: number;
  /** The symbol/footprint name — field named like the others to keep the table simple. */
  component_name: string;
  version_no: number;
  is_new_component: boolean;
  created_by: string | null;
  created_at: string;
  comment: string | null;
  status: string;
}

export type Proposal = ComponentProposal | SkillProposal | GeometryProposal;

/** Approve/reject responses for component proposals (no `kind` field). */
export interface ComponentProposalAction {
  proposal_id: number;
  component_id: number;
  component_name: string;
  version_no: number;
  is_new_component: boolean;
  base_component: string;
  category_path: string;
  created_by: string | null;
  created_at: string;
  comment: string | null;
  status: string;
  mirror?: Record<string, number>;
  mirror_warnings?: string[];
}

export interface SkillProposalAction {
  kind: string;
  proposal_id: number;
  skill_name: string;
  version_no: number;
  status: string;
}

export function getProposals(signal?: AbortSignal): Promise<Proposal[]> {
  return request("/api/proposals", { signal });
}

export function approveProposal(id: number): Promise<ComponentProposalAction> {
  return request(`/api/proposals/${id}/approve`, { method: "POST" });
}

export function rejectProposal(id: number): Promise<ComponentProposalAction> {
  return request(`/api/proposals/${id}/reject`, { method: "POST" });
}

export function approveSkillProposal(id: number): Promise<SkillProposalAction> {
  return request(`/api/proposals/skills/${id}/approve`, { method: "POST" });
}

export function rejectSkillProposal(id: number): Promise<SkillProposalAction> {
  return request(`/api/proposals/skills/${id}/reject`, { method: "POST" });
}

export interface GeometryProposalAction {
  kind: string;
  proposal_id: number;
  component_name: string;
  version_no: number;
  status: string;
  mirror?: Record<string, number>;
  mirror_warnings?: string[];
}

export function approveGeometryProposal(
  kind: "symbol" | "footprint",
  id: number,
): Promise<GeometryProposalAction> {
  return request(`/api/proposals/${kind}s/${id}/approve`, { method: "POST" });
}

export function rejectGeometryProposal(
  kind: "symbol" | "footprint",
  id: number,
): Promise<GeometryProposalAction> {
  return request(`/api/proposals/${kind}s/${id}/reject`, { method: "POST" });
}

/** SVG preview of a geometry proposal — draft or the live current version. */
export function geometryProposalPreviewUrl(
  kind: "symbol" | "footprint",
  id: number,
  which: "draft" | "current",
): string {
  return `${API_URL}/api/proposals/${kind}s/${id}/preview.svg?which=${which}`;
}

export function startImport(): Promise<{ status: string }> {
  return request("/api/import", { method: "POST" });
}

/** Non-destructive: diff Sources/*.yaml against the DB → draft proposals. */
export function startSync(): Promise<{ status: string }> {
  return request("/api/import/sync", { method: "POST" });
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
}

export interface RunPatchBody {
  label?: string;
  qty?: number;
  status?: string;
  run_date?: string;
  notes?: string;
  overrides?: Record<string, unknown>;
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
