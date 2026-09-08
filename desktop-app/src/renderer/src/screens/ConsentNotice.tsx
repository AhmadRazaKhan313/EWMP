import { Loader2, Monitor } from "lucide-react";
import { useDeviceStore } from "../store/deviceStore";

/**
 * Shown exactly once per install, before an employee's device is ever
 * self-enrolled — see backend's SelfEnrollRequest.consent_acknowledged,
 * which this screen exists to make true.
 *
 * Content deliberately mirrors agent/ewmp_agent.py's CONSENT_NOTICE
 * (same disclosures, same "flagged-only, not full history" framing) —
 * this is the desktop-app's answer to that script's own noted gap: a
 * one-line console print isn't a real disclosure mechanism, and some
 * jurisdictions require an explicit acknowledgment click. This is that
 * click. It is still not a substitute for your organization's own
 * written monitoring policy — see DeviceAlert's model docstring on the
 * backend for the compliance note this mirrors.
 */
export default function ConsentNotice(): JSX.Element {
  const status = useDeviceStore((s) => s.status);
  const error = useDeviceStore((s) => s.error);
  const acknowledgeAndEnroll = useDeviceStore((s) => s.acknowledgeAndEnroll);
  const isEnrolling = status === "enrolling";

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-[hsl(var(--background))] p-6">
      <div className="flex max-w-md flex-col gap-4 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 text-[hsl(var(--foreground))] shadow-lg">
        <div className="flex items-center gap-2">
          <Monitor size={20} className="text-[hsl(var(--primary))]" />
          <h1 className="font-heading text-base font-semibold">Device Monitoring Notice</h1>
        </div>

        <p className="text-sm text-[hsl(var(--foreground-muted))]">
          This computer is managed by your organization's IT department using the EWMP desktop app. While active, it
          may:
        </p>

        <ul className="list-disc space-y-1 pl-5 text-sm text-[hsl(var(--foreground-muted))]">
          <li>Report hardware/performance metrics (CPU, RAM, disk, battery)</li>
          <li>Allow IT to remotely lock, restart, or send you a message</li>
          <li>
            Capture a screenshot <strong>only</strong> when an administrator explicitly requests one — never
            continuously or without a specific request
          </li>
          <li>
            Flag when this device visits a small watch-list of known non-work websites or has certain applications in
            focus, for workplace-policy purposes — only flagged matches are reported, <strong>not</strong> a full
            browsing or activity history
          </li>
        </ul>

        <p className="text-xs text-[hsl(var(--foreground-muted))]">
          A tray icon is shown at all times while this app is running. Contact your IT/HR department for your
          organization's full device-monitoring policy.
        </p>

        {error && (
          <p role="alert" className="text-xs text-[hsl(var(--destructive))]">
            {error} — you can keep using the app; device setup will retry.
          </p>
        )}

        <button
          onClick={() => void acknowledgeAndEnroll()}
          disabled={isEnrolling}
          data-testid="consent-acknowledge-button"
          className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl bg-[hsl(var(--primary))] py-3 text-sm font-semibold text-[hsl(var(--primary-foreground))] shadow-md transition-colors hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
        >
          {isEnrolling && <Loader2 className="animate-spin" size={16} />}
          I Understand, Continue
        </button>
      </div>
    </div>
  );
}
