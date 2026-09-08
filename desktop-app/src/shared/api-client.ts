/**
 * Centralized API client for the desktop app.
 *
 * Mirrors the web frontend's axios interceptor pattern
 * (frontend/src/services/api-client.ts), with two intentional differences:
 *
 * 1. Tokens live in the encrypted secureStore (via the preload bridge),
 *    never in localStorage/plain disk — see src/shared/secureStore.ts.
 *    That store is only reachable through async IPC calls, so token
 *    getters here are async where the web version's are synchronous.
 *
 * 2. Two bugs present in the web frontend's version are fixed here rather
 *    than reproduced, since this is new code:
 *      - Queued requests that were waiting on an in-flight refresh never
 *        got `_retry` set on their own config, so if the retried request
 *        also came back 401 it could re-enter the refresh flow a second
 *        time. Fixed by marking every request `_retry` before it's ever
 *        sent through the retry path, not just the one that triggered the
 *        refresh.
 *      - The login and refresh endpoints have different response shapes:
 *        POST /auth/login returns `{ tokens: { access_token, ... }, user }`
 *        (nested), but POST /auth/refresh returns `{ access_token, ... }`
 *        (flat) — see backend/app/schemas/auth.py's AuthResponse vs
 *        TokenResponse. This file only ever touches the flat /refresh
 *        shape, and does so correctly; whatever calls /auth/login (the
 *        Phase 2 login screen) must unwrap `data.tokens.*`, not
 *        `data.*` — noted here so that phase doesn't reintroduce the
 *        mismatch from a different angle.
 */
import axios, {
  type AxiosError,
  type AxiosRequestConfig,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";

const DEFAULT_SERVER_BASE_URL = "http://localhost:8000";

interface RetryableConfig extends AxiosRequestConfig {
  _retry?: boolean;
}

/** Raw server base (scheme + host + port), no /api/v1 suffix. Used for
 * health checks and as the source the API base is derived from. */
export async function getServerBaseUrl(): Promise<string> {
  const stored = await window.ewmp.secureStore.get("serverUrl");
  return (stored || DEFAULT_SERVER_BASE_URL).replace(/\/+$/, "");
}

export async function setServerBaseUrl(url: string): Promise<void> {
  await window.ewmp.secureStore.set("serverUrl", url.replace(/\/+$/, ""));
}

export async function hasServerConfigured(): Promise<boolean> {
  return (await window.ewmp.secureStore.get("serverUrl")) !== null;
}

/** The actual API base (raw server URL + /api/v1) — what apiClient and
 * the manual /auth/refresh call both use. */
export async function getServerUrl(): Promise<string> {
  const base = await getServerBaseUrl();
  return `${base}/api/v1`;
}

export async function getAccessToken(): Promise<string | null> {
  return window.ewmp.secureStore.get("accessToken");
}

export async function getRefreshToken(): Promise<string | null> {
  return window.ewmp.secureStore.get("refreshToken");
}

export async function getTenantId(): Promise<string | null> {
  return window.ewmp.secureStore.get("tenantId");
}

export async function setTokens(access: string, refresh: string, tenantId?: string | null): Promise<void> {
  await window.ewmp.secureStore.set("accessToken", access);
  await window.ewmp.secureStore.set("refreshToken", refresh);
  if (tenantId) {
    await window.ewmp.secureStore.set("tenantId", tenantId);
  }
}

export async function clearTokens(): Promise<void> {
  await window.ewmp.secureStore.delete("accessToken");
  await window.ewmp.secureStore.delete("refreshToken");
  await window.ewmp.secureStore.delete("tenantId");
}

// The runtime-configurable server URL means baseURL isn't known
// synchronously at module-init time, so it's set per-request in the
// interceptor rather than in axios.create().
const apiClient: AxiosInstance = axios.create({
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  if (!config.baseURL) {
    config.baseURL = await getServerUrl();
  }

  const token = await getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  const tenantId = await getTenantId();
  if (tenantId) {
    config.headers["X-Tenant-ID"] = tenantId;
  }

  return config;
});

// ── Refresh logic ────────────────────────────────────────────────────────
let isRefreshing = false;
let pendingRequests: Array<{
  resolve: (token: string) => void;
  reject: (error: unknown) => void;
}> = [];

function processPendingRequests(token: string | null, error: unknown): void {
  pendingRequests.forEach(({ resolve, reject }) => {
    if (token) resolve(token);
    else reject(error);
  });
  pendingRequests = [];
}

export const AUTH_FAILURE_EVENT = "ewmp:auth-failure";

async function onAuthFailure(): Promise<void> {
  await clearTokens();
  // Deliberately a plain DOM event rather than importing the Zustand auth
  // store directly — this file has no business knowing about React/Zustand.
  // The renderer's auth store (src/renderer/src/store/authStore.ts)
  // subscribes to this once, on app boot, and flips itself to logged-out.
  window.dispatchEvent(new CustomEvent(AUTH_FAILURE_EVENT));
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetryableConfig | undefined;

    if (!originalRequest || error.response?.status !== 401 || originalRequest._retry) {
      return Promise.reject(error);
    }

    // /auth/refresh's own 401 means the refresh token itself is dead —
    // log out. /auth/login's 401 means the *credentials* were wrong (most
    // backends, including ours, return 401 for bad email/password) — there
    // is no session yet at that point, so this must NEVER fall through to
    // the refresh-and-retry logic below. Without this second check, a
    // plain wrong-password attempt gets misreported as "No refresh token
    // available" instead of the real login error.
    if (originalRequest.url?.includes("/auth/refresh") || originalRequest.url?.includes("/auth/login")) {
      if (originalRequest.url?.includes("/auth/refresh")) {
        await onAuthFailure();
      }
      return Promise.reject(error);
    }

    // Fix vs. the web frontend: mark _retry on THIS request before it ever
    // goes through the queued-retry path, not only on the one request that
    // happens to trigger the actual refresh call. Without this, a queued
    // request whose retry also 401s could re-enter this whole branch again.
    originalRequest._retry = true;

    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        pendingRequests.push({
          resolve: (token) => {
            if (originalRequest.headers) {
              originalRequest.headers.Authorization = `Bearer ${token}`;
            }
            resolve(apiClient(originalRequest));
          },
          reject,
        });
      });
    }

    isRefreshing = true;

    try {
      const refreshToken = await getRefreshToken();
      if (!refreshToken) throw new Error("No refresh token available");

      const serverUrl = await getServerUrl();
      // Deliberately flat: POST /auth/refresh's response body IS
      // { access_token, refresh_token, token_type, expires_in } — no
      // `tokens` wrapper. That wrapper only exists on POST /auth/login's
      // response (AuthResponse vs TokenResponse in the backend schema).
      const { data } = await axios.post<{ access_token: string; refresh_token: string }>(
        `${serverUrl}/auth/refresh`,
        { refresh_token: refreshToken },
      );

      await setTokens(data.access_token, data.refresh_token);
      processPendingRequests(data.access_token, null);

      if (originalRequest.headers) {
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
      }
      return apiClient(originalRequest);
    } catch (refreshError) {
      processPendingRequests(null, refreshError);
      await onAuthFailure();
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  },
);

export default apiClient;