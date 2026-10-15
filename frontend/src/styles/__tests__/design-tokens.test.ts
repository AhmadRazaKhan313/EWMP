// @vitest-environment node
/**
 * Guards for the design tokens (UI redesign, foundation task).
 *
 *  1. The web app and the desktop app share ONE design system: the
 *     "SHARED TOKENS" CSS block and tailwind.tokens.js must be identical in
 *     both. Rebranding means editing the brand scale — in both copies — and
 *     this fails if one of them is forgotten.
 *  2. The brand colour lives only in the brand scale; roles point at it.
 *  3. Every token the code uses is actually defined (a missing token makes a
 *     colour silently disappear rather than fail).
 *
 * The desktop checks are skipped when desktop-app/ isn't present (the
 * frontend's Docker build copies only frontend/).
 */
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = fileURLToPath(new URL(".", import.meta.url));
const FRONTEND = resolve(here, "../../..");
const DESKTOP = resolve(FRONTEND, "../desktop-app");
const WEB_CSS = join(FRONTEND, "src/styles/globals.css");
const DESKTOP_CSS = join(DESKTOP, "src/renderer/src/styles/globals.css");
const hasDesktop = existsSync(DESKTOP_CSS);

const BEGIN = "/* ── SHARED TOKENS: BEGIN";
const END = "/* ── SHARED TOKENS: END ── */";

function sharedBlock(path: string): string {
  const css = readFileSync(path, "utf8").replace(/\r\n/g, "\n");
  const start = css.indexOf(BEGIN);
  const end = css.indexOf(END);
  expect(start, `${path} is missing the SHARED TOKENS: BEGIN marker`).toBeGreaterThanOrEqual(0);
  expect(end, `${path} is missing the SHARED TOKENS: END marker`).toBeGreaterThan(start);
  return css.slice(start, end + END.length);
}

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "__tests__") continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) files(full, out);
    else if (/\.(tsx?|css)$/.test(name)) out.push(full);
  }
  return out;
}

const stripComments = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

function undefinedTokens(srcDir: string, cssPath: string, providedElsewhere: string[] = []): string[] {
  const defined = new Set<string>(providedElsewhere);
  for (const m of readFileSync(cssPath, "utf8").matchAll(/^\s*(--[\w-]+):/gm)) if (m[1]) defined.add(m[1]);
  const used = new Set<string>();
  for (const f of files(srcDir)) {
    const text = stripComments(readFileSync(f, "utf8"));
    for (const m of text.matchAll(/"(--[\w-]+)":/g)) if (m[1]) defined.add(m[1]); // inline style={{ "--x": … }}
    for (const m of text.matchAll(/var\((--[\w-]+)/g)) if (m[1]) used.add(m[1]);
  }
  return [...used].filter((t) => !defined.has(t)).sort();
}

describe("design tokens", () => {
  it("defines the brand as a 12-step scale and points the primary colour at it", () => {
    const block = sharedBlock(WEB_CSS);
    for (const step of [25, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]) {
      expect(block).toMatch(new RegExp(`--brand-${step}: [\\d.]+ [\\d.]+% [\\d.]+%;`));
    }
    expect(block).toContain("--primary: var(--brand-600);");
    expect(block).toContain("--primary-hover: var(--brand-700);");
  });

  it("uses no hard-coded brand colour outside the brand scale", () => {
    const roles = sharedBlock(WEB_CSS).split("/* 3. Semantic roles")[1];
    expect(roles).not.toMatch(/#[0-9a-f]{6}/i);
  });

  it("every token the web app uses is defined", () => {
    // next/font sets the --font-* variables on <html> (app/layout.tsx).
    expect(undefinedTokens(join(FRONTEND, "src"), WEB_CSS, ["--font-sans", "--font-heading", "--font-mono"])).toEqual([]);
  });

  it.skipIf(!hasDesktop)("the desktop app shares exactly the same token block", () => {
    expect(sharedBlock(DESKTOP_CSS)).toBe(sharedBlock(WEB_CSS));
  });

  it.skipIf(!hasDesktop)("the desktop app shares exactly the same Tailwind theme", () => {
    const read = (p: string) => readFileSync(p, "utf8").replace(/\r\n/g, "\n");
    expect(read(join(DESKTOP, "tailwind.tokens.js"))).toBe(read(join(FRONTEND, "tailwind.tokens.js")));
  });

  it.skipIf(!hasDesktop)("every token the desktop app uses is defined", () => {
    expect(undefinedTokens(join(DESKTOP, "src/renderer/src"), DESKTOP_CSS)).toEqual([]);
  });
});
