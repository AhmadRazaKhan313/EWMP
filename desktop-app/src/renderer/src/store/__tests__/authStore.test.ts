import { describe, it, expect, vi, beforeEach } from "vitest";
import { useAuthStore, attachAuthFailureListener } from "../authStore";
import * as authService from "../../services/authService";
import { AUTH_FAILURE_EVENT } from "@shared/api-client";

vi.mock("../../services/authService");

function resetStore(): void {
  useAuthStore.setState({ status: "checking", user: null, error: null });
}

describe("authStore.login", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  it("sets status=authenticated and stores the user on success", async () => {
    vi.mocked(authService.login).mockResolvedValue({
      user: {
        id: "u1", email: "a@b.com", first_name: "A", last_name: "B", full_name: "A B",
        avatar_url: null, is_platform_admin: false, organization_id: null,
        organization_slug: null, roles: [], permissions: [],
      },
    });

    await useAuthStore.getState().login("a@b.com", "pw");

    expect(useAuthStore.getState().status).toBe("authenticated");
    expect(useAuthStore.getState().user?.email).toBe("a@b.com");
    expect(useAuthStore.getState().error).toBeNull();
  });

  it("sets status=unauthenticated with an error message on failure", async () => {
    vi.mocked(authService.login).mockRejectedValue({
      response: { data: { detail: "Invalid credentials" } },
    });

    await expect(useAuthStore.getState().login("a@b.com", "wrong")).rejects.toBeTruthy();

    expect(useAuthStore.getState().status).toBe("unauthenticated");
    expect(useAuthStore.getState().error).toBe("Invalid credentials");
  });
});

describe("authStore.logout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  it("clears user and sets status=unauthenticated", async () => {
    useAuthStore.setState({ status: "authenticated", user: { id: "1", email: "a@b.com", full_name: "A", avatar_url: null } });
    vi.mocked(authService.logout).mockResolvedValue(undefined);

    await useAuthStore.getState().logout();

    expect(useAuthStore.getState().status).toBe("unauthenticated");
    expect(useAuthStore.getState().user).toBeNull();
  });
});

describe("authStore.restoreSession", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetStore();
  });

  it("goes straight to unauthenticated when no token is stored (no /me call)", async () => {
    vi.mocked(authService.hasStoredSession).mockResolvedValue(false);

    await useAuthStore.getState().restoreSession();

    expect(useAuthStore.getState().status).toBe("unauthenticated");
    expect(authService.getMe).not.toHaveBeenCalled();
  });

  it("restores an authenticated session when a token exists and /me succeeds", async () => {
    vi.mocked(authService.hasStoredSession).mockResolvedValue(true);
    vi.mocked(authService.getMe).mockResolvedValue({
      id: "u1", email: "a@b.com", first_name: "A", last_name: "B", full_name: "A B",
      avatar_url: null, is_platform_admin: false, is_2fa_enabled: false,
    });

    await useAuthStore.getState().restoreSession();

    expect(useAuthStore.getState().status).toBe("authenticated");
    expect(useAuthStore.getState().user?.full_name).toBe("A B");
  });

  it("falls back to unauthenticated when a stored token exists but /me fails (refresh also failed)", async () => {
    vi.mocked(authService.hasStoredSession).mockResolvedValue(true);
    vi.mocked(authService.getMe).mockRejectedValue(new Error("401"));

    await useAuthStore.getState().restoreSession();

    expect(useAuthStore.getState().status).toBe("unauthenticated");
    expect(useAuthStore.getState().user).toBeNull();
  });
});

describe("attachAuthFailureListener", () => {
  beforeEach(() => {
    resetStore();
  });

  it("logs the user out when the api-client dispatches an auth-failure event", () => {
    useAuthStore.setState({ status: "authenticated", user: { id: "1", email: "a@b.com", full_name: "A", avatar_url: null } });
    attachAuthFailureListener();

    window.dispatchEvent(new CustomEvent(AUTH_FAILURE_EVENT));

    expect(useAuthStore.getState().status).toBe("unauthenticated");
    expect(useAuthStore.getState().user).toBeNull();
  });
});
