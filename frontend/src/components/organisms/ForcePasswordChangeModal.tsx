"use client";

/**
 * Shown as a blocking overlay whenever the logged-in user still has
 * `must_change_password: true` — i.e. they're on a randomly generated
 * temporary password (new employee, or a newly created org owner) and
 * haven't set their own password yet.
 *
 * Rendered from (dashboard)/layout.tsx, on top of everything else, with
 * no close/dismiss affordance — the only way out is a successful
 * password change, which flips `must_change_password` to false and
 * unmounts this.
 */

import { useState } from "react";
import { Loader2, ShieldAlert } from "lucide-react";
import { authService } from "@/services/auth.service";
import { useAuthStore } from "@/store/auth.store";
import { cn } from "@/utils/cn";

const inputClass =
  "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] outline-none focus:border-[hsl(var(--border-strong))]";

// FastAPI/Pydantic validation errors (422) return `detail` as an ARRAY of
// {loc, msg, type} objects, not a string — rendering that array directly
// as a React child crashes the component (blank screen, no error
// boundary). Flatten it into a readable string first.
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

  return (
    err?.response?.data?.message ||
    "Couldn't change password — check your current password and try again."
  );
}

export function ForcePasswordChangeModal(): JSX.Element {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (newPassword !== confirmPassword) {
      setError("New password and confirmation don't match.");
      return;
    }
    if (newPassword.length < 8) {
      setError("New password must be at least 8 characters.");
      return;
    }

    setIsSaving(true);
    try {
      await authService.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      // Refresh the profile so must_change_password (now false) and any
      // other server-side state stay in sync with the store.
      const me = await authService.getMe();
      setUser(me);
    } catch (err: unknown) {
      setError(extractErrorMessage(err));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 px-4 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-6 shadow-[var(--shadow-md)]">
        <div className="mb-4 flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]">
            <ShieldAlert size={18} />
          </div>
          <div>
            <h2 className="font-heading text-base font-semibold">
              Set a new password
            </h2>
            <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">
              {user?.first_name ? `Hi ${user.first_name}, ` : ""}
              you're signing in with a temporary password. Please set your own
              password before continuing.
            </p>
          </div>
        </div>

        <form onSubmit={onSubmit} className="space-y-3">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[hsl(var(--foreground-muted))]">
              Temporary / current password
            </label>
            <input
              type="password"
              autoComplete="current-password"
              className={inputClass}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[hsl(var(--foreground-muted))]">
              New password
            </label>
            <input
              type="password"
              autoComplete="new-password"
              className={inputClass}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
            />
            <p className="mt-1 text-[11px] text-[hsl(var(--foreground-subtle))]">
              At least 8 characters, with an uppercase letter, a lowercase
              letter, and a number.
            </p>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-[hsl(var(--foreground-muted))]">
              Confirm new password
            </label>
            <input
              type="password"
              autoComplete="new-password"
              className={inputClass}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>

          {error && (
            <p className="text-xs text-[hsl(var(--destructive))]">{error}</p>
          )}

          <button
            type="submit"
            disabled={isSaving}
            className={cn(
              "flex w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))] transition-colors",
              "hover:bg-[hsl(var(--primary-hover))]",
              "disabled:cursor-not-allowed disabled:opacity-60",
            )}
          >
            {isSaving && <Loader2 size={15} className="animate-spin" />}
            {isSaving ? "Updating..." : "Update password & continue"}
          </button>
        </form>
      </div>
    </div>
  );
}
