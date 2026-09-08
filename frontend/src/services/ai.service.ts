import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./api-client";

export type AIProvider = "openai" | "anthropic" | "google" | "ollama";

export interface AIConfig {
  provider: AIProvider;
  model: string;
  base_url: string | null;
  has_api_key: boolean;
  api_key_preview: string | null;
  using_platform_default: boolean;
}

export interface AIConfigUpdateInput {
  provider: AIProvider;
  model: string;
  api_key?: string; // omit to keep the currently-stored key
  base_url?: string | null;
}

export interface AIConfigTestInput {
  provider: AIProvider;
  model: string;
  api_key?: string;
  base_url?: string | null;
}

export interface AIConfigTestResult {
  ok: boolean;
  message: string;
}

const aiKeys = {
  all: ["ai"] as const,
  config: () => [...aiKeys.all, "config"] as const,
};

export function useAIConfig() {
  return useQuery({
    queryKey: aiKeys.config(),
    queryFn: async () => {
      const { data } = await apiClient.get<AIConfig>("/ai/config");
      return data;
    },
  });
}

export function useUpdateAIConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: AIConfigUpdateInput) => {
      const { data } = await apiClient.patch<AIConfig>("/ai/config", input);
      return data;
    },
    onSuccess: (data) => qc.setQueryData(aiKeys.config(), data),
  });
}

export function useResetAIConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.delete<AIConfig>("/ai/config");
      return data;
    },
    onSuccess: (data) => qc.setQueryData(aiKeys.config(), data),
  });
}

export function useTestAIConfig() {
  return useMutation({
    mutationFn: async (input: AIConfigTestInput) => {
      const { data } = await apiClient.post<AIConfigTestResult>("/ai/config/test", input);
      return data;
    },
  });
}