import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./api-client";

export interface PermissionItem {
  id: string;
  codename: string;
  label: string;
  description: string | null;
  resource: string;
  action: string;
  category: string;
  is_sensitive: boolean;
}

export interface PermissionCategory {
  category: string;
  permissions: PermissionItem[];
}

export interface Role {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  color: string | null;
  is_super: boolean;
  display_order: number;
  permission_codenames: string[];
  user_count: number;
}

export interface OrgUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role_names?: string[];
}

export interface RoleFormInput {
  name: string;
  description?: string;
  color?: string;
  is_super?: boolean;
  permission_codenames: string[];
}

const roleKeys = {
  all: ["roles"] as const,
  list: () => [...roleKeys.all, "list"] as const,
  detail: (id: string) => [...roleKeys.all, "detail", id] as const,
  permissions: () => [...roleKeys.all, "permissions"] as const,
  orgUsers: () => [...roleKeys.all, "org-users"] as const,
  roleUsers: (id: string) => [...roleKeys.all, "role-users", id] as const,
};

export function useRoles() {
  return useQuery({
    queryKey: roleKeys.list(),
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: Role[]; total: number }>("/roles");
      return data.items;
    },
  });
}

export function usePermissionCatalog() {
  return useQuery({
    queryKey: roleKeys.permissions(),
    queryFn: async () => {
      const { data } = await apiClient.get<{ categories: PermissionCategory[]; total: number }>(
        "/roles/permissions",
      );
      return data.categories;
    },
    staleTime: 5 * 60 * 1000, // permission catalog rarely changes
  });
}

export function useOrgUsers() {
  return useQuery({
    queryKey: roleKeys.orgUsers(),
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: OrgUser[]; total: number }>("/roles/users/list");
      return data.items;
    },
  });
}

export function useRoleUsers(roleId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: roleKeys.roleUsers(roleId ?? ""),
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: OrgUser[]; total: number }>(
        `/roles/${roleId}/users`,
      );
      return data.items;
    },
    enabled: !!roleId && enabled,
  });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: RoleFormInput) => {
      const { data } = await apiClient.post<Role>("/roles", input);
      return data;
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: roleKeys.list() }),
  });
}

export function useUpdateRole(roleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: Partial<RoleFormInput>) => {
      const { data } = await apiClient.patch<Role>(`/roles/${roleId}`, input);
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: roleKeys.list() });
      void qc.invalidateQueries({ queryKey: roleKeys.detail(roleId) });
    },
  });
}

export function useDeleteRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (roleId: string) => {
      await apiClient.delete(`/roles/${roleId}`);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: roleKeys.list() }),
  });
}

export function useAssignRoleToUser(roleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) => {
      await apiClient.post(`/roles/${roleId}/users/${userId}`);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: roleKeys.roleUsers(roleId) });
      void qc.invalidateQueries({ queryKey: roleKeys.list() });
      void qc.invalidateQueries({ queryKey: roleKeys.orgUsers() });
    },
  });
}

export function useUnassignRoleFromUser(roleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) => {
      await apiClient.delete(`/roles/${roleId}/users/${userId}`);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: roleKeys.roleUsers(roleId) });
      void qc.invalidateQueries({ queryKey: roleKeys.list() });
      void qc.invalidateQueries({ queryKey: roleKeys.orgUsers() });
    },
  });
}
