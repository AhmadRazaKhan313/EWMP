import { Loader2, ShieldCheck, Camera, MessageSquare, Activity } from "lucide-react";
import { useDeviceStore } from "../store/deviceStore";
import AuthShell from "../components/AuthShell";

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
    <AuthShell step={2} wide>
      <div className="flex flex-col gap-8">
        <div>
          <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-[hsl(var(--accent))] text-[hsl(var(--primary))]">
            <ShieldCheck size={20} />
          </div>
          <h1 className="font-heading text-[26px] font-semibold text-[hsl(var(--foreground))]">
            Device monitoring notice
          </h1>
          <p className="mt-1.5 text-sm text-[hsl(var(--foreground-muted))]">
            This computer is managed by your organization's IT department using the EWMP desktop app. While active,
            it may:
          </p>
        </div>

        <ul className="flex flex-col gap-4">
          <ConsentItem icon={<Activity size={16} />} title="Report hardware/performance metrics">
            CPU, RAM, disk, and battery — used to keep company devices healthy.
          </ConsentItem>
          <ConsentItem icon={<MessageSquare size={16} />} title="Allow IT to remotely lock, restart, or message you">
            Standard fleet-management actions, always visible when they happen.
          </ConsentItem>
          <ConsentItem icon={<Camera size={16} />} title="Capture a screenshot — only on explicit request">
            Never continuously — only when an administrator explicitly requests one.
          </ConsentItem>
          <ConsentItem icon={<ShieldCheck size={16} />} title="Flag visits to a small non-work watch-list">
            Only flagged matches are reported for workplace-policy purposes — not a full browsing or activity
            history.
          </ConsentItem>
        </ul>

        <p className="text-xs leading-relaxed text-[hsl(var(--foreground-muted))]">
          A tray icon is shown at all times while this app is running. Contact your IT/HR department for your
          organization's full device-monitoring policy.
        </p>

        {error && (
          <p role="alert" className="text-sm text-[hsl(var(--destructive))]">
            {error} — you can keep using the app; device setup will retry.
          </p>
        )}

        <button
          onClick={() => void acknowledgeAndEnroll()}
          disabled={isEnrolling}
          data-testid="consent-acknowledge-button"
          className="flex items-center justify-center gap-2 rounded-lg bg-[hsl(var(--primary))] py-2.5 text-sm font-semibold text-[hsl(var(--primary-foreground))] shadow-sm transition-colors hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
        >
          {isEnrolling && <Loader2 className="animate-spin" size={16} />}
          I Understand, Continue
        </button>
      </div>
    </AuthShell>
  );
}

function ConsentItem({
  icon,
  title,
  children,
}: {
  icon: JSX.Element;
  title: string;
  children: string;
}): JSX.Element {
  return (
    <li className="flex gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--muted))] text-[hsl(var(--foreground-subtle))]">
        {icon}
      </div>
      <div>
        <p className="text-sm font-medium text-[hsl(var(--foreground))]">{title}</p>
        <p className="mt-0.5 text-sm leading-relaxed text-[hsl(var(--foreground-muted))]">{children}</p>
      </div>
    </li>
  );
}
