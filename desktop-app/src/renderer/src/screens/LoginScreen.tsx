import { useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { useAuthStore } from "../store/authStore";
import AuthShell from "../components/AuthShell";

export default function LoginScreen(): JSX.Element {
  const login = useAuthStore((s) => s.login);
  const error = useAuthStore((s) => s.error);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await login(email, password);
    } catch {
      // error is already surfaced via the store's `error` field
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthShell step={3}>
      <div className="flex flex-col gap-8">
        <div>
          <h1 className="font-heading text-[26px] font-semibold text-[hsl(var(--foreground))]">Sign in</h1>
          <p className="mt-1.5 text-sm text-[hsl(var(--foreground-muted))]">
            Use your work email to continue to EWMP.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground-subtle))]">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoFocus
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3.5 py-2.5 text-sm outline-none transition-shadow focus:border-[hsl(var(--ring))] focus:ring-2 focus:ring-[hsl(var(--ring))]/30"
            />
          </div>
          <div>
            <label
              htmlFor="password"
              className="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground-subtle))]"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3.5 py-2.5 text-sm outline-none transition-shadow focus:border-[hsl(var(--ring))] focus:ring-2 focus:ring-[hsl(var(--ring))]/30"
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-[hsl(var(--destructive))]">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="mt-1 flex items-center justify-center gap-2 rounded-lg bg-[hsl(var(--primary))] py-2.5 text-sm font-semibold text-[hsl(var(--primary-foreground))] shadow-sm transition-colors hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
          >
            {isSubmitting && <Loader2 size={14} className="animate-spin" />}
            Sign in
          </button>
        </form>

        <button
          type="button"
          onClick={() => void handleChangeServer()}
          className="self-start text-sm text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
        >
          Wrong server? Change it
        </button>
      </div>
    </AuthShell>
  );
}

async function handleChangeServer(): Promise<void> {
  await window.ewmp.secureStore.delete("serverUrl");
  window.location.reload();
}
