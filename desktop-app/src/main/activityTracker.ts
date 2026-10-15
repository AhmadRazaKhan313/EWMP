/**
 * Polls the OS's currently-focused window (via `get-windows`, a native
 * addon — see get-windows.d.ts for why a type shim exists) and matches it
 * against the org's activity watchlist (delivered on every heartbeat —
 * see deviceTypes.ts's HeartbeatResponse). A match gets queued as an
 * alert; the renderer drains and uploads the queue via
 * POST /devices/alerts/upload on its own heartbeat cadence (see
 * useDeviceHeartbeat.ts) — this module never talks to the network
 * itself, it only tracks local state.
 *
 * IMPORTANT — verification note: `get-windows` is a native compiled addon
 * (platform-specific prebuilt binary, rebuilt for Electron's Node ABI via
 * `@electron/rebuild`, wired as this project's `postinstall` script — see
 * package.json). It could not be fully installed in the environment this
 * file was written in (its install step needs to reach nodejs.org to
 * fetch build headers when no prebuild matches, which that sandbox's
 * network allowlist blocks), so this module's actual runtime behavior —
 * does the native binary load, does polling work, are matches accurate —
 * has NOT been exercised end-to-end. `npm install` and `npm run dev` on a
 * real Windows machine is the first real test this code gets. The
 * dynamic import + try/catch around every poll (see below) is
 * deliberately defensive because of that: a failed/missing native binary
 * must degrade this ONE feature silently, never crash check-in,
 * heartbeat, or screenshot capture, which have nothing to do with it.
 */

export interface WatchlistAlert {
  alert_type: "flagged_app_usage" | "flagged_browsing";
  matched_term: string;
  detail: string;
  occurred_at: string;
}

export interface ActiveWindowLike {
  title: string;
  owner: { name: string };
}

// 10s — frequent enough that a flagged app doesn't run unnoticed for
// most of a work session, infrequent enough not to be a meaningful
// battery/CPU cost or feel like continuous surveillance (contrast with
// screenshots, which are on-demand only — see screenshotCapture.ts).
const POLL_INTERVAL_MS = 10_000;

let watchlist: string[] = [];
let pollTimer: ReturnType<typeof setInterval> | null = null;
let pendingAlerts: WatchlistAlert[] = [];
// Tracks the last term alerted on so continuous focus on the same flagged
// window doesn't produce a new alert every single poll tick — reset
// whenever focus moves to something non-flagged, so returning to the
// SAME flagged window later re-alerts (that's a new instance of it).
let lastAlertedTerm: string | null = null;

export function setActivityWatchlist(terms: string[]): void {
  watchlist = terms;
}

export function startActivityTracking(): void {
  if (pollTimer) return; // already running — start is idempotent
  pollTimer = setInterval(() => void poll(), POLL_INTERVAL_MS);
}

export function stopActivityTracking(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  lastAlertedTerm = null;
}

export function drainPendingAlerts(): WatchlistAlert[] {
  const drained = pendingAlerts;
  pendingAlerts = [];
  return drained;
}

async function poll(): Promise<void> {
  if (watchlist.length === 0) return;

  try {
    // Dynamic, not a static top-level import: if the native binary
    // failed to build/load on this machine, this throws HERE (caught
    // below) on first use, rather than at module load time — which
    // would otherwise take down the whole main process before it even
    // gets to create a window.
    const { activeWindow } = await import("get-windows");
    const win = await activeWindow();
    if (!win) return;

    const match = matchWatchlist(win, watchlist);
    if (!match) {
      lastAlertedTerm = null;
      return;
    }
    if (match.matched_term === lastAlertedTerm) return; // still the same flagged window — don't re-alert every tick
    lastAlertedTerm = match.matched_term;
    pendingAlerts.push(match);
  } catch (err) {
    console.error("[activity-tracker] poll failed (native module unavailable or errored):", err);
  }
}

/**
 * Watch-list entries are domain-shaped ("facebook.com" — see backend's
 * DEVICE_ACTIVITY_WATCHLIST default) but Windows window titles almost
 * never literally contain a domain string; they show the site/app's
 * NAME ("Facebook - Google Chrome"). So matching is done on each term's
 * label (the part before the first dot) as a case-insensitive substring
 * against both the window title and the owning app's name — not the raw
 * domain. Labels under 3 characters are skipped entirely ("x.com" -> "x"
 * would match almost anything and be pure noise); the backend already
 * accepts that this watchlist is "catching obvious policy violations,
 * not building a comprehensive web filter" (see its own config comment),
 * so an imprecise short label is better left unmatched than spamming
 * false positives.
 */
export function matchWatchlist(win: ActiveWindowLike, terms: string[]): WatchlistAlert | null {
  const title = (win.title || "").toLowerCase();
  const appName = (win.owner?.name || "").toLowerCase();

  for (const term of terms) {
    const label = term.split(".")[0]?.toLowerCase().trim();
    if (!label || label.length < 3) continue;

    const hitInApp = appName.includes(label);
    const hitInTitle = title.includes(label);
    if (!hitInApp && !hitInTitle) continue;

    return {
      // "flagged_app_usage" when the match is specifically the app
      // itself (a dedicated desktop app, e.g. a standalone Netflix/
      // Spotify app) rather than something found in a browser tab title.
      alert_type: hitInApp && !hitInTitle ? "flagged_app_usage" : "flagged_browsing",
      matched_term: term,
      detail: `Matched "${label}" in ${hitInApp && !hitInTitle ? "application" : "window title"}: "${win.title}" (${win.owner?.name})`,
      occurred_at: new Date().toISOString(),
    };
  }
  return null;
}
