import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { APP_BASE } from "./appbase";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

// A deploy replaces every hashed chunk, and a tab opened before it still holds
// the old index. The first lazy import after that — esptool's per-chip module
// on a bench, a route on any page — fails with "Failed to fetch dynamically
// imported module", and on the bench that read as a device that would not
// connect (prod run 6329, 2026-09-17). Vite reports the failure as this event;
// the only fix is the new index, so reload once rather than fail in place.
window.addEventListener("vite:preloadError", (event) => {
  event.preventDefault();
  const key = "reloaded-for-stale-chunk";
  if (sessionStorage.getItem(key) === location.href) return; // never loop
  sessionStorage.setItem(key, location.href);
  window.location.reload();
});

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    {/* basename, not <base href>: pushState navigation ignores the base tag,
        so the router needs the mount point given to it explicitly. */}
    <BrowserRouter basename={APP_BASE || undefined}>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
