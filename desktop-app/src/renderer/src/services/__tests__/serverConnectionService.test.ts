import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import axios from "axios";
import { checkServerHealth, normalizeServerUrl } from "../serverConnectionService";

describe("normalizeServerUrl", () => {
  it("adds http:// when no scheme is given", () => {
    expect(normalizeServerUrl("192.168.1.50:8000")).toBe("http://192.168.1.50:8000");
  });

  it("leaves an explicit https:// scheme alone", () => {
    expect(normalizeServerUrl("https://ewmp.company.com")).toBe("https://ewmp.company.com");
  });

  it("strips a trailing slash", () => {
    expect(normalizeServerUrl("http://localhost:8000/")).toBe("http://localhost:8000");
  });

  it("trims whitespace", () => {
    expect(normalizeServerUrl("  192.168.1.50:8000  ")).toBe("http://192.168.1.50:8000");
  });
});

describe("checkServerHealth", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("returns ok when the server responds healthy", async () => {
    vi.spyOn(axios, "get").mockResolvedValue({ data: { status: "healthy" } });
    const result = await checkServerHealth("192.168.1.50:8000");
    expect(result.ok).toBe(true);
  });

  it("hits {base}/health, adding http:// if no scheme was given", async () => {
    const spy = vi.spyOn(axios, "get").mockResolvedValue({ data: { status: "healthy" } });
    await checkServerHealth("192.168.1.50:8000");
    expect(spy).toHaveBeenCalledWith("http://192.168.1.50:8000/health", expect.anything());
  });

  it("rejects an empty address without making a network call", async () => {
    const spy = vi.spyOn(axios, "get");
    const result = await checkServerHealth("   ");
    expect(result.ok).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("returns a clear message when the server is unreachable", async () => {
    vi.spyOn(axios, "isAxiosError").mockReturnValue(true);
    vi.spyOn(axios, "get").mockRejectedValue({ isAxiosError: true, code: "ECONNREFUSED" });
    const result = await checkServerHealth("192.168.1.50:8000");
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/could not reach/i);
  });

  it("returns a timeout-specific message on ECONNABORTED", async () => {
    vi.spyOn(axios, "isAxiosError").mockReturnValue(true);
    vi.spyOn(axios, "get").mockRejectedValue({ isAxiosError: true, code: "ECONNABORTED" });
    const result = await checkServerHealth("192.168.1.50:8000");
    expect(result.message).toMatch(/timed out/i);
  });

  it("flags a non-healthy status from a reachable server", async () => {
    vi.spyOn(axios, "get").mockResolvedValue({ data: { status: "degraded" } });
    const result = await checkServerHealth("192.168.1.50:8000");
    expect(result.ok).toBe(false);
  });
});
