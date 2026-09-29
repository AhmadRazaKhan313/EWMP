/**
 * Payroll API surface.
 *
 * Every payroll page before this reached for `apiClient` inline and
 * re-declared its own response interfaces, so the same endpoint had
 * three slightly different shapes across three files. This module is the
 * single description of what the payroll API returns — the field names
 * and enum values here are taken from backend/app/api/v1/hrms/payroll.py's
 * `_serialize_*` helpers, which are the actual contract.
 *
 * Note the serializers return Decimals as STRINGS, not numbers. That is
 * deliberate on the backend's side (no float rounding on the way out) and
 * is reflected here rather than papered over — parse at the point of
 * display, with `fmtMoney` below.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "./api-client";

// ── Enums (mirror app/models/payroll.py) ──────────────────────────────────
export const BONUS_TYPES = [
  "performance", "annual", "festival", "joining", "retention", "spot", "attendance", "custom",
] as const;
export type BonusType = (typeof BONUS_TYPES)[number];

export const REIMBURSEMENT_CATEGORIES = [
  "travel", "medical", "fuel", "internet", "meals", "accommodation", "other",
] as const;
export type ReimbursementCategory = (typeof REIMBURSEMENT_CATEGORIES)[number];

export type LoanStatus = "active" | "suspended" | "closed" | "cancelled";
export type AdvanceStatus = "active" | "closed" | "cancelled";
export type ApprovableStatus = "pending" | "approved" | "paid" | "cancelled";
export type ReimbursementStatus =
  | "submitted" | "reviewed" | "approved" | "included_in_payroll" | "paid" | "rejected";

// ── Response shapes ───────────────────────────────────────────────────────
export interface Paginated<T> { items: T[]; total: number }

export interface Loan {
  id: string; employee_id: string; principal_amount: string; interest_rate: string;
  number_of_installments: number; installment_amount: string; remaining_balance: string;
  start_date: string; status: LoanStatus; reason: string | null;
}

export interface Advance {
  id: string; employee_id: string; advance_amount: string; number_of_installments: number;
  installment_amount: string; remaining_balance: string; recovery_start_date: string;
  status: AdvanceStatus; reason: string | null;
}

export interface Bonus {
  id: string; employee_id: string; bonus_type: BonusType; name: string; amount: string;
  is_taxable: boolean; target_period_start: string; target_period_end: string;
  status: ApprovableStatus; notes: string | null;
}

export interface Arrear {
  id: string; employee_id: string; reason: string;
  source_period_start: string; source_period_end: string;
  target_period_start: string; target_period_end: string;
  amount: string; is_taxable: boolean; status: ApprovableStatus;
  calculation_details: Record<string, unknown>;
}

export interface Commission {
  id: string; employee_id: string; plan_id: string | null;
  target_period_start: string; target_period_end: string;
  sales_amount: string; computed_amount: string; status: ApprovableStatus;
}

export interface Reimbursement {
  id: string; employee_id: string; category: ReimbursementCategory; amount: string;
  description: string | null; receipt_url: string | null; is_taxable: boolean;
  status: ReimbursementStatus; submitted_at: string | null; rejection_reason: string | null;
}

export interface TaxBracket {
  id?: string; min_amount: string; max_amount: string | null;
  rate_percentage: string; display_order: number;
}

export interface TaxRule {
  id: string; name: string; country: string; tax_year: string;
  calculation_base: "monthly_taxable_income" | "annual_taxable_income";
  is_active: boolean; effective_from: string; effective_to: string | null;
  notes: string | null; brackets: TaxBracket[];
}

export interface ContributionRule {
  id: string; name: string; code: string; calculation_base: "basic" | "gross";
  employee_percentage: string | null; employee_fixed_amount: string | null;
  employer_percentage: string | null; employer_fixed_amount: string | null;
  min_base: string | null; max_base: string | null;
  is_taxable: boolean; is_active: boolean;
  effective_from: string; effective_to: string | null;
}

export interface ApprovalLevel {
  id: string; name: string; level_order: number;
  required_permission: string; is_active: boolean;
}

export interface EmployeeSalaryAssignment {
  assigned: boolean; id?: string; salary_structure_id?: string;
  basic_salary?: string; effective_from?: string;
  component_overrides?: Record<string, string>;
}

// ── Query keys ────────────────────────────────────────────────────────────
export const payrollKeys = {
  all: ["payroll"] as const,
  loans: (employeeId?: string) => ["payroll", "loans", employeeId ?? "all"] as const,
  advances: (employeeId?: string) => ["payroll", "advances", employeeId ?? "all"] as const,
  bonuses: (employeeId?: string) => ["payroll", "bonuses", employeeId ?? "all"] as const,
  arrears: (employeeId?: string) => ["payroll", "arrears", employeeId ?? "all"] as const,
  commissions: () => ["payroll", "commissions"] as const,
  reimbursements: (employeeId?: string) => ["payroll", "reimbursements", employeeId ?? "all"] as const,
  taxRules: () => ["payroll", "tax-rules"] as const,
  contributionRules: () => ["payroll", "contribution-rules"] as const,
  approvalLevels: () => ["payroll", "approval-levels"] as const,
  employeeSalary: (employeeId: string) => ["payroll", "employee-salary", employeeId] as const,
  structures: () => ["salary-structures"] as const,
};

// ── Helpers ───────────────────────────────────────────────────────────────

/** The backend raises ValidationError/NotFoundError with the human
 * sentence in `detail`; FastAPI's own 422s put it elsewhere. Pull whatever
 * is actually there rather than showing "Request failed with status 400". */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const e = error as { response?: { data?: { detail?: unknown; message?: string } } };
  const detail = e?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: string[] };
    if (first?.msg) return first.loc ? `${first.loc.slice(-1)[0]}: ${first.msg}` : first.msg;
  }
  return e?.response?.data?.message ?? fallback;
}

