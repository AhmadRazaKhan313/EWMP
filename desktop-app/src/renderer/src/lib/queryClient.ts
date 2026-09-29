import { QueryClient } from "@tanstack/react-query";

/**
 * The one QueryClient instance for this renderer, pulled out of main.tsx
 * so it can also be imported from outside the React tree — specifically
 * by store/timerStore.ts, which needs to invalidate the dashboard's
 * queries the instant a check-in/check-out/break action completes rather
 * than waiting for their poll interval (up to 2 minutes). See
 * timerStore.ts's `invalidateAfterTimerAction` for why that matters.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});
