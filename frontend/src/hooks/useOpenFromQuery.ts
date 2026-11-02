"use client";

import { useEffect } from "react";

/**
 * Dashboard quick actions deep-link into a page's create dialog
 * (`/leave?apply=1`, `/helpdesk?new=1`). Calls `open()` once on mount when the
 * query param is present, then removes it so a refresh doesn't reopen it.
 *
 * Reads window.location directly: `useSearchParams` would force every page that
 * uses this into a Suspense boundary just to read one flag.
 */
export function useOpenFromQuery(param: string, open: () => void) {
  useEffect(() => {
    const url = new URL(window.location.href);
    if (!url.searchParams.has(param)) return;
    open();
    url.searchParams.delete(param);
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
