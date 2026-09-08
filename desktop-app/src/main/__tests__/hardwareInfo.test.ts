import { describe, it, expect, vi } from "vitest";

vi.mock("electron", () => ({ app: { getVersion: (): string => "1.2.3" } }));

import { detectOsType, firstMacAddress, getHardwareInfo } from "../hardwareInfo";

describe("detectOsType", () => {
  it("maps process.platform to the backend's DeviceOS values", () => {
    const original = Object.getOwnPropertyDescriptor(process, "platform")!;
    for (const [platform, expected] of [
      ["win32", "windows"],
      ["linux", "linux"],
      ["darwin", "macos"],
      ["freebsd", "other"],
    ] as const) {
      Object.defineProperty(process, "platform", { value: platform });
      expect(detectOsType()).toBe(expected);
    }
    Object.defineProperty(process, "platform", original);
  });
});

describe("firstMacAddress", () => {
  it("skips internal interfaces (e.g. loopback)", () => {
    const mac = firstMacAddress({
      lo: [{ mac: "00:00:00:00:00:00", internal: true } as never],
      eth0: [{ mac: "aa:bb:cc:dd:ee:ff", internal: false } as never],
    });
    expect(mac).toBe("aa:bb:cc:dd:ee:ff");
  });

  it("skips a real interface reporting the null MAC", () => {
    const mac = firstMacAddress({
      eth0: [{ mac: "00:00:00:00:00:00", internal: false } as never],
      wlan0: [{ mac: "11:22:33:44:55:66", internal: false } as never],
    });
    expect(mac).toBe("11:22:33:44:55:66");
  });

  it("returns null when no usable interface exists", () => {
    expect(firstMacAddress({ lo: [{ mac: "00:00:00:00:00:00", internal: true } as never] })).toBeNull();
    expect(firstMacAddress({})).toBeNull();
  });
});

describe("getHardwareInfo", () => {
  it("returns a fully-populated, backend-shaped object", () => {
    const info = getHardwareInfo();
    expect(info.hostname).toEqual(expect.any(String));
    expect(["windows", "linux", "macos", "other"]).toContain(info.os_type);
    expect(info.cpu_cores).toBeGreaterThan(0);
    expect(info.ram_total_gb).toBeGreaterThan(0);
    expect(info.agent_version).toBe("1.2.3");
  });
});
