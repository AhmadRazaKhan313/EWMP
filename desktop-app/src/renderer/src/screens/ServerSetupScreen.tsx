import { useState, type FormEvent } from "react";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { setServerBaseUrl } from "@shared/api-client";
import { checkServerHealth, normalizeServerUrl } from "../services/serverConnectionService";
import AuthShell from "../components/AuthShell";

interface ServerSetupScreenProps {
  onConnected: () => void;
}

export default function ServerSetupScreen({ onConnected }: ServerSetupScreenProps): JSX.Element {
  const [address, setAddress] = useState("");
  const [status, setStatus] = useState<"idle" | "checking" | "ok" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent): Promise<void> {
    e.preventDefault();
    setStatus("checking");
    setMessage(null);

    const result = await checkServerHealth(address);
    if (result.ok) {
      await setServerBaseUrl(normalizeServerUrl(address));
      setStatus("ok");
      setMessage(result.message);
      onConnected();
    } else {
      setStatus("error");
      setMessage(result.message);
    }
  }

  return (
    <AuthShell step={1}>
      <div className="flex flex-col gap-8">
        <div>
          <h1 className="font-heading text-[26px] font-semibold text-[hsl(var(--foreground))]">
            Connect to your server
          </h1>
          <p className="mt-1.5 text-sm text-[hsl(var(--foreground-muted))]">
            Ask your admin for the server address — something like{" "}
            <span className="font-mono text-[hsl(var(--foreground-subtle))]">192.168.1.50:8000</span> or{" "}
            <span className="font-mono text-[hsl(var(--foreground-subtle))]">ewmp.company.com</span>.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label
              htmlFor="server-address"
              className="mb-1.5 block text-sm font-medium text-[hsl(var(--foreground-subtle))]"
            >
              Server address
            </label>
            <input
              id="server-address"
              type="text"
              required
              autoFocus
              placeholder="192.168.1.50:8000"
              value={address}
              onChange={(e) => {
                setAddress(e.target.value);
                setStatus("idle");
              }}
              className="w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3.5 py-2.5 font-mono text-sm outline-none transition-shadow focus:border-[hsl(var(--ring))] focus:ring-2 focus:ring-[hsl(var(--ring))]/30"
            />
          </div>

          {message && (
            <p
              role="status"
              className={`flex items-center gap-1.5 text-sm ${
                status === "ok" ? "text-[hsl(var(--success))]" : "text-[hsl(var(--destructive))]"
              }`}
            >
              {status === "ok" ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
              {message}
            </p>
          )}

          <button
            type="submit"
            disabled={status === "checking" || status === "ok"}
            className="mt-1 flex items-center justify-center gap-2 rounded-lg bg-[hsl(var(--primary))] py-2.5 text-sm font-semibold text-[hsl(var(--primary-foreground))] shadow-sm transition-colors hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
          >
            {status === "checking" && <Loader2 size={14} className="animate-spin" />}
            {status === "checking" ? "Connecting…" : "Connect"}
          </button>
        </form>
      </div>
    </AuthShell>
  );
}