export function fmtMoney(amount: string | number | null | undefined, currency = "USD"): string {
  if (amount === null || amount === undefined) return "—";
  const n = typeof amount === "number" ? amount : parseFloat(amount);
  if (Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(n);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
}

/** Turns an enum value into something readable without a lookup table per
 * page — "included_in_payroll" becomes "Included in payroll". */
export function humanize(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// ── Generic list hook ─────────────────────────────────────────────────────
function useList<T>(key: readonly unknown[], url: string, params?: Record<string, string | undefined>) {
  return useQuery({
    queryKey: key,
    queryFn: async () => (await apiClient.get<Paginated<T>>(url, { params })).data,
  });
}

/**
 * Every payroll write follows the same three beats: call, toast, refresh
 * the lists that could have changed. Factored out so a new entity type
 * doesn't bring another twenty lines of identical mutation boilerplate.
 */
function useWrite<TVars>(
  fn: (vars: TVars) => Promise<unknown>,
  { success, failure, invalidate }: { success: string; failure: string; invalidate: readonly (readonly unknown[])[] },
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      toast.success(success);
      invalidate.forEach((key) => void qc.invalidateQueries({ queryKey: key }));
    },
    onError: (err: unknown) => toast.error(apiErrorMessage(err, failure)),
  });
}

// ── Loans ─────────────────────────────────────────────────────────────────
export const useLoans = (employeeId?: string) =>
  useList<Loan>(payrollKeys.loans(employeeId), "/payroll/loans", { employee_id: employeeId });

export const useCreateLoan = () =>
  useWrite(
    (body: {
      employee_id: string; principal_amount: number; interest_rate: number;
      number_of_installments: number; start_date: string; reason?: string | null;
    }) => apiClient.post("/payroll/loans", body),
    { success: "Loan created", failure: "Could not create loan", invalidate: [["payroll", "loans"]] },
  );

export const useCancelLoan = () =>
  useWrite((id: string) => apiClient.post(`/payroll/loans/${id}/cancel`), {
    success: "Loan cancelled — no further deductions",
    failure: "Could not cancel loan",
    invalidate: [["payroll", "loans"]],
  });

// ── Advances ──────────────────────────────────────────────────────────────
export const useAdvances = (employeeId?: string) =>
  useList<Advance>(payrollKeys.advances(employeeId), "/payroll/advances", { employee_id: employeeId });

