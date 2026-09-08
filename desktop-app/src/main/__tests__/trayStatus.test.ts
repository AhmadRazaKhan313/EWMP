import { describe, it, expect, vi } from "vitest";

vi.mock("electron", () => ({
  nativeImage: {
    createFromDataURL: (dataUrl: string): { __dataUrl: string; addRepresentation: ReturnType<typeof vi.fn> } => ({
      __dataUrl: dataUrl,
      addRepresentation: vi.fn(),
    }),
  },
  Menu: {
    buildFromTemplate: (template: unknown[]): { __template: unknown[] } => ({ __template: template }),
  },
}));

import { applyTrayStatus, TRAY_STATUS_LABEL } from "../trayStatus";

function fakeTray(): {
  setImage: ReturnType<typeof vi.fn>;
  setToolTip: ReturnType<typeof vi.fn>;
  setContextMenu: ReturnType<typeof vi.fn>;
} {
  return { setImage: vi.fn(), setToolTip: vi.fn(), setContextMenu: vi.fn() };
}

describe("applyTrayStatus", () => {
  it("sets a status-specific tooltip for each state", () => {
    for (const status of ["idle", "active", "on_break"] as const) {
      const tray = fakeTray();
      applyTrayStatus(tray as never, status, { onOpen: vi.fn(), onQuit: vi.fn() });
      expect(tray.setToolTip).toHaveBeenCalledWith(`EWMP — ${TRAY_STATUS_LABEL[status]}`);
    }
  });

  it("sets a new icon image on every call", () => {
    const tray = fakeTray();
    applyTrayStatus(tray as never, "active", { onOpen: vi.fn(), onQuit: vi.fn() });
    expect(tray.setImage).toHaveBeenCalledTimes(1);
  });

  it("builds a context menu whose first (disabled) row shows the status label", () => {
    const tray = fakeTray();
    applyTrayStatus(tray as never, "on_break", { onOpen: vi.fn(), onQuit: vi.fn() });

    const [{ __template: template }] = tray.setContextMenu.mock.calls[0] as [{ __template: Array<Record<string, unknown>> }];
    expect(template[0]).toMatchObject({ label: "On break", enabled: false });
  });

  it("wires the Open/Quit menu items to the given handlers", () => {
    const tray = fakeTray();
    const onOpen = vi.fn();
    const onQuit = vi.fn();
    applyTrayStatus(tray as never, "idle", { onOpen, onQuit });

    const [{ __template: template }] = tray.setContextMenu.mock.calls[0] as [
      { __template: Array<{ label?: string; click?: () => void }> },
    ];
    template.find((item) => item.label === "Open EWMP")?.click?.();
    template.find((item) => item.label === "Quit")?.click?.();

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onQuit).toHaveBeenCalledTimes(1);
  });
});
