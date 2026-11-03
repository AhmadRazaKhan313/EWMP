import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../../services/authService", () => ({
  login: vi.fn(), getMe: vi.fn(), logout: vi.fn(), hasStoredSession: vi.fn(),
}));
vi.mock("@shared/api-client", () => ({ AUTH_FAILURE_EVENT: "ewmp:auth-failure" }));

import * as authService from "../../services/authService";
import { useAuthStore } from "../authStore";

const ME = {
  id: "u1", email: "a@b.com", first_name: "A", last_name: "B", full_name: "A B", avatar_url: null,
  must_change_password: false,
};
const networkError = () => Object.assign(new Error("Network Error"), { isAxiosError: true, code: "ERR_NETWORK" });

describe("restoreSession when the computer has just started and the network is not up yet", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useAuthStore.setState({ status: "checking", user: null, error: null });
    vi.mocked(authService.hasStoredSession).mockResolvedValue(true);
  });
  afterEach(() => vi.useRealTimers());

  it("keeps the session and retries instead of dropping to the login screen", async () => {
    vi.mocked(authService.getMe).mockRejectedValueOnce(networkError()).mockRejectedValueOnce(networkError())
      .mockResolvedValue(ME as never);
    const p = useAuthStore.getState().restoreSession();
    await vi.advanceTimersByTimeAsync(0);
    expect(useAuthStore.getState().status).toBe("checking");
    await vi.advanceTimersByTimeAsync(15_000);
    expect(useAuthStore.getState().status).toBe("checking");
    await vi.advanceTimersByTimeAsync(15_000);
    await p;
    expect(useAuthStore.getState().status).toBe("authenticated");
    expect(authService.getMe).toHaveBeenCalledTimes(3);
  });

  it("a real rejection (server answered 401) still goes to login", async () => {
    vi.mocked(authService.getMe).mockRejectedValue(
      Object.assign(new Error("401"), { isAxiosError: true, response: { status: 401 } }));
    await useAuthStore.getState().restoreSession();
    expect(useAuthStore.getState().status).toBe("unauthenticated");
    expect(authService.getMe).toHaveBeenCalledTimes(1);
  });
});