export const useCreateAdvance = () =>
  useWrite(
    (body: {
      employee_id: string; advance_amount: number; number_of_installments: number;
      recovery_start_date: string; reason?: string | null;
    }) => apiClient.post("/payroll/advances", body),
    { success: "Advance created", failure: "Could not create advance", invalidate: [["payroll", "advances"]] },
  );

// ── Bonuses ───────────────────────────────────────────────────────────────
export const useBonuses = (employeeId?: string) =>
  useList<Bonus>(payrollKeys.bonuses(employeeId), "/payroll/bonuses", { employee_id: employeeId });

export const useCreateBonus = () =>
  useWrite(
    (body: {
      employee_id: string; bonus_type: BonusType; name: string; amount: number;
      is_taxable: boolean; target_period_start: string; target_period_end: string; notes?: string | null;
    }) => apiClient.post("/payroll/bonuses", body),
    { success: "Bonus created — pending approval", failure: "Could not create bonus", invalidate: [["payroll", "bonuses"]] },
  );

export const useApproveBonus = () =>
  useWrite((id: string) => apiClient.post(`/payroll/bonuses/${id}/approve`), {
    success: "Bonus approved — the next matching run will include it",
    failure: "Could not approve bonus",
    invalidate: [["payroll", "bonuses"]],
  });

// ── Arrears ───────────────────────────────────────────────────────────────
export const useArrears = (employeeId?: string) =>
  useList<Arrear>(payrollKeys.arrears(employeeId), "/payroll/arrears", { employee_id: employeeId });

export const useCreateArrear = () =>
  useWrite(
    (body: {
      employee_id: string; reason: string; amount: number; is_taxable: boolean;
      source_period_start: string; source_period_end: string;
      target_period_start: string; target_period_end: string;
    }) => apiClient.post("/payroll/arrears", body),
    { success: "Arrear created — pending approval", failure: "Could not create arrear", invalidate: [["payroll", "arrears"]] },
  );

export const useApproveArrear = () =>
  useWrite((id: string) => apiClient.post(`/payroll/arrears/${id}/approve`), {
    success: "Arrear approved",
    failure: "Could not approve arrear",
    invalidate: [["payroll", "arrears"]],
  });

// ── Commissions ───────────────────────────────────────────────────────────
export const useCreateCommissionPlan = () =>
  useWrite(
    (body: { name: string; tiers: { min_amount: number; max_amount: number | null; rate_percentage: number; display_order: number }[] }) =>
      apiClient.post("/payroll/commission-plans", body),
    { success: "Commission plan created", failure: "Could not create plan", invalidate: [["payroll", "commissions"]] },
  );

export const useCreateCommission = () =>
  useWrite(
    (body: {
      employee_id: string; plan_id: string | null;
      target_period_start: string; target_period_end: string; sales_amount: number;
    }) => apiClient.post("/payroll/commissions", body),
    { success: "Commission recorded", failure: "Could not record commission", invalidate: [["payroll", "commissions"]] },
  );

export const useApproveCommission = () =>
  useWrite((id: string) => apiClient.post(`/payroll/commissions/${id}/approve`), {
    success: "Commission approved",
    failure: "Could not approve commission",
    invalidate: [["payroll", "commissions"]],
  });

// ── Reimbursements ────────────────────────────────────────────────────────
export const useReimbursements = (employeeId?: string) =>
  useList<Reimbursement>(payrollKeys.reimbursements(employeeId), "/payroll/reimbursements", {
    employee_id: employeeId,
  });

export const useCreateReimbursement = () =>
  useWrite(
    (body: {
      employee_id: string; category: ReimbursementCategory; amount: number;
      description?: string | null; receipt_url?: string | null; is_taxable: boolean;
    }) => apiClient.post("/payroll/reimbursements", body),
    { success: "Claim submitted", failure: "Could not submit claim", invalidate: [["payroll", "reimbursements"]] },
  );

export const useApproveReimbursement = () =>
  useWrite((id: string) => apiClient.post(`/payroll/reimbursements/${id}/approve`), {
    success: "Claim approved",
    failure: "Could not approve claim",
    invalidate: [["payroll", "reimbursements"]],
  });

