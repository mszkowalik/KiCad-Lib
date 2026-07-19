/** JSX typing for the <model-viewer> custom element (@google/model-viewer).
 *  Attributes are intentionally loose — the element takes kebab-case HTML
 *  attributes, not typed React props. */
declare namespace JSX {
  interface IntrinsicElements {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    "model-viewer": any;
  }
}
