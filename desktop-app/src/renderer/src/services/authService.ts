import apiClient, { setTokens, clearTokens, getAccessToken, getServerBaseUrl } from "@shared/api-client";
import type { AuthResponse, MeResponse, ProfileUpdatePayload, UserInToken } from "../types/auth";

export interface LoginResult {
  user: UserInToken;
}

/**
 * POST /auth/login. The response is NESTED (`{ tokens: {...}, user: {...} }`)
 * — unlike POST /auth/refresh, which is flat. This is the one place that
 * unwraps `data.tokens.*`, so nothing else in the app needs to know or
 * guess which shape applies to which endpoint.
 */
export async function login(email: string, password: string): Promise<LoginResult> {
  const { data } = await apiClient.post<AuthResponse>("/auth/login", { email, password });
  await setTokens(data.tokens.access_token, data.tokens.refresh_token, data.user.organization_id);
  return { user: data.user };
}

/** Validates the current session and returns a fresh (but smaller —
 * see MeResponse vs UserInToken) profile. Used on app boot to decide
 * whether a stored token is still good. */
export async function getMe(): Promise<MeResponse> {
  const { data } = await apiClient.get<MeResponse>("/auth/me");
  return data;
}

/** PATCH /auth/me — partial update; only the fields present in `payload`
 * are changed. Returns the full updated profile so the caller doesn't
 * need a separate re-fetch. */
export async function updateProfile(payload: ProfileUpdatePayload): Promise<MeResponse> {
  const { data } = await apiClient.patch<MeResponse>("/auth/me", payload);
  return data;
}

/** POST /auth/me/avatar (multipart) — backend caps this at 5MB and only
 * accepts PNG/JPEG/WebP; those same limits are enforced client-side first
 * in ProfileScreen so a bad file never makes a doomed round trip. */
export async function uploadAvatar(file: File): Promise<{ avatar_url: string }> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post<{ avatar_url: string }>("/auth/me/avatar", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/** avatar_url from the backend is a path (`/api/v1/auth/avatar/{id}`),
 * already including /api/v1 — so it's joined onto the raw server base,
 * NOT the /api/v1-suffixed API url (that would double it up). Serves
 * unauthenticated, so this works directly as an <img src>. */
export async function resolveAvatarUrl(avatarUrl: string | null): Promise<string | null> {
  if (!avatarUrl) return null;
  const base = await getServerBaseUrl();
  return `${base}${avatarUrl}`;
}

export async function logout(): Promise<void> {
  await clearTokens();
}

/** POST /auth/change-password — used by ChangePasswordScreen, both for
 * the forced first-login flow (must_change_password) and any later
 * voluntary password change. */
export async function changePassword(payload: {
  current_password: string;
  new_password: string;
  confirm_password: string;
}): Promise<void> {
  await apiClient.post("/auth/change-password", payload);
}

export async function hasStoredSession(): Promise<boolean> {
  return (await getAccessToken()) !== null;
}
