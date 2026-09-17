import apiClient from "@shared/api-client";
import type { MyPayslipItem } from "../types/hrms";

/** GET /payroll/payslips/me — self-service, no payroll.view permission
 * needed (see backend/app/api/v1/hrms/payroll.py's docstring on this
 * endpoint). Paginated server-side, but the desktop app's payslip
 * history is small enough per employee that we just ask for a generous
 * page size and treat it as "all of them" rather than building
 * pagination UI for it. */
export async function getMyPayslips(): Promise<MyPayslipItem[]> {
  const { data } = await apiClient.get<{ items: MyPayslipItem[]; total: number }>("/payroll/payslips/me", {
    params: { page: 1, page_size: 100 },
  });
  return data.items;
}

/** GET /payroll/payslips/{id}/pdf — same self-view permission check as
 * the rest of the payslip endpoints (own payslip only unless the caller
 * has payroll.view). Returns the raw PDF bytes as a blob; the caller is
 * responsible for turning that into a download (see PayslipsScreen). */
export async function downloadPayslipPdf(payslipId: string): Promise<Blob> {
  const { data } = await apiClient.get(`/payroll/payslips/${payslipId}/pdf`, { responseType: "blob" });
  return data as Blob;
}
