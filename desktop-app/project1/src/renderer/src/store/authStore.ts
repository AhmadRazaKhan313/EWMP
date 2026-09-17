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
  must_change_password: boolean;
}

export type AuthStatus = "checking" | "authenticated" | "unauthenticated";

interface AuthState {
  status: AuthStatus;
  user: AuthUser | null;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  restoreSession: () => Promise<void>;
  /** Called after a successful forced password change so the app can
   * leave the ChangePasswordScreen without another round-trip. */
  clearMustChangePassword: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: "checking",
  user: null,
  error: null,

  login: async (email: string, password: string): Promise<void> => {
    set({ error: null });
    try {
      const { user } = await loginRequest(email, password);
      set({
        status: "authenticated",
        user: {
          id: user.id,
          email: user.email,
          full_name: user.full_name,
          avatar_url: user.avatar_url,
          must_change_password: user.must_change_password,
        },
        error: null,
      });
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
        user: {
          id: me.id,
          email: me.email,
          full_name: me.full_name,
          avatar_url: me.avatar_url,
          must_change_password: me.must_change_password,
        },
      });
    } catch {
      // The api-client's response interceptor already tried refreshing on
      // a 401 and clears tokens itself if that also failed (onAuthFailure)
      // — by the time we get here, there's genuinely no valid session left.
      set({ status: "unauthenticated", user: null });
    }
  },

  clearMustChangePassword: (): void => {
    set((state) => (state.user ? { user: { ...state.user, must_change_password: false } } : {}));
  },
}));

// FastAPI/Pydantic validation errors (422) return `detail` as an ARRAY of
// {loc, msg, type} objects, not a string — assigning that straight into
// `error` and rendering it as a React child crashes the screen (blank
// screen, no error boundary). Flatten it into a readable string first.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractErrorMessage(err: any): string {
  const detail = err?.response?.data?.detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d: { msg?: string }) => d?.msg)
      .filter((m: unknown): m is string => typeof m === "string" && m.length > 0);
    if (messages.length > 0) return messages.join(" ");
  }
  if (typeof detail === "string" && detail.length > 0) return detail;
  return err?.response?.data?.message || err?.message || "Login failed";
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
