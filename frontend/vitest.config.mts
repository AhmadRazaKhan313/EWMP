import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";

// Minimal test runner for `frontend/`. Kept intentionally small — this is
// the first test setup in this package (see EWMP bug catalogue: no
// Jest/Vitest/RTL existed before the C4 fix). Extend as more
// component/unit tests get added under Phase 0.
export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
    css: false,
  },
});
