import { defineConfig } from "vite";

export default defineConfig({
  server: { port: 5174, host: "127.0.0.1", fs: { allow: ["."] } },
  build: { target: "esnext" },
});
