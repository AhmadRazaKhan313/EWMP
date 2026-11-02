import apiClient from "@shared/api-client";

export type BreakPhase = "none" | "upcoming" | "warning" | "active" | "over";

/** GET /break/me — what the server says about today's break for this employee. */
export interface BreakInfo {
  server_time: string;
  has_break: boolean;
  phase: BreakPhase;
  locked: boolean;
  unlocked_by_admin?: boolean;
  start: string | null;
  end: string | null;
  duration_minutes: number | null;
  request: { id: string; status: "pending" | "approved" | "denied"; reason: string | null } | null;
}

export const breakLockService = {
  getMine: async (): Promise<BreakInfo> => (await apiClient.get<BreakInfo>("/break/me")).data,
  requestUnlock: async (reason: string): Promise<void> => {
    await apiClient.post("/break/unlock-requests", { reason: reason.trim() || null });
  },
};
