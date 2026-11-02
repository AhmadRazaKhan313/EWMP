"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bell, Banknote, CalendarDays, Clock, Headphones, ShieldAlert, type LucideIcon,
} from "lucide-react";
import {
  timeAgo, useMarkAllRead, useMarkRead, useNotificationList, useUnreadCount,
  type NotificationItem,
} from "@/services/notifications.service";

const ICONS: Record<string, LucideIcon> = {
  leave: CalendarDays,
  payroll: Banknote,
  helpdesk: Headphones,
  attendance: Clock,
  device_alert: ShieldAlert,
};

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const unread = useUnreadCount();
  const list = useNotificationList(open);
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();

  const count = unread.data ?? 0;
  const items = list.data?.items ?? [];

  function openItem(n: NotificationItem) {
    if (!n.is_read) markRead.mutate(n.id);
    setOpen(false);
    if (n.action_url) router.push(n.action_url);
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={count > 0 ? `Notifications, ${count} unread` : "Notifications"}
        className="relative flex h-10 w-10 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] transition-colors hover:bg-[hsl(var(--background-subtle))] hover:text-[hsl(var(--foreground))]"
      >
        <Bell size={20} />
        {count > 0 && (
          <span className="absolute right-1 top-1 flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-[hsl(var(--destructive))] px-0.5 text-[9px] font-bold text-white">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-10 z-50 w-[22rem] max-w-[calc(100vw-2rem)] rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-lg">
            <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-4 py-3">
              <p className="text-sm font-semibold">Notifications</p>
              <button
                onClick={() => markAll.mutate()}
                disabled={count === 0 || markAll.isPending}
                className="text-xs font-medium text-[hsl(var(--primary))] hover:underline disabled:cursor-not-allowed disabled:opacity-40 disabled:no-underline"
              >
                Mark all read
              </button>
            </div>

            <div className="max-h-96 overflow-y-auto">
              {list.isLoading ? (
                <p className="px-4 py-6 text-center text-xs text-[hsl(var(--foreground-muted))]">Loading…</p>
              ) : list.isError ? (
                <p className="px-4 py-6 text-center text-xs text-[hsl(var(--destructive))]">Could not load notifications.</p>
              ) : items.length === 0 ? (
                <p className="px-4 py-8 text-center text-xs text-[hsl(var(--foreground-muted))]">You're all caught up.</p>
              ) : (
                items.map((n) => {
                  const Icon = ICONS[n.type] ?? Bell;
                  return (
                    <button
                      key={n.id}
                      onClick={() => openItem(n)}
                      className={`flex w-full items-start gap-3 border-b border-[hsl(var(--border))] px-4 py-3 text-left last:border-0 hover:bg-[hsl(var(--accent))] ${n.is_read ? "" : "bg-[hsl(var(--background-subtle))]"}`}
                    >
                      <Icon size={16} className="mt-0.5 shrink-0 text-[hsl(var(--foreground-muted))]" />
                      <div className="min-w-0 flex-1">
                        <p className={`text-sm ${n.is_read ? "" : "font-semibold"}`}>{n.title}</p>
                        {n.body && (
                          <p className="mt-0.5 line-clamp-2 text-xs text-[hsl(var(--foreground-muted))]">{n.body}</p>
                        )}
                        <p className="mt-1 text-[11px] text-[hsl(var(--foreground-muted))]">{timeAgo(n.created_at)}</p>
                      </div>
                      {!n.is_read && (
                        <span aria-label="Unread" className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[hsl(var(--primary))]" />
                      )}
                    </button>
                  );
                })
              )}
            </div>

            <button
              onClick={() => { setOpen(false); router.push("/settings?tab=notifications"); }}
              className="w-full border-t border-[hsl(var(--border))] px-4 py-2.5 text-center text-xs font-medium text-[hsl(var(--primary))] hover:bg-[hsl(var(--accent))]"
            >
              Notification settings
            </button>
          </div>
        </>
      )}
    </div>
  );
}
