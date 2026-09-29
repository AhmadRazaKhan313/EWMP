"use client";

/**
 * Landing page for the link in every verification email
 * (`${FRONTEND_URL}/verify-email?token=…`).
 *
 * This page did not exist before (audit C-3): the emailed link was a 404, so
 * with REQUIRE_EMAIL_VERIFICATION on nobody could ever verify, and every
 * permission-gated screen answered EMAIL_NOT_VERIFIED forever.
 *
 * Works whether or not the visitor is signed in: signed-in users get their
 * profile refreshed (so the "verify your email" banner disappears) and are
 * sent to the dashboard; everyone else is pointed to the login page.
 */

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, CheckCircle2, Loader2, Shield } from "lucide-react";
import { authService } from "@/services/auth.service";
import { useAuthStore } from "@/store/auth.store";

type State = "verifying" | "done" | "error" | "missing";

function VerifyEmail() {
  const token = useSearchParams().get("token");
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const setUser = useAuthStore((s) => s.setUser);

  const [state, setState] = useState<State>(token ? "verifying" : "missing");
  const [error, setError] = useState<string | null>(null);

  // The token is single-use. React 18 dev mode runs effects twice, and the
  // second POST would fail with "invalid token" — turning a SUCCESSFUL
  // verification into an error screen. Guard so it's sent exactly once.
  const sent = useRef(false);

  useEffect(() => {
    if (!token || sent.current) return;
    sent.current = true;

    authService
      .verifyEmail(token)
      .then(async () => {
        setState("done");
        if (useAuthStore.getState().isAuthenticated) {
          try {
            setUser(await authService.getMe());
          } catch {
            /* the banner will just refresh on next navigation */
          }
        }
      })
      .catch((err: unknown) => {
        setError(
          (err as { response?: { data?: { message?: string } } })?.response?.data?.message ??
            "This verification link is invalid or has already been used.",
        );
        setState("error");
      });
  }, [token, setUser]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[hsl(var(--background-subtle))] px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <Shield size={18} />
          <span className="font-heading font-semibold">EWMP</span>
        </div>

        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-8 text-center shadow-[var(--shadow-md)]">
          {state === "verifying" && (
            <>
              <Loader2 className="mx-auto mb-3 animate-spin text-[hsl(var(--foreground-muted))]" size={28} />
              <p className="text-sm text-[hsl(var(--foreground-muted))]">Verifying your email…</p>
            </>
          )}

          {state === "done" && (
            <>
              <CheckCircle2 className="mx-auto mb-3 text-[hsl(var(--success))]" size={32} />
              <h1 className="font-heading text-lg font-semibold">Email verified</h1>
              <p className="mt-1 text-sm text-[hsl(var(--foreground-muted))]">
                Your email address is confirmed. You now have full access.
              </p>
              <Link
                href={isAuthenticated ? "/dashboard" : "/login"}
                className="mt-6 inline-flex h-9 items-center justify-center rounded-md bg-[hsl(var(--primary))] px-4 text-sm font-medium text-[hsl(var(--primary-foreground))]"
              >
                {isAuthenticated ? "Go to dashboard" : "Sign in"}
              </Link>
            </>
          )}

          {(state === "error" || state === "missing") && (
            <>
              <AlertTriangle className="mx-auto mb-3 text-[hsl(var(--warning))]" size={32} />
              <h1 className="font-heading text-lg font-semibold">Link not valid</h1>
              <p className="mt-1 text-sm text-[hsl(var(--foreground-muted))]">
                {state === "missing"
                  ? "This page needs the link from your verification email."
                  : error}
              </p>
              <p className="mt-3 text-xs text-[hsl(var(--foreground-muted))]">
                Only the most recent link works. Sign in and use “Resend email” on the
                banner at the top of the page to get a new one.
              </p>
              <Link
                href={isAuthenticated ? "/dashboard" : "/login"}
                className="mt-6 inline-flex h-9 items-center justify-center rounded-md border border-[hsl(var(--border))] px-4 text-sm font-medium"
              >
                {isAuthenticated ? "Back to dashboard" : "Sign in"}
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  // useSearchParams() must sit under a Suspense boundary in the App Router
  // (same pattern as reset-password/page.tsx).
  return (
    <Suspense fallback={null}>
      <VerifyEmail />
    </Suspense>
  );
}