export const useRejectReimbursement = () =>
  useWrite(
    ({ id, reason }: { id: string; reason: string }) =>
      apiClient.post(`/payroll/reimbursements/${id}/reject`, { reason }),
    { success: "Claim rejected", failure: "Could not reject claim", invalidate: [["payroll", "reimbursements"]] },
  );

// ── Tax rules ─────────────────────────────────────────────────────────────
export const useTaxRules = () => useList<TaxRule>(payrollKeys.taxRules(), "/payroll/tax-rules");

export const useCreateTaxRule = () =>
  useWrite(
    (body: {
      name: string; country: string; tax_year: string; calculation_base: string;
      effective_from: string; effective_to: string | null; notes: string | null;
      brackets: { min_amount: number; max_amount: number | null; rate_percentage: number; display_order: number }[];
    }) => apiClient.post("/payroll/tax-rules", body),
    { success: "Tax rule created", failure: "Could not create tax rule", invalidate: [payrollKeys.taxRules()] },
  );

export const useDeactivateTaxRule = () =>
  useWrite((id: string) => apiClient.delete(`/payroll/tax-rules/${id}`), {
    success: "Tax rule deactivated",
    failure: "Could not deactivate tax rule",
    invalidate: [payrollKeys.taxRules()],
  });

// ── Contribution rules ────────────────────────────────────────────────────
export const useContributionRules = () =>
  useList<ContributionRule>(payrollKeys.contributionRules(), "/payroll/contribution-rules");

export const useCreateContributionRule = () =>
  useWrite(
    (body: Record<string, unknown>) => apiClient.post("/payroll/contribution-rules", body),
    {
      success: "Contribution rule created",
      failure: "Could not create contribution rule",
      invalidate: [payrollKeys.contributionRules()],
    },
  );

export const useDeactivateContributionRule = () =>
  useWrite((id: string) => apiClient.delete(`/payroll/contribution-rules/${id}`), {
    success: "Contribution rule deactivated",
    failure: "Could not deactivate contribution rule",
    invalidate: [payrollKeys.contributionRules()],
  });

// ── Approval levels ───────────────────────────────────────────────────────
export const useApprovalLevels = () =>
  useList<ApprovalLevel>(payrollKeys.approvalLevels(), "/payroll/approval-levels");

export const useCreateApprovalLevel = () =>
  useWrite(
    (body: { name: string; level_order: number; required_permission: string }) =>
      apiClient.post("/payroll/approval-levels", body),
    {
      success: "Approval level added",
      failure: "Could not add approval level",
      invalidate: [payrollKeys.approvalLevels()],
    },
  );

// ── Employee salary assignment ────────────────────────────────────────────
export function useEmployeeSalary(employeeId: string | null) {
  return useQuery({
    queryKey: payrollKeys.employeeSalary(employeeId ?? ""),
    queryFn: async () =>
      (await apiClient.get<EmployeeSalaryAssignment>(`/payroll/employees/${employeeId}/salary`)).data,
    enabled: !!employeeId,
  });
}

export const useAssignEmployeeSalary = () =>
  useWrite(
    ({ employeeId, ...body }: {
      employeeId: string; salary_structure_id: string; basic_salary: number;
      effective_from: string; component_overrides: Record<string, number>;
    }) => apiClient.post(`/payroll/employees/${employeeId}/salary`, body),
    {
      success: "Salary structure assigned",
      failure: "Could not assign salary structure",
      invalidate: [["payroll", "employee-salary"], ["employees"]],
    },
  );

/**
 * The PDF endpoint needs the same Bearer token as everything else, so a
 * plain <a href> can't reach it — fetch as a blob and hand the browser an
 * object URL. Same pattern as downloadEmployeeDocument.
 */
export async function downloadPayslipPdf(payslipId: string, fileName: string): Promise<void> {
  try {
    const response = await apiClient.get(`/payroll/payslips/${payslipId}/pdf`, { responseType: "blob" });
    const url = window.URL.createObjectURL(new Blob([response.data], { type: "application/pdf" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    toast.error(apiErrorMessage(err, "Could not download payslip"));
  }
}
