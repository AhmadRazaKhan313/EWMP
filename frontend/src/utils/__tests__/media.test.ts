/** Run:  cd frontend && npm test -- media */
import { describe, it, expect } from "vitest";
import { resolveMediaUrl } from "../media";

describe("resolveMediaUrl", () => {
  it("points an API path at the API server, not the website", () => {
    expect(resolveMediaUrl("/api/v1/auth/avatar/abc?v=1")).toBe("http://localhost:8000/api/v1/auth/avatar/abc?v=1");
  });

  it("leaves full, data and blob URLs alone", () => {
    expect(resolveMediaUrl("https://cdn.example.com/a.png")).toBe("https://cdn.example.com/a.png");
    expect(resolveMediaUrl("data:image/png;base64,AAA")).toBe("data:image/png;base64,AAA");
    expect(resolveMediaUrl("blob:http://x/1")).toBe("blob:http://x/1");
  });

  it("returns null when there is no picture", () => {
    expect(resolveMediaUrl(null)).toBeNull();
    expect(resolveMediaUrl(undefined)).toBeNull();
    expect(resolveMediaUrl("")).toBeNull();
  });
});
