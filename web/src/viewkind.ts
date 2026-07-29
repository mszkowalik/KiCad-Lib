/** File-type dispatch for the in-browser file viewer (/view).
 *
 *  PDFs keep plain links — every browser renders them natively and the user
 *  likes that flow. Formats the browser can't render (CAD/mesh files) route
 *  through the viewer page instead of triggering a bare download.
 */
import { API_URL } from "./api";
import { appHref } from "./appbase";

export type ViewKind = "pdf" | "step" | "iges" | "3mf" | "wrl" | "dxf" | "dwg" | "glb" | "image";

const EXT_KINDS: Record<string, ViewKind> = {
  pdf: "pdf",
  step: "step",
  stp: "step",
  iges: "iges",
  igs: "iges",
  "3mf": "3mf",
  wrl: "wrl",
  vrml: "wrl",
  dxf: "dxf",
  dwg: "dwg",
  glb: "glb",
  gltf: "glb",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  svg: "image",
};

/** Kinds the /view page can render (everything except plain links). */
const VIEWER_KINDS: ReadonlySet<ViewKind> = new Set([
  "step",
  "iges",
  "3mf",
  "wrl",
  "dxf",
  "dwg",
  "glb",
  "image",
]);

export function viewKindOf(name: string): ViewKind | null {
  const ext = name.split("?")[0].split("#")[0].split(".").pop()?.toLowerCase() ?? "";
  return EXT_KINDS[ext] ?? null;
}

/** Absolute URL for fetching a same-origin path (or pass through full URLs). */
export function absoluteFileUrl(src: string): string {
  return src.startsWith("/") ? `${API_URL}${src}` : src;
}

/** Where a link to this file should point: the viewer page for CAD/mesh
 *  formats, the raw URL otherwise (PDF → browser viewer, unknown → download).
 *  `src` should be a same-origin path (e.g. /api/datasheets/3/file) when the
 *  file is served by our API — external URLs can't be fetched cross-origin
 *  by the viewer, so they stay plain links. */
export function fileHref(src: string, name: string): string {
  const kind = viewKindOf(name);
  // API_URL is "" for a same-origin build, and every string starts with "" —
  // so the prefix test has to be guarded or external URLs count as ours.
  const prefixed = API_URL !== "" && src.startsWith(API_URL);
  if (kind !== null && VIEWER_KINDS.has(kind) && (src.startsWith("/") || prefixed)) {
    const path = prefixed ? src.slice(API_URL.length) : src;
    // appHref, because this lands in a plain <a href> — the router basename
    // does not apply and <base href> only governs relative urls, so a bare
    // "/view" would escape the mount point.
    return appHref(`/view?src=${encodeURIComponent(path)}&name=${encodeURIComponent(name)}`);
  }
  return absoluteFileUrl(src);
}
