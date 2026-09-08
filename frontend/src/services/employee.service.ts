import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import apiClient from "./api-client";
import type { EmployeeListItem, EmployeeDetail, PaginatedResponse } from "@/types";

export interface EmployeeFilters {
  query?: string;
  department_id?: string;
  branch_id?: string;
  status?: string;
  employment_type?: string;
  page?: number;
  page_size?: number;
}

export const employeeKeys = {
  all: ["employees"] as const,
  lists: () => [...employeeKeys.all, "list"] as const,
  list: (filters: EmployeeFilters) => [...employeeKeys.lists(), filters] as const,
  detail: (id: string) => [...employeeKeys.all, "detail", id] as const,
  stats: () => [...employeeKeys.all, "stats"] as const,
};

async function fetchEmployees(filters: EmployeeFilters) {
  const { data } = await apiClient.get<PaginatedResponse<EmployeeListItem>>("/employees", {
    params: filters,
  });
  return data;
}

async function fetchEmployee(id: string) {
  const { data } = await apiClient.get<EmployeeDetail>(`/employees/${id}`);
  return data;
}

async function fetchEmployeeStats() {
  const { data } = await apiClient.get<Record<string, unknown>>("/employees/stats");
  return data;
}

export function useEmployees(filters: EmployeeFilters = {}) {
  return useQuery({
    queryKey: employeeKeys.list(filters),
    queryFn: () => fetchEmployees(filters),
  });
}

export function useEmployee(id: string) {
  return useQuery({
    queryKey: employeeKeys.detail(id),
    queryFn: () => fetchEmployee(id),
    enabled: !!id,
  });
}

export function useEmployeeStats() {
  return useQuery({
    queryKey: employeeKeys.stats(),
    queryFn: fetchEmployeeStats,
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreateEmployee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiClient.post("/employees", data).then((r) => r.data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: employeeKeys.lists() });
      void qc.invalidateQueries({ queryKey: employeeKeys.stats() });
    },
  });
}

export function useUpdateEmployee(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiClient.patch(`/employees/${id}`, data).then((r) => r.data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: employeeKeys.detail(id) });
      void qc.invalidateQueries({ queryKey: employeeKeys.lists() });
    },
  });
}

export function useDeleteEmployee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiClient.delete(`/employees/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: employeeKeys.lists() });
      void qc.invalidateQueries({ queryKey: employeeKeys.stats() });
    },
  });
}
