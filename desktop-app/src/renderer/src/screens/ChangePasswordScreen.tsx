import { useState, type FormEvent } from "react";
import { Loader2, ShieldAlert } from "lucide-react";
import { changePassword } from "../services/authService";
import { useAuthStore } from "../store/authStore";

/**
 * Rendered by App.tsx instead of AuthenticatedPlaceholder/ConsentNotice
 * whenever the signed-in user still has `must_change_password: true` —
 * i.e. they logged in with a randomly generated temporary password
 * (new employee, or a newly created org owner) and haven't set their
 * own password yet. There is no way to skip or dismiss this screen; the
 * only way past it is a successful password change.
 */
export default function ChangePasswordScreen(): JSX.Element {
  const user = useAuthStore((s) => s.user);
  const clearMustChangePassword = useAuthStore((s) => s.clearMustChangePassword);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent): Promise<void> {
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

    setIsSubmitting(true);
    try {
      await changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      clearMustChangePassword();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center gap-6 bg-[hsl(var(--background))] px-8 text-[hsl(var(--foreground))]">
      <div className="flex flex-col items-center gap-2 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]">
          <ShieldAlert size={22} />
        </div>
        <h1 className="font-heading text-lg font-semibold">Set a new password</h1>
        <p className="max-w-xs text-xs text-[hsl(var(--foreground-muted))]">
          {user?.full_name ? `Hi ${user.full_name}, ` : ""}
          you're signing in with a temporary password. Please set your own
          password before continuing.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex w-full max-w-xs flex-col gap-3">
        <div>
          <label htmlFor="currentPassword" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">
            Temporary / current password
          </label>
          <input
            id="currentPassword"
            type="password"
            required
            autoFocus
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>
        <div>
          <label htmlFor="newPassword" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">
            New password
          </label>
          <input
            id="newPassword"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
          <p className="mt-1 text-[11px] text-[hsl(var(--foreground-subtle))]">
            At least 8 characters, with an uppercase letter, a lowercase letter, and a number.
          </p>
        </div>
        <div>
          <label htmlFor="confirmPassword" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">
            Confirm new password
          </label>
          <input
            id="confirmPassword"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>

        {error && (
          <p role="alert" className="text-xs text-[hsl(var(--destructive))]">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="mt-2 flex items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] transition-colors hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
        >
          {isSubmitting && <Loader2 size={14} className="animate-spin" />}
          Update password & continue
        </button>
      </form>
    </div>
  );
}

// FastAPI/Pydantic validation errors (422) return `detail` as an ARRAY of
// {loc, msg, type} objects, not a string — rendering that array directly
// as a React child crashes the screen (blank white screen, no error
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
    err?.message ||
    "Couldn't change password — check your current password and try again."
  );
}
