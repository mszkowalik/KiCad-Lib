import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { APP_BASE } from "./appbase";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    {/* basename, not <base href>: pushState navigation ignores the base tag,
        so the router needs the mount point given to it explicitly. */}
    <BrowserRouter basename={APP_BASE || undefined}>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
