import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Check, CheckCheck, Inbox } from "lucide-react";
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "../services/notificationsService";
import { timeAgo } from "../lib/format";
import { Badge, Card, EmptyState, SkeletonList, cn } from "../components/ui";

/**
 * Notification inbox — GET /notifications, always the caller's own; there
 * is no "view someone else's" mode on this endpoint.
 *
 * Unread rows carry a left indigo bar plus an explicit "New" badge rather
 * than a tinted background alone. A background tint is invisible to
 * anyone who cannot distinguish it from white, and it also made read and
 * unread rows look like two different components.
 */
export default function NotificationsScreen(): JSX.Element {
  const queryClient = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);

  const query = useQuery({
    queryKey: ["notifications", "list", unreadOnly],
    queryFn: () => listNotifications(unreadOnly),
  });

  const markReadMutation = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  const markAllMutation = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  const items = query.data?.items ?? [];
  const unreadCount = query.data?.unread_count ?? 0;

  return (
    <div className="flex w-full flex-col gap-[18px] p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2.5 font-heading text-[22px] font-semibold tracking-tight text-[hsl(var(--foreground))]">
            Notifications
            {unreadCount > 0 && <Badge variant="warning">{unreadCount} unread</Badge>}
          </h1>
          <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
            Updates and alerts from your organisation
          </p>
        </div>

        <div className="flex items-center gap-4">
          <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-[hsl(var(--foreground-muted))]">
            <input
              type="checkbox"
              data-testid="unread-only-toggle"
              checked={unreadOnly}
              onChange={(e) => setUnreadOnly(e.target.checked)}
              className="h-4 w-4 accent-[hsl(var(--primary))]"
            />
            Unread only
          </label>
          <button
            data-testid="mark-all-read-button"
            onClick={() => markAllMutation.mutate()}
            disabled={markAllMutation.isPending || unreadCount === 0}
            className="flex items-center gap-1.5 rounded-[var(--radius-control)] border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-2 text-xs font-semibold text-[hsl(var(--primary))] transition-colors hover:bg-[hsl(var(--secondary))] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <CheckCheck size={14} />
            Mark all read
          </button>
        </div>
      </header>

      {query.isLoading && <SkeletonList rows={5} height="h-[74px]" />}

      {!query.isLoading && items.length === 0 && (
        <Card>
          <EmptyState
            icon={unreadOnly ? <Check size={20} /> : <Inbox size={20} />}
            title={unreadOnly ? "You're all caught up" : "No notifications yet"}
            body={
              unreadOnly
                ? "Nothing unread. Turn off the filter to see everything you've already read."
                : "Approvals, reminders and announcements from your organisation will land here."
            }
          />
        </Card>
      )}

      <ul data-testid="notifications-list" className="flex flex-col gap-2.5">
        {items.map((n) => (
          <li key={n.id} data-testid={`notification-item-${n.id}`}>
            <Card className="flex items-start gap-3.5">
              <span
                aria-hidden
                className={cn(
                  "mt-0.5 w-1 shrink-0 self-stretch rounded-full",
                  n.is_read ? "bg-[hsl(var(--border))]" : "bg-[hsl(var(--primary))]",
                )}
              />
              <span
                className={cn(
                  "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                  n.is_read
                    ? "bg-[hsl(var(--muted))] text-[hsl(var(--foreground-muted))]"
                    : "bg-[hsl(var(--secondary))] text-[hsl(var(--primary))]",
                )}
              >
                <Bell size={15} />
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p
                    className={cn(
                      "text-sm text-[hsl(var(--foreground))]",
                      n.is_read ? "font-medium" : "font-semibold",
                    )}
                  >
                    {n.title}
                  </p>
                  {!n.is_read && <Badge variant="info">New</Badge>}
                </div>
                {n.body && (
                  <p className="mt-1 text-xs leading-relaxed text-[hsl(var(--foreground-muted))]">{n.body}</p>
                )}
                <p className="mt-1.5 text-[11px] text-[hsl(var(--foreground-muted))]">{timeAgo(n.created_at)}</p>
              </div>

              {!n.is_read && (
                <button
                  data-testid={`mark-read-${n.id}`}
                  onClick={() => markReadMutation.mutate(n.id)}
                  disabled={markReadMutation.isPending}
                  className="flex shrink-0 items-center gap-1 rounded-[var(--radius-chip)] px-2.5 py-1.5 text-[11px] font-semibold text-[hsl(var(--primary))] transition-colors hover:bg-[hsl(var(--secondary))] disabled:opacity-50"
                >
                  <Check size={12} />
                  Mark read
                </button>
              )}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
