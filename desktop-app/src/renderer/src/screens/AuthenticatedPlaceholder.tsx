import { LogOut, RefreshCw } from "lucide-react";
import { useAuthStore } from "../store/authStore";
import { useDeviceStore } from "../store/deviceStore";
import CheckInWidget from "./CheckInWidget";

export default function AuthenticatedPlaceholder(): JSX.Element {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const deviceStatus = useDeviceStore((s) => s.status);
  const retryEnrollment = useDeviceStore((s) => s.retryEnrollment);

  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center gap-2 bg-[hsl(var(--background))] text-[hsl(var(--foreground))]">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[hsl(var(--primary))] font-heading text-base font-bold text-[hsl(var(--primary-foreground))]">
        {user?.full_name?.charAt(0)?.toUpperCase() ?? "?"}
      </div>
      <p className="font-heading text-sm font-semibold">{user?.full_name}</p>

      <CheckInWidget />

      {/* Non-blocking: enrollment failing (e.g. no employee record linked
          yet, or a transient network error) must never stop the employee
          from checking in/out — see deviceStore's "needs_finish" comment.
          This is the retry affordance for exactly that case. */}
      {(deviceStatus === "needs_finish" || deviceStatus === "enrolling") && (
        <button
          onClick={() => void retryEnrollment()}
          disabled={deviceStatus === "enrolling"}
          data-testid="finish-device-setup-button"
          className="flex items-center gap-1.5 text-xs text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))] disabled:opacity-60"
        >
          <RefreshCw size={12} className={deviceStatus === "enrolling" ? "animate-spin" : ""} />
          {deviceStatus === "enrolling" ? "Finishing device setup…" : "Finish device setup"}
        </button>
      )}

      <button
        onClick={() => void logout()}
        className="flex items-center gap-2 rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--accent))]"
      >
        <LogOut size={14} />
        Sign out
      </button>
    </div>
  );
}
