import { describe, it, expect, vi, beforeEach } from "vitest";
import { useDeviceStore } from "../deviceStore";
import { deviceService } from "../../services/deviceService";

const HW = {
  hostname: "h1", os_type: "linux" as const, os_name: "Linux", os_version: "6.0",
  cpu_model: "cpu", cpu_cores: 8, ram_total_gb: 16, mac_address: "aa:bb:cc:dd:ee:ff", agent_version: "1.0.0",
};

function reset(): void {
  useDeviceStore.setState({ status: "checking", error: null });
}

describe("deviceStore.init", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("needs_consent when the consent flag was never set", async () => {
    vi.spyOn(window.ewmp.secureStore, "get").mockResolvedValue(null);
    await useDeviceStore.getState().init();
    expect(useDeviceStore.getState().status).toBe("needs_consent");
  });

  it("enrolled when a deviceId is already stored (no network call)", async () => {
    const spy = vi.spyOn(window.ewmp.secureStore, "get").mockImplementation(
      async (key: string) => (key === "deviceConsentAcknowledged" ? "true" : key === "deviceId" ? "d1" : null),
    );
    const enrollSpy = vi.spyOn(deviceService, "selfEnroll");
    await useDeviceStore.getState().init();
    expect(useDeviceStore.getState().status).toBe("enrolled");
    expect(enrollSpy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("needs_finish when consent was given but no deviceId exists yet", async () => {
    vi.spyOn(window.ewmp.secureStore, "get").mockImplementation(
      async (key: string) => (key === "deviceConsentAcknowledged" ? "true" : null),
    );
    await useDeviceStore.getState().init();
    expect(useDeviceStore.getState().status).toBe("needs_finish");
  });

  it("fails open to enrolled if local state can't be read at all", async () => {
    vi.spyOn(window.ewmp.secureStore, "get").mockRejectedValue(new Error("disk error"));
    await useDeviceStore.getState().init();
    expect(useDeviceStore.getState().status).toBe("enrolled");
  });
});

describe("deviceStore.acknowledgeAndEnroll", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("persists consent, enrolls, and stores the returned device credentials", async () => {
    const setSpy = vi.spyOn(window.ewmp.secureStore, "set").mockResolvedValue(undefined);
    vi.spyOn(deviceService, "getHardwareInfo").mockResolvedValue(HW);
    vi.spyOn(deviceService, "selfEnroll").mockResolvedValue({ device_id: "d1", agent_token: "tok1" });

    await useDeviceStore.getState().acknowledgeAndEnroll();

    expect(setSpy).toHaveBeenCalledWith("deviceConsentAcknowledged", "true");
    expect(setSpy).toHaveBeenCalledWith("deviceId", "d1");
    expect(setSpy).toHaveBeenCalledWith("agentToken", "tok1");
    expect(useDeviceStore.getState().status).toBe("enrolled");
    expect(useDeviceStore.getState().error).toBeNull();
  });

  it("still records consent even if the enroll call fails, and never re-asks", async () => {
    const setSpy = vi.spyOn(window.ewmp.secureStore, "set").mockResolvedValue(undefined);
    vi.spyOn(deviceService, "getHardwareInfo").mockResolvedValue(HW);
    vi.spyOn(deviceService, "selfEnroll").mockRejectedValue({
      response: { data: { detail: "No employee record linked to this account — cannot self-enroll a device." } },
    });

    await useDeviceStore.getState().acknowledgeAndEnroll();

    expect(setSpy).toHaveBeenCalledWith("deviceConsentAcknowledged", "true");
    expect(useDeviceStore.getState().status).toBe("needs_finish"); // not needs_consent
    expect(useDeviceStore.getState().error).toMatch(/cannot self-enroll/);
  });
});

describe("deviceStore.retryEnrollment", () => {
  beforeEach(() => { vi.clearAllMocks(); reset(); });

  it("re-attempts enrollment without touching the consent flag", async () => {
    const setSpy = vi.spyOn(window.ewmp.secureStore, "set").mockResolvedValue(undefined);
    vi.spyOn(deviceService, "getHardwareInfo").mockResolvedValue(HW);
    vi.spyOn(deviceService, "selfEnroll").mockResolvedValue({ device_id: "d1", agent_token: "tok1" });

    useDeviceStore.setState({ status: "needs_finish", error: "previous failure" });
    await useDeviceStore.getState().retryEnrollment();

    expect(setSpy).not.toHaveBeenCalledWith("deviceConsentAcknowledged", expect.anything());
    expect(useDeviceStore.getState().status).toBe("enrolled");
  });
});
