import { describe, it, expect, vi, beforeEach } from "vitest";
import axios from "axios";
import { deviceService } from "../deviceService";

describe("deviceService.sendHeartbeat", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("is a no-op when no agentToken has been stored yet", async () => {
    vi.spyOn(window.ewmp.secureStore, "get").mockResolvedValue(null);
    const postSpy = vi.spyOn(axios, "post");

    await deviceService.sendHeartbeat();

    expect(postSpy).not.toHaveBeenCalled();
  });

  it("posts to /devices/heartbeat with the agent_token as Authorization — NOT via the shared apiClient", async () => {
    vi.spyOn(window.ewmp.secureStore, "get").mockImplementation(async (key: string) =>
      key === "agentToken" ? "agent-token-abc" : key === "serverUrl" ? "http://localhost:8000" : null,
    );
    const postSpy = vi.spyOn(axios, "post").mockResolvedValue({ data: { actions: [] } });

    await deviceService.sendHeartbeat();

    expect(postSpy).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/devices/heartbeat",
      {},
      expect.objectContaining({ headers: { Authorization: "Bearer agent-token-abc" } }),
    );
  });

  it("propagates a failed heartbeat rather than swallowing it silently", async () => {
    vi.spyOn(window.ewmp.secureStore, "get").mockImplementation(async (key: string) =>
      key === "agentToken" ? "agent-token-abc" : null,
    );
    vi.spyOn(axios, "post").mockRejectedValue(new Error("network down"));

    await expect(deviceService.sendHeartbeat()).rejects.toThrow("network down");
  });
});
