import { useMutation, useQueryClient } from "@tanstack/react-query";
import apiClient from "./api-client";

export const assetKeys = {
  all: ["assets"] as const,
  list: () => [...assetKeys.all, "list"] as const,
};

export interface AssetUpdateInput {
  name?: string;
  status?: string;
  location?: string;
  brand?: string;
  model?: string;
  warranty_expiry?: string;
}

function useInvalidateAssets() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: assetKeys.list() });
}

export function useUpdateAsset() {
  const invalidate = useInvalidateAssets();
  return useMutation({
    mutationFn: async ({ assetId, body }: { assetId: string; body: AssetUpdateInput }) => {
      await apiClient.patch(`/assets/${assetId}`, body);
    },
    onSuccess: invalidate,
  });
}

export function useDeleteAsset() {
  const invalidate = useInvalidateAssets();
  return useMutation({
    mutationFn: async (assetId: string) => {
      await apiClient.delete(`/assets/${assetId}`);
    },
    onSuccess: invalidate,
  });
}

export function useAssignAsset() {
  const invalidate = useInvalidateAssets();
  return useMutation({
    mutationFn: async ({ assetId, employeeId, notes }: { assetId: string; employeeId: string; notes?: string }) => {
      await apiClient.post(`/assets/${assetId}/assign`, { employee_id: employeeId, notes: notes ?? "" });
    },
    onSuccess: invalidate,
  });
}

export function useReturnAsset() {
  const invalidate = useInvalidateAssets();
  return useMutation({
    mutationFn: async ({ assetId, condition, notes }: { assetId: string; condition?: string; notes?: string }) => {
      await apiClient.post(`/assets/${assetId}/return`, { condition: condition ?? "good", notes: notes ?? "" });
    },
    onSuccess: invalidate,
  });
}
