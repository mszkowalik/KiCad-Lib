/** Lazy-loaded wrapper around Google's <model-viewer> web component.
 *  The side-effect import registers the custom element and pulls in the
 *  three.js-based engine (~1 MB), so this module is only loaded via
 *  React.lazy when the 3D view is actually opened.
 *
 *  No environment-image is set on purpose: the default neutral studio
 *  lighting is bright, and model-viewer auto-frames the model and manages
 *  the camera near/far planes (no clipping while orbiting). */
import "@google/model-viewer";

export default function ModelViewer({ src }: { src: string }) {
  return (
    <model-viewer
      src={src}
      camera-controls=""
      exposure="1.25"
      shadow-intensity="0.6"
      interaction-prompt="none"
      style={{ width: "100%", height: "100%", backgroundColor: "#1e2125" }}
    />
  );
}
