import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "./api-client";
import { apiErrorMessage } from "./payroll.service";

// ── status history (E-08) ───────────────────────────────────────────────────
export interface StatusHistoryItem {
  id: string;
  from_status: string | null;
  to_status: string;
  reason: string | null;
  effective_date: string;
  source: "created" | "update" | "offboard" | "import";
  changed_by: string | null;
  created_at: string | null;
}

export function useEmployeeHistory(employeeId: string) {
  return useQuery({
    queryKey: ["employee", employeeId, "history"],
    queryFn: async () => (await apiClient.get<StatusHistoryItem[]>(`/employees/${employeeId}/history`)).data,
    enabled: !!employeeId,
  });
}

// ── offboarding ─────────────────────────────────────────────────────────────
export const OFFBOARD_REASONS = [
  { value: "resignation", label: "Resignation" },
  { value: "termination", label: "Termination" },
  { value: "end_of_contract", label: "End of contract" },
  { value: "retirement", label: "Retirement" },
  { value: "other", label: "Other" },
] as const;
export type OffboardReason = (typeof OFFBOARD_REASONS)[number]["value"];

export function useOffboardEmployee(employeeId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { date_of_leaving: string; exit_reason: string; reason_type: OffboardReason }) =>
      (await apiClient.post(`/employees/${employeeId}/offboard`, null, { params: v })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employee", employeeId] });
      qc.invalidateQueries({ queryKey: ["employees"] });
      toast.success("Employee offboarded. Their login has been disabled.");
    },
    onError: (err: unknown) => toast.error(apiErrorMessage(err, "Could not offboard this employee")),
  });
}

// ── contracts (E-07) ────────────────────────────────────────────────────────
export type ContractState = "active" | "expiring" | "expired" | "renewed" | "terminated";
export const CONTRACT_TYPES = [
  { value: "permanent", label: "Permanent" },
  { value: "fixed_term", label: "Fixed term" },
  { value: "probation", label: "Probation" },
  { value: "internship", label: "Internship" },
  { value: "consultant", label: "Consultant" },
] as const;

export interface Contract {
  id: string;
  employee_id: string;
  employee_code: string | null;
  employee_name: string | null;
  contract_type: string;
  start_date: string;
  end_date: string | null;
  status: string;
  state: ContractState;
  days_left: number | null;
  renewal_alert_days: number;
  document_id: string | null;
  notes: string | null;
  renewed_from_id: string | null;
}
export interface ContractList {
  items: Contract[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
export interface ContractInput {
  contract_type: string;
  start_date: string;
  end_date: string | null;
  renewal_alert_days: number;
  notes: string | null;
}

export function useEmployeeContracts(employeeId: string) {
  return useQuery({
    queryKey: ["employee", employeeId, "contracts"],
    queryFn: async () => (await apiClient.get<ContractList>(`/employees/${employeeId}/contracts`)).data,
    enabled: !!employeeId,
  });
}

export function useContracts(filters: { state?: string; page?: number; page_size?: number }) {
  return useQuery({
    queryKey: ["contracts", filters],
    queryFn: async () => (await apiClient.get<ContractList>("/employees/contracts", { params: filters })).data,
  });
}

function invalidateContracts(qc: ReturnType<typeof useQueryClient>, employeeId?: string) {
  qc.invalidateQueries({ queryKey: ["contracts"] });
  if (employeeId) qc.invalidateQueries({ queryKey: ["employee", employeeId, "contracts"] });
}

export function useContractActions(employeeId?: string) {
  const qc = useQueryClient();
  const done = (msg: string) => () => {
    invalidateContracts(qc, employeeId);
    toast.success(msg);
  };
  const fail = (msg: string) => (err: unknown) => toast.error(apiErrorMessage(err, msg));
  return {
    create: useMutation({
      mutationFn: async (v: ContractInput) => (await apiClient.post(`/employees/${employeeId}/contracts`, v)).data,
      onSuccess: done("Contract added"), onError: fail("Could not add the contract"),
    }),
    update: useMutation({
      mutationFn: async (v: { id: string; data: Partial<ContractInput> }) =>
        (await apiClient.patch(`/employees/contracts/${v.id}`, v.data)).data,
      onSuccess: done("Contract updated"), onError: fail("Could not update the contract"),
    }),
    renew: useMutation({
      mutationFn: async (v: { id: string; data: Partial<ContractInput> }) =>
        (await apiClient.post(`/employees/contracts/${v.id}/renew`, v.data)).data,
      onSuccess: done("Contract renewed"), onError: fail("Could not renew the contract"),
    }),
    terminate: useMutation({
      mutationFn: async (v: { id: string; reason: string }) =>
        (await apiClient.post(`/employees/contracts/${v.id}/terminate`, { reason: v.reason || null })).data,
      onSuccess: done("Contract terminated"), onError: fail("Could not terminate the contract"),
    }),
    remove: useMutation({
      mutationFn: async (id: string) => (await apiClient.delete(`/employees/contracts/${id}`)).data,
      onSuccess: done("Contract deleted"), onError: fail("Could not delete the contract"),
    }),
  };
}

// ── export / import (E-08) ──────────────────────────────────────────────────
/** Both files need the Bearer token, so fetch as a blob and hand the browser an object URL. */
export async function downloadCsv(path: string, fileName: string, params?: Record<string, unknown>): Promise<void> {
  try {
    const response = await apiClient.get(path, { params, responseType: "blob" });
    const url = window.URL.createObjectURL(new Blob([response.data], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    toast.error(apiErrorMessage(err, "Could not download the file"));
  }
}

export interface ImportRow {
  row: number;
  email: string;
  ok: boolean;
  error: string | null;
  employee_code?: string;
  temporary_password?: string | null;
}
export interface ImportResult {
  dry_run: boolean;
  total: number;
  created: number;
  failed: number;
  rows: ImportRow[];
}

export async function importEmployees(file: File, dryRun: boolean): Promise<ImportResult> {
  const body = new FormData();
  body.append("file", file);
  const { data } = await apiClient.post<ImportResult>("/employees/import", body, { params: { dry_run: dryRun } });
  return data;
}
