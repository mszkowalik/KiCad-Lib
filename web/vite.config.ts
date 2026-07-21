import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // In Docker on macOS/Windows, bind-mount edits don't fire fsevents, so the
    // watcher must poll. Enabled via CHOKIDAR_USEPOLLING (set for the web
    // container in compose.yaml); native host dev keeps efficient fsevents.
    watch:
      process.env.CHOKIDAR_USEPOLLING === "true"
        ? { usePolling: true, interval: 100 }
        : undefined,
  },
});
