import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./api-client";

export type WorkDay = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export const WORK_DAYS: readonly WorkDay[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

/** GET/PATCH /organization — the caller's own organization. */
export interface OrganizationSettings {
  id: string;
  name: string;
  slug: string;
  email: string;
  phone: string | null;
  website: string | null;
  country: string | null;
  /** IANA name, e.g. "Asia/Karachi". */
  timezone: string;
  /** ISO 4217, e.g. "PKR". */
  currency: string;
  work_days: WorkDay[];
  standard_work_hours_per_day: number;
}

/** Partial update: send only the fields that change. */
export type OrganizationSettingsUpdate = Partial<
  Omit<OrganizationSettings, "id" | "slug">
>;

const orgKeys = {
  all: ["organization"] as const,
  settings: () => [...orgKeys.all, "settings"] as const,
};

export function useOrganizationSettings() {
  return useQuery({
    queryKey: orgKeys.settings(),
    queryFn: async () => {
      const { data } = await apiClient.get<OrganizationSettings>("/organization");
      return data;
    },
  });
}

export function useUpdateOrganizationSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: OrganizationSettingsUpdate) => {
      const { data } = await apiClient.patch<OrganizationSettings>("/organization", input);
      return data;
    },
    onSuccess: (data) => qc.setQueryData(orgKeys.settings(), data),
  });
}
