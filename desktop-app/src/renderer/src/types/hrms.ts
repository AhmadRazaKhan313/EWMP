/**
 * Mirrors backend/app/api/v1/hrms/{leave,holidays,notifications,work_sessions}.py
 * response shapes — kept in sync manually, same convention as types/auth.ts.
 */

// ── Leave ────────────────────────────────────────────────────────────────

export interface LeaveType {
  id: string;
  name: string;
  code: string;
  color: string;
  days_per_year: string;
  is_paid: boolean;
  requires_approval: boolean;
  requires_document: boolean;
  is_carry_forward: boolean;
  is_active: boolean;
}

export interface LeaveBalanceItem {
  leave_type_id: string;
  leave_type_name: string;
  leave_type_color: string;
  year: number;
  entitled_days: number;
  carried_forward_days: number;
  used_days: number;
  pending_days: number;
  remaining_days: number;
}

export type LeaveRequestStatus = "pending" | "approved" | "rejected";

export interface LeaveRequestItem {
  id: string;
  employee_id: string;
  employee_name: string;
  leave_type: string;
  leave_type_color: string;
  start_date: string;
  end_date: string;
  total_days: number;
  duration_type: "full_day" | "half_day" | "hourly";
  half_day_period: "morning" | "afternoon" | null;
  hours: number | null;
  reason: string | null;
  status: LeaveRequestStatus;
  created_at: string;
}

export interface LeaveApplyPayload {
  leave_type_id: string;
  start_date: string; // ISO date
  end_date: string; // ISO date
  reason?: string;
  duration_type: "full_day" | "half_day" | "hourly";
  half_day_period?: "morning" | "afternoon";
  hours?: number;
}

// ── Holidays ─────────────────────────────────────────────────────────────

export interface Holiday {
  id: string;
  name: string;
  date: string; // ISO date
  description: string | null;
  is_optional: boolean;
  branch_id: string | null;
}

// ── Notifications ────────────────────────────────────────────────────────

export interface NotificationItem {
  id: string;
  title: string;
  body: string | null;
  type: string;
  icon: string | null;
  action_url: string | null;
  metadata: Record<string, unknown>;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

// ── Work sessions (for the Dashboard's "this week" total) ──────────────────

export interface WorkSessionItem {
  id: string;
  employee_id: string;
  started_at: string;
  ended_at: string | null;
  status: "active" | "on_break" | "ended";
  total_minutes: number;
  total_break_minutes: number;
  current_break_started_at: string | null;
}

// ── Payroll (self-service payslips) ─────────────────────────────────────────

export type PayslipStatus = "draft" | "generated" | "sent" | "paid" | "reversed";

export interface PayslipRun {
  id: string;
  name: string;
  period_start: string; // ISO date
  period_end: string; // ISO date
  pay_date: string; // ISO date
  currency: string;
}

export interface MyPayslipItem {
  id: string;
  status: PayslipStatus;
  gross_salary: string; // decimal-as-string, same convention the backend uses everywhere else
  total_deductions: string;
  net_salary: string;
  run: PayslipRun;
}

// ── Attendance (self-service history) ───────────────────────────────────────

export type AttendanceStatus =
  | "present"
  | "absent"
  | "late"
  | "half_day"
  | "on_leave"
  | "holiday"
  | "weekend"
  | "work_from_home";

export interface AttendanceRecordItem {
  id: string;
  employee_id: string;
  employee_name: string;
  date: string; // ISO date
  check_in: string | null; // ISO datetime
  check_out: string | null; // ISO datetime
  status: AttendanceStatus;
  total_minutes: number | null;
  overtime_minutes: number | null;
  late_minutes: number | null;
  is_regularized: boolean;
}
