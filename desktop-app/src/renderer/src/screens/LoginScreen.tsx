import { useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { useAuthStore } from "../store/authStore";

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
    <div className="flex h-screen w-screen flex-col items-center justify-center gap-6 bg-[hsl(var(--background))] px-8 text-[hsl(var(--foreground))]">
      <div className="flex flex-col items-center gap-2">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[hsl(var(--primary))] font-heading text-lg font-bold text-[hsl(var(--primary-foreground))]">
          E
        </div>
        <h1 className="font-heading text-lg font-semibold">Sign in to EWMP</h1>
      </div>

      <form onSubmit={handleSubmit} className="flex w-full max-w-xs flex-col gap-3">
        <div>
          <label htmlFor="email" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>
        <div>
          <label htmlFor="password" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
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
          Sign in
        </button>
      </form>

      <button
        type="button"
        onClick={() => void handleChangeServer()}
        className="text-xs text-[hsl(var(--foreground-muted))] underline hover:text-[hsl(var(--foreground))]"
      >
        Wrong server? Change it
      </button>
    </div>
  );
}

async function handleChangeServer(): Promise<void> {
  await window.ewmp.secureStore.delete("serverUrl");
  window.location.reload();
}
