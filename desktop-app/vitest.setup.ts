import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach((): void => {
  cleanup();
});

// Tests that exercise renderer code touching window.ewmp should override
// this per-test with vi.spyOn/mockResolvedValue as needed; this baseline
// stub just keeps unrelated tests from crashing on an undefined bridge.
//
// secureStore.get defaults "deviceConsentAcknowledged" to already-true
// (and everything else to null) deliberately: tests unrelated to device
// enrollment (auth routing, the timer widget, etc.) render
// AuthenticatedPlaceholder without knowing anything about
// ConsentNotice/deviceStore, and must never get gated behind it just
// because the real default (not-yet-consented) would otherwise apply.
// Tests that specifically exercise the not-yet-consented path override
// this per-test — see deviceStore.test.ts / ConsentNotice.test.tsx.
if (typeof window !== "undefined") {
  (window as unknown as { ewmp: unknown }).ewmp = {
    app: { getVersion: async (): Promise<string> => "0.0.0-test" },
    secureStore: {
      get: async (key: string): Promise<string | null> => (key === "deviceConsentAcknowledged" ? "true" : null),
      set: async (): Promise<void> => undefined,
      delete: async (): Promise<void> => undefined,
      clear: async (): Promise<void> => undefined,
    },
    window: { hide: async (): Promise<void> => undefined },
    tray: { setStatus: async (): Promise<void> => undefined, setTooltip: async (): Promise<void> => undefined },
    device: {
      getHardwareInfo: async (): Promise<Record<string, unknown>> => ({
        hostname: "test-host",
        os_type: "other",
        os_name: "test",
        os_version: "0",
        cpu_model: "test-cpu",
        cpu_cores: 4,
        ram_total_gb: 8,
        mac_address: "00:00:00:00:00:00",
        agent_version: "0.0.0-test",
      }),
    },
  };
}

// ── ewmp: fill-in stubs (adds only what is missing) ──────────────────────────
if (typeof window !== "undefined") {
  if (typeof window.matchMedia !== "function") {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string): MediaQueryList =>
        ({
          matches: false,
          media: query,
          onchange: null,
          addListener: () => undefined,
          removeListener: () => undefined,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          dispatchEvent: () => false,
        }) as unknown as MediaQueryList,
    });
  }

  const noop = async (): Promise<void> => undefined;
  const defaults: Record<string, Record<string, unknown>> = {
    app: { getVersion: async (): Promise<string> => "0.0.0-test" },
    secureStore: {
      get: async (key: string): Promise<string | null> => (key === "deviceConsentAcknowledged" ? "true" : null),
      set: noop,
      delete: noop,
      clear: noop,
    },
    window: { hide: noop },
    tray: { setStatus: noop, setTooltip: noop, setBadgeCount: noop },
    device: {
      getHardwareInfo: async (): Promise<Record<string, unknown>> => ({
        hostname: "test-host", os_type: "other", os_name: "test", os_version: "0",
        cpu_model: "test-cpu", cpu_cores: 4, ram_total_gb: 8, mac_address: "00:00:00:00:00:00",
        agent_version: "0.0.0-test",
      }),
      captureScreenshot: async (): Promise<Record<string, unknown>> => ({ base64Png: "", width: 0, height: 0 }),
    },
    activity: { start: noop, stop: noop, setWatchlist: noop, drainAlerts: async (): Promise<unknown[]> => [] },
    widget: { toggle: async (): Promise<boolean> => true, hide: noop, isVisible: async (): Promise<boolean> => false },
  };
  const w = window as unknown as { ewmp?: Record<string, Record<string, unknown>> };
  w.ewmp = w.ewmp ?? {};
  for (const [group, fns] of Object.entries(defaults)) {
    w.ewmp[group] = { ...fns, ...(w.ewmp[group] ?? {}) };
  }
}
