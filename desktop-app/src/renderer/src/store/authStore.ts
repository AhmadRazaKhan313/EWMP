import { create } from "zustand";
import { login as loginRequest, getMe, logout as logoutRequest, hasStoredSession } from "../services/authService";
import { AUTH_FAILURE_EVENT } from "@shared/api-client";

/** Common shape both the login response's full UserInToken and the
 * smaller session-restore MeResponse satisfy — Phase 2's UI only needs
 * these fields. Role/permission-aware UI (later phases) will need a
 * fresh login or a richer /me endpoint to get roles back after restore. */
export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  avatar_url: string | null;
}

export type AuthStatus = "checking" | "authenticated" | "unauthenticated";

interface AuthState {
  status: AuthStatus;
  user: AuthUser | null;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  restoreSession: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: "checking",
  user: null,
  error: null,

  login: async (email: string, password: string): Promise<void> => {
    set({ error: null });
    try {
      const { user } = await loginRequest(email, password);
      set({ status: "authenticated", user, error: null });
    } catch (err) {
      const message = extractErrorMessage(err);
      set({ status: "unauthenticated", user: null, error: message });
      throw err;
    }
  },

  logout: async (): Promise<void> => {
    await logoutRequest();
    set({ status: "unauthenticated", user: null, error: null });
  },

  restoreSession: async (): Promise<void> => {
    const hasSession = await hasStoredSession();
    if (!hasSession) {
      set({ status: "unauthenticated" });
      return;
    }
    try {
      const me = await getMe();
      set({
        status: "authenticated",
        user: { id: me.id, email: me.email, full_name: me.full_name, avatar_url: me.avatar_url },
      });
    } catch {
      // The api-client's response interceptor already tried refreshing on
      // a 401 and clears tokens itself if that also failed (onAuthFailure)
      // — by the time we get here, there's genuinely no valid session left.
      set({ status: "unauthenticated", user: null });
    }
  },
}));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractErrorMessage(err: any): string {
  return err?.response?.data?.detail || err?.response?.data?.message || err?.message || "Login failed";
}

let authFailureListenerAttached = false;

/** Call once, near app startup — wires the api-client's auth-failure
 * event (refresh token also expired/invalid) to actually logging the
 * user out in the UI, not just clearing storage silently. */
export function attachAuthFailureListener(): void {
  if (authFailureListenerAttached) return;
  authFailureListenerAttached = true;
  window.addEventListener(AUTH_FAILURE_EVENT, () => {
    useAuthStore.setState({ status: "unauthenticated", user: null });
  });
}
