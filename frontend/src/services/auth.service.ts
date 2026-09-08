/**
 * Auth API service.
 */

import apiClient, { clearTokens, setTokens, TOKEN_KEYS } from "./api-client";
import type { AuthResponse, MeResponse, TokenResponse } from "@/types";

export interface LoginPayload {
  email: string;
  password: string;
}

export interface RegisterPayload {
  org_name: string;
  org_slug: string;
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  timezone?: string;
  country?: string;
}

export const authService = {
  async login(payload: LoginPayload): Promise<AuthResponse> {
    const { data } = await apiClient.post<AuthResponse>("/auth/login", payload);
    // Save tokens + tenant_id
    setTokens(
      data.tokens.access_token,
      data.tokens.refresh_token,
      data.user.organization_id ?? undefined,
    );
    return data;
  },

  async register(payload: RegisterPayload): Promise<AuthResponse> {
    const { data } = await apiClient.post<AuthResponse>("/auth/register", payload);
    setTokens(
      data.tokens.access_token,
      data.tokens.refresh_token,
      data.user.organization_id ?? undefined,
    );
    return data;
  },

  async getMe(): Promise<MeResponse> {
    const { data } = await apiClient.get<MeResponse>("/auth/me");
    // Update tenant_id if available
    if (data.organization_id && typeof window !== "undefined") {
      localStorage.setItem(TOKEN_KEYS.TENANT_ID, data.organization_id);
    }
    return data;
  },

  async logout(): Promise<void> {
    try {
      await apiClient.post("/auth/logout");
    } finally {
      clearTokens();
    }
  },

  async refreshTokens(refreshToken: string): Promise<TokenResponse> {
    const { data } = await apiClient.post<TokenResponse>("/auth/refresh", {
      refresh_token: refreshToken,
    });
    setTokens(data.access_token, data.refresh_token);
    return data;
  },

  async forgotPassword(payload: { email: string }): Promise<void> {
    await apiClient.post("/auth/forgot-password", payload);
  },

  async resetPassword(payload: {
    token: string;
    new_password: string;
    confirm_password: string;
  }): Promise<void> {
    await apiClient.post("/auth/reset-password", payload);
  },

  async verifyEmail(token: string): Promise<void> {
    await apiClient.post("/auth/verify-email", { token });
  },

  async changePassword(payload: {
    current_password: string;
    new_password: string;
    confirm_password: string;
  }): Promise<void> {
    await apiClient.post("/auth/change-password", payload);
  },

  async updateProfile(payload: {
    first_name?: string;
    last_name?: string;
    phone?: string;
    bio?: string;
  }): Promise<MeResponse> {
    const { data } = await apiClient.patch<MeResponse>("/auth/me", payload);
    return data;
  },

  async uploadAvatar(file: File): Promise<{ avatar_url: string }> {
    const form = new FormData();
    form.append("file", file);
    const { data } = await apiClient.post<{ avatar_url: string }>("/auth/me/avatar", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data;
  },
};