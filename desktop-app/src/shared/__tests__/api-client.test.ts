import { describe, it, expect, vi, beforeEach } from "vitest";
import axios from "axios";
import apiClient, { getAccessToken, setTokens, clearTokens, getServerBaseUrl, setServerBaseUrl, getServerUrl, hasServerConfigured } from "../api-client";

// Access axios's internal interceptor handler arrays directly — the
// standard way to unit-test interceptor logic without spinning up a real
// HTTP server. (Implementation detail of axios, but stable across 1.x.)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getRequestInterceptor(): any {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (apiClient.interceptors.request as any).handlers[0];
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getResponseInterceptor(): any {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (apiClient.interceptors.response as any).handlers[0];
}

describe("api-client — token storage goes through secureStore, never localStorage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("setTokens/getAccessToken round-trip through window.ewmp.secureStore", async () => {
    const store = new Map<string, string>();
    window.ewmp.secureStore.set = vi.fn(async (key, value) => {
      store.set(key, value);
    });
    window.ewmp.secureStore.get = vi.fn(async (key) => store.get(key) ?? null);

    await setTokens("access-123", "refresh-456");
    expect(await getAccessToken()).toBe("access-123");
    expect(window.ewmp.secureStore.set).toHaveBeenCalledWith("accessToken", "access-123");
  });

  it("clearTokens deletes all three keys via secureStore, not localStorage.clear", async () => {
    window.ewmp.secureStore.delete = vi.fn(async () => undefined);
    await clearTokens();
    expect(window.ewmp.secureStore.delete).toHaveBeenCalledWith("accessToken");
    expect(window.ewmp.secureStore.delete).toHaveBeenCalledWith("refreshToken");
    expect(window.ewmp.secureStore.delete).toHaveBeenCalledWith("tenantId");
  });

  it("never touches window.localStorage", async () => {
    const spy = vi.spyOn(Storage.prototype, "setItem");
    await setTokens("a", "b");
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("api-client — server URL configuration (multi-machine deployments)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("defaults to localhost when nothing is configured yet", async () => {
    window.ewmp.secureStore.get = vi.fn(async () => null);
    expect(await getServerBaseUrl()).toBe("http://localhost:8000");
    expect(await hasServerConfigured()).toBe(false);
  });

  it("getServerUrl appends /api/v1 to whatever base is configured", async () => {
    window.ewmp.secureStore.get = vi.fn(async () => "http://192.168.1.50:8000");
    expect(await getServerUrl()).toBe("http://192.168.1.50:8000/api/v1");
  });

  it("setServerBaseUrl strips a trailing slash before saving", async () => {
    const setSpy = vi.fn(async () => undefined);
    window.ewmp.secureStore.set = setSpy;
    await setServerBaseUrl("http://192.168.1.50:8000/");
    expect(setSpy).toHaveBeenCalledWith("serverUrl", "http://192.168.1.50:8000");
  });

  it("hasServerConfigured is true once a server URL is stored", async () => {
    window.ewmp.secureStore.get = vi.fn(async () => "http://192.168.1.50:8000");
    expect(await hasServerConfigured()).toBe(true);
  });
});

describe("api-client — request interceptor", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("attaches Authorization header when a token exists", async () => {
    window.ewmp.secureStore.get = vi.fn(async (key) =>
      key === "accessToken" ? "my-token" : null,
    );
    const config = await getRequestInterceptor().fulfilled({ headers: {} });
    expect(config.headers.Authorization).toBe("Bearer my-token");
  });

  it("does not attach Authorization header when no token exists", async () => {
    window.ewmp.secureStore.get = vi.fn(async () => null);
    const config = await getRequestInterceptor().fulfilled({ headers: {} });
    expect(config.headers.Authorization).toBeUndefined();
  });

  it("attaches X-Tenant-ID header when a tenant id is stored", async () => {
    window.ewmp.secureStore.get = vi.fn(async (key) =>
      key === "tenantId" ? "tenant-abc" : null,
    );
    const config = await getRequestInterceptor().fulfilled({ headers: {} });
    expect(config.headers["X-Tenant-ID"]).toBe("tenant-abc");
  });
});

