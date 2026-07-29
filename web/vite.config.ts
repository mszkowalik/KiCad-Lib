import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Where the dev server forwards the API paths. Keeps dev same-origin, the same
// way nginx does in the built image, so the client can use relative paths and
// needs no VITE_API_URL. Override for an API on another host or port.
const apiTarget = process.env.VITE_API_PROXY ?? "http://localhost:8020";

const apiPaths = ["/api", "/kicad", "/files", "/docs", "/redoc", "/openapi.json"];

export default defineConfig(({ command }) => ({
  // Relative asset urls on build, so the <base href> injected into index.html
  // at container start decides the mount point. An absolute base would bake the
  // prefix into the image. Dev does not support a relative base, and does not
  // need one — it always serves from the root.
  base: command === "build" ? "./" : "/",
  plugins: [
    react(),
    {
      // The dev server has no container entrypoint to substitute the mount
      // point, so resolve the placeholder to "" — dev is always at the root.
      name: "app-base-dev",
      apply: "serve",
      transformIndexHtml: (html) => html.replaceAll("__APP_BASE__", ""),
    },
  ],
  server: {
    port: 5173,
    host: true,
    // ws: true so the flasher's run WebSocket (/api/flasher/ws/…) rides the
    // same proxy as plain requests.
    proxy: Object.fromEntries(
      apiPaths.map((p) => [p, { target: apiTarget, changeOrigin: true, ws: true }]),
    ),
    // In Docker on macOS/Windows, bind-mount edits don't fire fsevents, so the
    // watcher must poll. Enabled via CHOKIDAR_USEPOLLING (set for the web
    // container in compose.yaml); native host dev keeps efficient fsevents.
    watch:
      process.env.CHOKIDAR_USEPOLLING === "true"
        ? { usePolling: true, interval: 100 }
        : undefined,
  },
}));
