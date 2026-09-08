import { describe, it, expect, vi, beforeEach } from "vitest";
import apiClient, { setTokens, clearTokens, getAccessToken } from "@shared/api-client";
import { login, getMe, logout, hasStoredSession } from "../authService";

vi.mock("@shared/api-client", () => ({
  default: { post: vi.fn(), get: vi.fn() },
  setTokens: vi.fn(),
  clearTokens: vi.fn(),
  getAccessToken: vi.fn(),
}));

describe("authService.login", () => {
  beforeEach(() => vi.clearAllMocks());

  it("unwraps the NESTED tokens object from POST /auth/login (not a flat shape)", async () => {
    (apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        tokens: { access_token: "acc-1", refresh_token: "ref-1", token_type: "bearer", expires_in: 900 },
        user: {
          id: "u1", email: "a@b.com", first_name: "A", last_name: "B", full_name: "A B",
          avatar_url: null, is_platform_admin: false, organization_id: "org-1",
          organization_slug: "acme", roles: [], permissions: [],
        },
      },
    });

    const result = await login("a@b.com", "pw");

    expect(apiClient.post).toHaveBeenCalledWith("/auth/login", { email: "a@b.com", password: "pw" });
    // THE assertion: tokens came from data.tokens.*, not data.*
    expect(setTokens).toHaveBeenCalledWith("acc-1", "ref-1", "org-1");
    expect(result.user.email).toBe("a@b.com");
  });

  it("propagates a login failure without calling setTokens", async () => {
    (apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { status: 401, data: { detail: "Invalid credentials" } },
    });

    await expect(login("a@b.com", "wrong")).rejects.toBeTruthy();
    expect(setTokens).not.toHaveBeenCalled();
  });
});

describe("authService.getMe", () => {
  beforeEach(() => vi.clearAllMocks());

  it("calls GET /auth/me and returns the flat profile", async () => {
    (apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { id: "u1", email: "a@b.com", first_name: "A", last_name: "B", full_name: "A B", avatar_url: null, is_platform_admin: false, is_2fa_enabled: false },
    });
    const me = await getMe();
    expect(apiClient.get).toHaveBeenCalledWith("/auth/me");
    expect(me.email).toBe("a@b.com");
  });
});

describe("authService.logout / hasStoredSession", () => {
  beforeEach(() => vi.clearAllMocks());

  it("logout clears tokens via secureStore, not localStorage", async () => {
    await logout();
    expect(clearTokens).toHaveBeenCalled();
  });

  it("hasStoredSession is true only when an access token exists", async () => {
    (getAccessToken as ReturnType<typeof vi.fn>).mockResolvedValueOnce("tok");
    expect(await hasStoredSession()).toBe(true);

    (getAccessToken as ReturnType<typeof vi.fn>).mockResolvedValueOnce(null);
    expect(await hasStoredSession()).toBe(false);
  });
});
