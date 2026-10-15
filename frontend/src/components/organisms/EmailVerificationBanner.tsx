"use client";

/**
 * Shown across the dashboard while the signed-in user's email is unverified
 * AND the server enforces verification (`email_verification_required`,
 * from GET /auth/me — false in dev setups and for platform admins).
 *
 * Until they verify, every permission-gated API call answers
 * EMAIL_NOT_VERIFIED, so without this the app just looks broken. Audit C-3.
 */

import { useState } from "react";
import { MailWarning } from "lucide-react";
import { authService } from "@/services/auth.service";
import { useAuthStore } from "@/store/auth.store";

export function EmailVerificationBanner(): JSX.Element | null {
  const user = useAuthStore((s) => s.user);
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  if (!user || !user.email_verification_required || user.is_email_verified) return null;

  async function resend() {
    setStatus("sending");
    setMessage(null);
    try {
      const { message: msg } = await authService.resendVerification();
      setMessage(msg);
      setStatus("sent");
    } catch (err: unknown) {
      setMessage(
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ??
          "Couldn't send the email. Please try again in a few minutes.",
      );
      setStatus("error");
    }
  }

  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-[hsl(var(--warning)/0.3)] bg-[hsl(var(--warning)/0.1)] px-6 py-2 text-sm"
    >
      <MailWarning size={16} className="shrink-0 text-[hsl(var(--warning))]" />
      <span className="flex-1">
        <strong className="font-medium">Verify your email address.</strong>{" "}
        We sent a link to <span className="font-medium">{user.email}</span>. Most of the app
        stays locked until you open it.
        {message && (
          <span className="ml-1 text-[hsl(var(--foreground-muted))]">{message}</span>
        )}
      </span>
      <button
        type="button"
        onClick={resend}
        disabled={status === "sending" || status === "sent"}
        className="shrink-0 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1 text-xs font-medium disabled:opacity-60"
      >
        {status === "sending" ? "Sending…" : status === "sent" ? "Email sent" : "Resend email"}
      </button>
    </div>
  );
}
