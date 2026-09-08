import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

/**
 * Regression test for a real bug: the CSP header set in main/index.ts had
 * no explicit `connect-src` directive, which per the CSP spec makes it
 * fall back to `default-src 'self'` — silently blocking every fetch/XHR
 * call to anything other than the app's own origin. This looked exactly
 * like a network/firewall/CORS problem (axios reports a generic "Network
 * Error"), but the request was being blocked by the renderer's own CSP
 * before it ever reached the network layer.
 *
 * Confirmed with a real Electron renderer (see
 * scripts/verify-csp-connect-src.js for the full reproduction): the old
 * CSP fired a genuine `securitypolicyviolation` event
 * (`directive=connect-src`) for any cross-origin fetch; the fixed CSP
 * does not.
 *
 * This test is a fast, static safety net for the obvious regression
 * (someone removing connect-src again); it can't replace actually
 * running a fetch in a real renderer, which is why the script above
 * exists too — run it whenever CSP is touched.
 */
describe("main process CSP includes a broad connect-src", () => {
  it("does not omit connect-src (which would fall back to default-src 'self')", () => {
    const source = readFileSync(resolve(__dirname, "../index.ts"), "utf-8");
    const cspBlockMatch = source.match(/Content-Security-Policy["'\s:[]+([\s\S]*?)["']\s*,?\s*\]/);
    expect(cspBlockMatch, "Could not find a Content-Security-Policy header definition in main/index.ts").not.toBeNull();

    const csp = cspBlockMatch![1]!;
    expect(csp).toContain("connect-src");

    // The connect-src value itself must not be scoped to 'self' only —
    // that's exactly the bug (backend runs on a different machine/origin
    // than the app, and its address is admin-configured at runtime).
    const connectSrcMatch = csp.match(/connect-src\s+([^;]+)/);
    expect(connectSrcMatch, "connect-src directive found but couldn't parse its value").not.toBeNull();
    const connectSrcValue = connectSrcMatch![1]!.trim();
    expect(connectSrcValue).not.toBe("'self'");
    expect(connectSrcValue.length).toBeGreaterThan("'self'".length);
  });

  it("still scopes script-src to 'self' (connect-src being broad must not weaken script execution controls)", () => {
    const source = readFileSync(resolve(__dirname, "../index.ts"), "utf-8");
    const cspBlockMatch = source.match(/Content-Security-Policy["'\s:[]+([\s\S]*?)["']\s*,?\s*\]/);
    const csp = cspBlockMatch![1]!;
    expect(csp).toMatch(/script-src\s+'self'/);
  });
});
