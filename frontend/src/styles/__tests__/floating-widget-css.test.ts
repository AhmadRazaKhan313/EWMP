/**
 * The floating check-in / break widget has one stylesheet used by BOTH the
 * website and the desktop app, so the two look identical. The copies must not
 * drift: edit one, copy it to the other.
 *
 * (Skipped when desktop-app/ isn't present, like design-tokens.test.ts.)
 */
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const WEB = resolve(__dirname, "../floating-widget.css");
const DESKTOP = resolve(__dirname, "../../../../desktop-app/src/renderer/src/styles/floating-widget.css");

describe("floating widget stylesheet", () => {
  it("defines the card, buttons and pill", () => {
    const css = readFileSync(WEB, "utf8");
    for (const cls of [".fw-card", ".fw-btn--teal", ".fw-btn--red", ".fw-btn--orange", ".fw-pill", ".fw-fill"]) {
      expect(css).toContain(cls);
    }
  });

  it.skipIf(!existsSync(DESKTOP))("is identical in the website and the desktop app", () => {
    expect(readFileSync(DESKTOP, "utf8")).toBe(readFileSync(WEB, "utf8"));
  });
});
