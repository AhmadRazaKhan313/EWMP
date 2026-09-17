/**
 * Ambient type shim for `get-windows` (the actively-maintained successor
 * to `active-win`, which is deprecated — npm flags it as "Renamed to
 * get-windows" as of active-win@9).
 *
 * On a real dev machine, `npm install` fetches the genuine package (a
 * native addon with a proper index.d.ts) and this file is redundant but
 * harmless — TypeScript prefers a real package's own types when present.
 *
 * This shim exists because get-windows could not be fully installed in
 * the environment this was built in (its install step downloads a
 * platform-matched prebuilt native binary, which needs network access
 * this sandbox's egress allowlist blocks) — see
 * main/activityTracker.ts's top-of-file note for what that means for
 * verification.
 *
 * Shape matches get-windows@9's documented API — only the fields this
 * codebase actually reads.
 */
declare module "get-windows" {
  interface ActiveWindowOwner {
    name: string;
    processId: number;
    path?: string;
  }

  interface ActiveWindowResult {
    title: string;
    id: number;
    owner: ActiveWindowOwner;
    /** Only populated on macOS for a handful of known browsers — never
     * present on Windows/Linux. Matching logic must not depend on this
     * being available. */
    url?: string;
  }

  export function activeWindow(options?: {
    accessibilityPermission?: boolean;
    screenRecordingPermission?: boolean;
  }): Promise<ActiveWindowResult | undefined>;
}
