/**
 * Auth store (Zustand).
 *
 * Single source of truth for authentication state.
 * Components read from here; never from localStorage directly.
 *
 * Hydration: On first render, AuthProvider calls store.initialize()
 * which reads the access token and loads /auth/me if valid.
 */

import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type { MeResponse } from "@/types";
import { authService } from "@/services/auth.service";
import { getAccessToken } from "@/services/api-client";

interface AuthState {
  user: MeResponse | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isInitialized: boolean;

  // Actions
  setUser: (user: MeResponse) => void;
  clearUser: () => void;
  initialize: () => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
  hasAnyPermission: (...permissions: string[]) => boolean;
  hasRole: (role: string) => boolean;
}

export const useAuthStore = create<AuthState>()(
  devtools(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      isInitialized: false,

      setUser: (user) =>
        set({ user, isAuthenticated: true, isLoading: false }),

      clearUser: () =>
        set({ user: null, isAuthenticated: false, isLoading: false }),

      initialize: async () => {
        // Avoid double-init
        if (get().isInitialized) return;

        const token = getAccessToken();
        if (!token) {
          set({ isInitialized: true, isLoading: false });
          return;
        }

        set({ isLoading: true });
        try {
          const user = await authService.getMe();
          // Save tenant_id to localStorage for API requests
          if (user.organization_id && typeof window !== "undefined") {
            localStorage.setItem("ewmp_tenant_id", user.organization_id);
          }
          set({ user, isAuthenticated: true });
        } catch {
          // Token invalid or expired — tokens already cleared by interceptor
          set({ user: null, isAuthenticated: false });
        } finally {
          set({ isLoading: false, isInitialized: true });
        }
      },

      logout: async () => {
        set({ isLoading: true });
        try {
          await authService.logout();
        } finally {
          set({
            user: null,
            isAuthenticated: false,
            isLoading: false,
          });
        }
      },

      hasPermission: (permission: string) => {
        const { user } = get();
        if (!user) return false;
        // is_platform_admin and has_full_access (org owner, or any
        // assigned role with is_super) both bypass the explicit
        // permissions list — mirrors the backend's User.has_permission().
        // Without this, a brand-new org's owner (whose "Owner" role is
        // is_super but carries no explicitly-assigned permission rows)
        // would see almost every sidebar item hidden despite having full
        // access on every actual API call.
        if (user.is_platform_admin || user.has_full_access) return true;
        return user.permissions.includes(permission);
      },

      hasAnyPermission: (...permissions: string[]) => {
        const { hasPermission } = get();
        return permissions.some((p) => hasPermission(p));
      },

      hasRole: (role: string) => {
        const { user } = get();
        if (!user) return false;
        return user.roles.includes(role);
      },
    }),
    { name: "ewmp-auth" },
  ),
);
