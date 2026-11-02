/**
 * Notifications API (the signed-in person's own inbox and on/off choices).
 * Shapes mirror backend/app/api/v1/notifications/router.py.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./api-client";

export interface NotificationItem {
  id: string;
  title: string;
  body: string | null;
  type: string; // leave | payroll | helpdesk | attendance | device_alert
  icon: string | null;
  action_url: string | null;
  metadata: Record<string, unknown>;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface NotificationsPage {
  items: NotificationItem[];
  total: number;
  unread_count: number;
}

export interface NotificationPreference {
  key: string;
  label: string;
  description: string;
  enabled: boolean;
}

const KEY = ["notifications"] as const;

/** The red number on the bell. Checked every 30 seconds. */
export function useUnreadCount() {
  return useQuery({
    queryKey: [...KEY, "unread"],
    queryFn: async () => (await apiClient.get<{ unread_count: number }>("/notifications/unread-count")).data.unread_count,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
}

/** The list shown in the bell's dropdown. Only fetched while it is open. */
export function useNotificationList(enabled: boolean, limit = 20) {
  return useQuery({
    queryKey: [...KEY, "list", limit],
    queryFn: async () => (await apiClient.get<NotificationsPage>("/notifications", { params: { limit } })).data,
    enabled,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => { await apiClient.post(`/notifications/${id}/read`); },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => { await apiClient.post("/notifications/read-all"); },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useNotificationPreferences() {
  return useQuery({
    queryKey: [...KEY, "preferences"],
    queryFn: async () =>
      (await apiClient.get<{ items: NotificationPreference[] }>("/notifications/preferences")).data.items,
  });
}

export function useUpdateNotificationPreference() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ key, enabled }: { key: string; enabled: boolean }) =>
      (await apiClient.put<{ items: NotificationPreference[] }>("/notifications/preferences", {
        preferences: { [key]: enabled },
      })).data.items,
    onSuccess: (items) => qc.setQueryData([...KEY, "preferences"], items),
  });
}

/** "just now", "5 min ago", "3 h ago", "2 d ago", else the date. */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} d ago`;
  return new Date(iso).toLocaleDateString("en-US", { day: "numeric", month: "short" });
}
