/**
 * Reports API. The hub (catalog + /hub/{key}) serves every report with one shape;
 * the older attendance-only helpers below are kept so nothing that imports them breaks.
 */
import { useQuery } from "@tanstack/react-query";
import apiClient from "./api-client";
import { downloadCsv } from "./payroll.service";

// ── Hub ─────────────────────────────────────────────────────────────────────
export type ReportColumnType = "text" | "int" | "money" | "percent" | "date" | "hours";

export interface ReportColumn { key: string; label: string; type: ReportColumnType }
export interface ReportTile { label: string; value: number | string | null; type: ReportColumnType }
export type ReportRow = Record<string, string | number | null>;

export interface HubReport {
  key: string;
  title: string;
  subtitle: string;
  columns: ReportColumn[];
  rows: ReportRow[];
  totals: ReportRow | null;
  summary: ReportTile[];
  notes: string[];
}

export interface CatalogItem {
  key: string;
  title: string;
  category: string;
  description: string;
  uses_search: boolean;
}

export interface HubFilters { month: string; departmentId?: string; search?: string }

function hubParams(f: HubFilters) {
  const p: Record<string, string> = { month: f.month };
  if (f.departmentId) p.department_id = f.departmentId;
  if (f.search) p.search = f.search;
  return p;
}

export function useReportCatalog() {
  return useQuery({
    queryKey: ["reports", "catalog"],
    queryFn: async () =>
      (await apiClient.get<{ items: CatalogItem[]; can_export: boolean }>("/reports/catalog")).data,
  });
}

export function useHubReport(key: string | null, filters: HubFilters) {
  return useQuery({
    queryKey: ["reports", "hub", key, filters],
    enabled: !!key,
    queryFn: async () =>
      (await apiClient.get<HubReport>(`/reports/hub/${key}`, { params: hubParams(filters) })).data,
  });
}

const XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export async function downloadHubReport(
  key: string, format: "xlsx" | "csv", filters: HubFilters,
): Promise<void> {
  const qs = new URLSearchParams(hubParams(filters)).toString();
  try {
    const response = await apiClient.get(`/reports/hub/${key}/${format}?${qs}`, { responseType: "blob" });
    const blob = new Blob([response.data], { type: format === "xlsx" ? XLSX_TYPE : "text/csv;charset=utf-8" });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${key}-${filters.month}.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    // A blob error body is not JSON yet; read it so the real message shows.
    const data = (err as { response?: { data?: unknown } })?.response?.data;
    if (data instanceof Blob) {
      try {
        const detail = JSON.parse(await data.text())?.detail;
        if (typeof detail === "string") throw new Error(detail);
      } catch (inner) {
        if (inner instanceof Error && !(inner instanceof SyntaxError)) throw inner;
      }
    }
    throw err;
  }
}

// ── Attendance-only helpers (kept for compatibility) ───────────────────────
export interface AttendanceMonthRow {
  employee_id: string;
  employee_code: string;
  employee_name: string;
  department_name: string | null;
  present: number;
  late: number;
  half_day: number;
  missed_punch: number;
  absent: number;
  on_leave: number;
  holiday: number;
  weekly_off: number;
  pending: number;
  days_worked: number;
  working_days: number;
  attendance_pct: number | null;
  worked_hours: number;
  late_minutes: number;
  overtime_hours: number;
}

export interface AttendanceMonthReport {
  period: { year: number; month: number; from: string; to: string; counted_through: string | null };
  items: AttendanceMonthRow[];
  totals: {
    employees: number;
    present: number;
    late: number;
    half_day: number;
    missed_punch: number;
    absent: number;
    on_leave: number;
    holiday: number;
    weekly_off: number;
    pending: number;
    attendance_pct: number | null;
  };
}

export interface ReportFilters {
  month: string; // YYYY-MM
  departmentId?: string;
  search?: string;
}

function params(f: ReportFilters) {
  const p: Record<string, string> = { month: f.month };
  if (f.departmentId) p.department_id = f.departmentId;
  if (f.search) p.search = f.search;
  return p;
}

export function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function useAttendanceMonthly(filters: ReportFilters) {
  return useQuery({
    queryKey: ["reports", "attendance-monthly", filters],
    queryFn: async () =>
      (await apiClient.get<AttendanceMonthReport>("/reports/attendance/monthly", { params: params(filters) })).data,
  });
}

export function downloadAttendanceCsv(filters: ReportFilters): Promise<void> {
  const qs = new URLSearchParams(params(filters)).toString();
  return downloadCsv(`/reports/attendance/monthly/csv?${qs}`, `attendance-${filters.month}.csv`);
}

export interface DepartmentOption { id: string; name: string }

export function useDepartmentOptions() {
  return useQuery({
    queryKey: ["departments", "options"],
    queryFn: async (): Promise<DepartmentOption[]> => {
      const raw = (await apiClient.get("/departments")).data as
        | { items?: { id: string; name: string }[] }
        | { id: string; name: string }[];
      const rows = Array.isArray(raw) ? raw : (raw.items ?? []);
      return rows.map((r) => ({ id: String(r.id), name: String(r.name ?? "") }));
    },
  });
}