describe("api-client — refresh flow (bug fixes vs. the web frontend)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Never let a retried request hit a real network call in this test
    // environment — only axios.post (the /auth/refresh call itself) is
    // mocked per-test below; the RETRY of the original request should
    // resolve instantly via this fake adapter instead of a real XHR.
    apiClient.defaults.adapter = async (config): Promise<import("axios").AxiosResponse> => ({
      data: {},
      status: 200,
      statusText: "OK",
      headers: {},
      config,
    });
  });

  it("reads the REFRESH response's flat access_token, never a nested tokens.access_token", async () => {
    window.ewmp.secureStore.get = vi.fn(async (key) =>
      key === "refreshToken" ? "old-refresh" : null,
    );
    const setSpy = vi.fn(async () => undefined);
    window.ewmp.secureStore.set = setSpy;

    vi.spyOn(axios, "post").mockResolvedValue({
      data: { access_token: "new-access", refresh_token: "new-refresh" },
    });

    const originalRequest = { url: "/employees", headers: {} };
    const error = { response: { status: 401 }, config: originalRequest };

    // The retry itself (`apiClient(originalRequest)`) makes a real network
    // call in this test environment (no server running), so its own
    // outcome isn't what we're checking here — what matters is that the
    // interceptor read the refresh response correctly before retrying.
    await getResponseInterceptor().rejected(error).catch(() => undefined);

    // The retried request must carry the NEW flat token, proving the
    // interceptor read `data.access_token` correctly (not `data.tokens.*`,
    // which would be `undefined` for this endpoint's actual shape).
    expect(setSpy).toHaveBeenCalledWith("accessToken", "new-access");
  });

  it("marks _retry on a QUEUED request too, not only the one that triggered the refresh", async () => {
    window.ewmp.secureStore.get = vi.fn(async (key) =>
      key === "refreshToken" ? "old-refresh" : null,
    );
    window.ewmp.secureStore.set = vi.fn(async () => undefined);

    let resolveRefresh: (v: unknown) => void = () => {};
    vi.spyOn(axios, "post").mockReturnValue(
      new Promise((resolve) => {
        resolveRefresh = resolve;
      }) as ReturnType<typeof axios.post>,
    );

    const rejected = getResponseInterceptor().rejected;

    // First 401 triggers the actual refresh (isRefreshing becomes true).
    const firstRequest = { url: "/employees", headers: {} };
    const firstPromise = rejected({ response: { status: 401 }, config: firstRequest });

    // A second, DIFFERENT request 401s while the refresh is still in flight
    // -> it must be queued, and THE BUG FIX: _retry must already be true.
    const secondRequest = { url: "/attendance", headers: {} };
    const secondPromise = rejected({ response: { status: 401 }, config: secondRequest });

    expect(secondRequest).toHaveProperty("_retry", true);

    resolveRefresh({ data: { access_token: "tok", refresh_token: "tok2" } });
    await firstPromise.catch(() => undefined);
    await secondPromise.catch(() => undefined);
  });

  it("does not retry a request that already has _retry set (prevents infinite loop)", async () => {
    const originalRequest = { url: "/employees", headers: {}, _retry: true };
    const error = { response: { status: 401 }, config: originalRequest };

    await expect(getResponseInterceptor().rejected(error)).rejects.toBe(error);
  });

  it("clears tokens and does not retry when the /auth/refresh call itself 401s", async () => {
    window.ewmp.secureStore.delete = vi.fn(async () => undefined);
    const originalRequest = { url: "/auth/refresh", headers: {} };
    const error = { response: { status: 401 }, config: originalRequest };

    await expect(getResponseInterceptor().rejected(error)).rejects.toBe(error);
    expect(window.ewmp.secureStore.delete).toHaveBeenCalledWith("accessToken");
  });

  it("passes through a 401 from /auth/login itself untouched — must not be mistaken for an expired-session refresh case", async () => {
    // Regression test: before this fix, a wrong-password 401 on the login
    // call itself fell through to the refresh branch below, found no
    // refreshToken (there's no session yet), and surfaced the misleading
    // "No refresh token available" instead of the real login error.
    window.ewmp.secureStore.get = vi.fn(async () => null); // no refresh token yet — nobody has logged in
    const getRefreshSpy = window.ewmp.secureStore.get;
    const originalRequest = { url: "/auth/login", headers: {} };
    const error = { response: { status: 401, data: { detail: "Invalid credentials" } }, config: originalRequest };

    await expect(getResponseInterceptor().rejected(error)).rejects.toBe(error);
    // Confirms it never entered the refresh path at all (which would have
    // read "refreshToken" from secureStore before throwing).
    expect(getRefreshSpy).not.toHaveBeenCalledWith("refreshToken");
  });

  it("passes through non-401 errors untouched", async () => {
    const error = { response: { status: 500 }, config: { url: "/x", headers: {} } };
    await expect(getResponseInterceptor().rejected(error)).rejects.toBe(error);
  });
});