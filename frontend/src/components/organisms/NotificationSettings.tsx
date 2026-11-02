"use client";

import { Card } from "@/components/atoms";
import { apiErrorText } from "@/utils/api-error";
import { toast } from "sonner";
import {
  useNotificationPreferences, useUpdateNotificationPreference,
} from "@/services/notifications.service";

export function NotificationSettings() {
  const prefs = useNotificationPreferences();
  const update = useUpdateNotificationPreference();

  function toggle(key: string, enabled: boolean) {
    update.mutate(
      { key, enabled },
      { onError: (e) => toast.error(apiErrorText(e, "Could not save your choice.")) },
    );
  }

  return (
    <Card padding={false}>
      <div className="border-b border-[hsl(var(--border))] px-6 py-5">
        <h2 className="font-heading text-base font-semibold">Notifications</h2>
        <p className="mt-1 text-sm text-[hsl(var(--foreground-muted))]">
          Choose what shows up in your bell. These choices are only for your own account.
        </p>
      </div>

      {prefs.isLoading && <p className="px-6 py-6 text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>}
      {prefs.isError && (
        <p className="px-6 py-6 text-sm text-[hsl(var(--destructive))]">
          {apiErrorText(prefs.error, "Could not load your notification settings.")}
        </p>
      )}

      <ul>
        {(prefs.data ?? []).map((p) => (
          <li key={p.key} className="flex items-center justify-between gap-6 border-b border-[hsl(var(--border))] px-6 py-4 last:border-0">
            <div>
              <p className="text-sm font-medium">{p.label}</p>
              <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">{p.description}</p>
            </div>
            <button
              role="switch"
              aria-checked={p.enabled}
              aria-label={p.label}
              onClick={() => toggle(p.key, !p.enabled)}
              className={`relative h-6 w-11 shrink-0 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[hsl(var(--brand-100))] ${p.enabled ? "bg-[hsl(var(--primary))]" : "bg-[hsl(var(--border-strong))]"}`}
            >
              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${p.enabled ? "left-[22px]" : "left-0.5"}`} />
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
