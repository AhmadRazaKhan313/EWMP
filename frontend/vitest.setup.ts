import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Explicit rather than relying on RTL's auto-detection of a global afterEach,
// so DOM from one test never leaks into the next (index-based queries like
// `getAllByRole("button")[n]` are especially sensitive to this).
afterEach(() => {
  cleanup();
});
