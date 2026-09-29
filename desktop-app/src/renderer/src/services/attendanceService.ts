import apiClient from "@shared/api-client";
import type { AttendanceRecordItem } from "../types/hrms";
import { toIsoDate } from "../lib/format";

/**
 * GET /attendance — self-scoping. A plain employee holding only
 * `attendance.view_own` (not the broader `attendance.view`) gets back just
 * their own records regardless of any employee_id passed, so no
 * employee_id param is sent here (see attendance.py's list_attendance).
 *
 * CHANGED: this used to ask for "page 1, page_size 30" with no date
 * filter and call that "recent history". That silently broke the moment
 * anyone had more than 30 records in view — and it made a month summary
 * impossible, because you never knew whether the 30 rows you got covered
 * the month or half of it. The endpoint has accepted date_from/date_to
 * all along (see its Query params); it just was not being used.
 */
export async function getMyAttendance(range?: { from: Date; to: Date }): Promise<AttendanceRecordItem[]> {
  const { data } = await apiClient.get<{ items: AttendanceRecordItem[]; total: number }>("/attendance", {
    params: {
      page: 1,
      page_size: 200, // endpoint caps at 200; a month is ~31 rows, so one page always covers it
      ...(range ? { date_from: toIsoDate(range.from), date_to: toIsoDate(range.to) } : {}),
    },
  });
  return data.items;
}

/** The current calendar month, used by the dashboard's stat band. */
export async function getMyAttendanceForMonth(month: Date): Promise<AttendanceRecordItem[]> {
  const from = new Date(month.getFullYear(), month.getMonth(), 1);
  const to = new Date(month.getFullYear(), month.getMonth() + 1, 0);
  return getMyAttendance({ from, to });
}
