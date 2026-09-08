import { useState, type FormEvent } from "react";
import { Loader2, CheckCircle2, XCircle, Server } from "lucide-react";
import { setServerBaseUrl } from "@shared/api-client";
import { checkServerHealth, normalizeServerUrl } from "../services/serverConnectionService";

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
    <div className="flex h-screen w-screen flex-col items-center justify-center gap-6 bg-[hsl(var(--background))] px-8 text-[hsl(var(--foreground))]">
      <div className="flex flex-col items-center gap-2">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]">
          <Server size={20} />
        </div>
        <h1 className="font-heading text-lg font-semibold">Connect to your EWMP server</h1>
        <p className="max-w-[280px] text-center text-xs text-[hsl(var(--foreground-muted))]">
          Ask your admin for the server address (e.g. 192.168.1.50:8000 or ewmp.company.com).
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex w-full max-w-xs flex-col gap-3">
        <div>
          <label htmlFor="server-address" className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-subtle))]">
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
            className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
          />
        </div>

        {message && (
          <p
            role="status"
            className={`flex items-center gap-1.5 text-xs ${
              status === "ok" ? "text-[hsl(var(--success))]" : "text-[hsl(var(--destructive))]"
            }`}
          >
            {status === "ok" ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
            {message}
          </p>
        )}

        <button
          type="submit"
          disabled={status === "checking" || status === "ok"}
          className="mt-2 flex items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] transition-colors hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
        >
          {status === "checking" && <Loader2 size={14} className="animate-spin" />}
          {status === "checking" ? "Connecting…" : "Connect"}
        </button>
      </form>
    </div>
  );
}
