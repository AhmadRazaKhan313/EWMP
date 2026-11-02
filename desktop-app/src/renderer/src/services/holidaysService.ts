import apiClient from "@shared/api-client";
import type { Holiday } from "../types/hrms";

/** GET /holidays?upcoming=true — org-wide calendar, branch-scoped server
 * side. Open to any authenticated employee (no permission gate). */
export async function getUpcomingHolidays(): Promise<Holiday[]> {
  const { data } = await apiClient.get<{ items: Holiday[]; total: number }>("/holidays", {
    params: { upcoming: true },
  });
  return data.items;
}

/** GET /holidays?year=YYYY — the full calendar for one year, past and
 * future, used by CalendarScreen when someone pages to a month that
 * upcoming=true would have excluded (last month, last year). */
export async function getHolidaysForYear(year: number): Promise<Holiday[]> {
  const { data } = await apiClient.get<{ items: Holiday[]; total: number }>("/holidays", {
    params: { year },
  });
  return data.items;
}
