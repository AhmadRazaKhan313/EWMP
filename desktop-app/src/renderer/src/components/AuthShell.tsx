import type { ReactNode } from "react";
import ClockMotif from "./ClockMotif";

const STEPS = ["Connect", "Consent", "Sign in"];

/**
 * Shared full-desktop-size shell for the onboarding sequence (server
 * setup → consent → login) — see main/index.ts's BrowserWindow, which is
 * now sized like an actual desktop app (1280×800, min 1024×700), not the
 * 420×640 phone-widget size this used to render at. Every screen in the
 * sequence keeps the SAME left brand panel so the whole flow reads as one
 * continuous experience rather than three different screens bolted
 * together — only the right-hand content pane, and which step is lit up
 * below, change.
 *
 * `step` is optional (1-indexed into STEPS) — only the flow itself
 * (App.tsx) knows where in server-setup/consent/login someone currently
 * is, so those screens pass it through; a screen shown standalone (tests,
 * Storybook-style usage) just omits it and no progress bar renders.
 */
export default function AuthShell({
  children,
  step,
  wide = false,
}: {
  children: ReactNode;
  step?: 1 | 2 | 3;
  /** ConsentNotice's disclosure list needs more breathing room than the
   * compact login/server-address forms — everything else stays at the
   * narrower default so short forms don't stretch into awkwardly long
   * input lines. */
  wide?: boolean;
}): JSX.Element {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[hsl(var(--background))]">
      <aside
        className="relative flex w-[440px] shrink-0 flex-col justify-between overflow-hidden px-10 py-10"
        style={{
          background: "linear-gradient(160deg, hsl(var(--auth-ink)) 0%, hsl(var(--auth-ink-2)) 100%)",
        }}
      >
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-[hsl(var(--auth-ink-border))] bg-white/5 font-heading text-sm font-semibold text-white">
            E
          </div>
          <span className="font-heading text-sm font-semibold tracking-tight text-white">EWMP</span>
        </div>

        <div className="flex flex-1 items-center justify-center py-8">
          <ClockMotif size={260} />
        </div>

        <div className="flex flex-col gap-4">
          <p className="max-w-[280px] font-heading text-xl font-medium leading-snug text-white">
            Every clock-in, accounted for.
          </p>
          <p className="text-sm leading-relaxed text-white/50">
            Attendance, leave, and payroll — run from one place your whole team already trusts.
          </p>

          {step && (
            <ol className="mt-2 flex items-center gap-3">
              {STEPS.map((label, i) => {
                const n = i + 1;
                const state = n === step ? "current" : n < step ? "done" : "upcoming";
                return (
                  <li key={label} className="flex items-center gap-2">
                    <span
                      className={`h-1 w-6 rounded-full transition-colors ${
                        state === "upcoming" ? "bg-white/15" : "bg-[hsl(var(--auth-accent))]"
                      }`}
                    />
                    <span
                      className={`text-xs ${
                        state === "current" ? "text-white" : "text-white/40"
                      }`}
                    >
                      {label}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </aside>

      <main className="flex flex-1 items-center justify-center px-16">
        <div className={`w-full ${wide ? "max-w-[520px]" : "max-w-[400px]"}`}>{children}</div>
      </main>
    </div>
  );
}
