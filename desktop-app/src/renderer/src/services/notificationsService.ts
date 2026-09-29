import apiClient from "@shared/api-client";
import type { NotificationItem } from "../types/hrms";

export interface NotificationsPage {
  items: NotificationItem[];
  total: number;
  unread_count: number;
}

/** GET /notifications — always the caller's own inbox; there is no
 * "view someone else's notifications" mode on this backend endpoint. */
export async function listNotifications(unreadOnly = false): Promise<NotificationsPage> {
  const { data } = await apiClient.get<NotificationsPage>("/notifications", {
    params: { unread_only: unreadOnly, limit: 50 },
  });
  return data;
}

export async function getUnreadNotificationCount(): Promise<number> {
  const { data } = await apiClient.get<{ unread_count: number }>("/notifications/unread-count");
  return data.unread_count;
}

export async function markNotificationRead(id: string): Promise<void> {
  await apiClient.post(`/notifications/${id}/read`);
}

export async function markAllNotificationsRead(): Promise<void> {
  await apiClient.post("/notifications/read-all");
}
