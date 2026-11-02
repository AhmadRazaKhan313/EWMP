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
  /** Path of the uploaded logo, or null. Read-only here: change it with the logo hooks. */
  logo_url?: string | null;
}

/** Partial update: send only the fields that change. */
export type OrganizationSettingsUpdate = Partial<
  Omit<OrganizationSettings, "id" | "slug" | "logo_url">
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

/** Same check the server does (it also checks the file's real bytes). */
export const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp", "image/svg+xml"];
export const MAX_LOGO_BYTES = 2 * 1024 * 1024;

export function logoProblem(file: { type: string; size: number }): string | null {
  if (!LOGO_TYPES.includes(file.type)) return "Logo must be a PNG, JPEG, WebP or SVG image";
  if (file.size > MAX_LOGO_BYTES) return "Logo must be 2 MB or smaller";
  return null;
}

/** Tells the sidebar (which reads the public logo URL directly) to look again. */
export const LOGO_CHANGED_EVENT = "ewmp:logo-changed";

export function useUploadOrganizationLogo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      const { data } = await apiClient.post<OrganizationSettings>("/organization/logo", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return data;
    },
    onSuccess: (data) => {
      qc.setQueryData(orgKeys.settings(), data);
      if (typeof window !== "undefined") window.dispatchEvent(new Event(LOGO_CHANGED_EVENT));
    },
  });
}

export function useDeleteOrganizationLogo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => (await apiClient.delete<OrganizationSettings>("/organization/logo")).data,
    onSuccess: (data) => {
      qc.setQueryData(orgKeys.settings(), data);
      if (typeof window !== "undefined") window.dispatchEvent(new Event(LOGO_CHANGED_EVENT));
    },
  });
}
