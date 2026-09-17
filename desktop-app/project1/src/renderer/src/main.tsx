import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { queryClient } from "./lib/queryClient";
// Self-hosted (npm-bundled, not a runtime Google Fonts fetch — this app
// needs to render correctly with no network at all, e.g. mid-enrollment
// on a fresh machine) — see globals.css's --font-* variables for how
// these get applied. Latin-only subsets (not the default "all
// languages" import) — this app's UI text is English/Urdu-in-Latin-
// script throughout, and pulling every language subset roughly 8x's the
// font payload bundled into the installer for nothing.
import "@fontsource/poppins/latin-400.css";
import "@fontsource/poppins/latin-500.css";
import "@fontsource/poppins/latin-600.css";
import "@fontsource/poppins/latin-700.css";
import "@fontsource/outfit/latin-500.css";
import "@fontsource/outfit/latin-600.css";
import "@fontsource/outfit/latin-700.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "./styles/globals.css";

// See App.tsx's IS_WIDGET_WINDOW — same flag, read again here (module
// load order between main.tsx and App.tsx isn't guaranteed) purely to
// toggle this one CSS hook before first paint, so the widget's rounded
// card never flashes an opaque square background first.
if (new URLSearchParams(window.location.search).get("widget") === "1") {
  document.body.classList.add("widget-window");
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
