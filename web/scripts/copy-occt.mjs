/** Copies the occt-import-js runtime (UMD glue + wasm, ~7 MB) from
 *  node_modules into public/occt/ so the STEP viewer can load it via a plain
 *  <script> tag — the emscripten UMD bundle does not survive Vite's module
 *  pipeline. Runs automatically via the predev / prebuild npm scripts;
 *  public/occt/ is gitignored. */
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "occt-import-js", "dist");
const dst = join(root, "public", "occt");

mkdirSync(dst, { recursive: true });
for (const name of ["occt-import-js.js", "occt-import-js.wasm"]) {
  copyFileSync(join(src, name), join(dst, name));
}
console.log("occt-import-js runtime copied to public/occt/");
