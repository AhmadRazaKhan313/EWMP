import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "./api-client";
import { apiErrorMessage } from "./payroll.service";

export interface TaxRow { tax_rate_id: string | null; name: string; percent: string; taxable: string; tax: string; documents: number }
export interface TaxSide { rows: TaxRow[]; taxable: string; tax: string }
export interface TaxReport { date_from: string; date_to: string; currency: string; sales: TaxSide; purchases: TaxSide; net_tax_payable: string }

export function useTaxReport(date_from: string, date_to: string, enabled = true) {
  return useQuery({
    queryKey: ["finance", "taxes", date_from, date_to], enabled,
    queryFn: async () => (await apiClient.get<TaxReport>("/finance/reports/taxes", { params: { date_from, date_to } })).data,
  });
}

export async function exportTaxReport(format: "xlsx" | "csv", date_from: string, date_to: string): Promise<void> {
  try {
    const { data } = await apiClient.get<Blob>("/finance/reports/export", { params: { report: "taxes", format, date_from, date_to }, responseType: "blob" });
    const url = URL.createObjectURL(data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `tax-report.${format}`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    toast.error(apiErrorMessage(e, "Could not export the report"));
  }
}
