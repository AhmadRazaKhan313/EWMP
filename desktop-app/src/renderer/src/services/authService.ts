import apiClient, { setTokens, clearTokens, getAccessToken } from "@shared/api-client";
import type { AuthResponse, MeResponse, UserInToken } from "../types/auth";

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

export async function logout(): Promise<void> {
  await clearTokens();
}

export async function hasStoredSession(): Promise<boolean> {
  return (await getAccessToken()) !== null;
}
