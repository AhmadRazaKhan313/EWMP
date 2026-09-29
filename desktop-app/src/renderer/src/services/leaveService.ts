import apiClient from "@shared/api-client";
import type { LeaveApplyPayload, LeaveBalanceItem, LeaveRequestItem, LeaveType } from "../types/hrms";

/** GET /leave/types — active leave categories the org has configured
 * (Annual, Sick, Casual, ...). Read-only for a plain employee. */
export async function listLeaveTypes(): Promise<LeaveType[]> {
  const { data } = await apiClient.get<{ items: LeaveType[]; total: number }>("/leave/types");
  return data.items.filter((t) => t.is_active);
}

/** GET /leave/balances — no employee_id sent, so the backend self-scopes
 * to the caller's own employee record (see leave.py's _resolve_leave_employee). */
export async function getMyLeaveBalances(year?: number): Promise<LeaveBalanceItem[]> {
  const { data } = await apiClient.get<{ employee_id: string; year: number; items: LeaveBalanceItem[] }>(
    "/leave/balances",
    { params: year ? { year } : undefined },
  );
  return data.items;
}

/** GET /leave/requests — same self-scoping: a plain `leave.apply` holder
 * (no `leave.view`) only ever gets their own requests back regardless of
 * what's requested here, so no employee_id param is needed client-side. */
export async function getMyLeaveRequests(status?: LeaveRequestItem["status"]): Promise<LeaveRequestItem[]> {
  const { data } = await apiClient.get<{ items: LeaveRequestItem[]; total: number }>("/leave/requests", {
    params: status ? { status } : undefined,
  });
  return data.items;
}

/** POST /leave/requests — employee_id is deliberately omitted; the backend
 * resolves it to the caller's own employee record. */
export async function applyForLeave(payload: LeaveApplyPayload): Promise<{ id: string }> {
  const { data } = await apiClient.post<{ id: string }>("/leave/requests", payload);
  return data;
}
