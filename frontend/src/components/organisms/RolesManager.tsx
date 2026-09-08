"use client";

import { useState, useMemo } from "react";
import { Plus, Shield, Trash2, Pencil, Users, X, Loader2, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { Button, Card, Badge } from "@/components/atoms";
import {
  useRoles, usePermissionCatalog, useOrgUsers, useRoleUsers,
  useCreateRole, useUpdateRole, useDeleteRole, useAssignRoleToUser, useUnassignRoleFromUser,
  type Role, type RoleFormInput,
} from "@/services/roles.service";

const ROLE_COLORS = ["#7C3AED", "#DC2626", "#2563EB", "#16A34A", "#EA580C", "#0891B2", "#DB2777"];

function RoleFormModal({
  initial, onClose, onSubmit, isSubmitting,
}: {
  initial?: Role;
  onClose: () => void;
  onSubmit: (input: RoleFormInput) => void;
  isSubmitting: boolean;
}) {
  const { data: categories, isLoading } = usePermissionCatalog();
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [color, setColor] = useState(initial?.color ?? ROLE_COLORS[0]);
  const [isSuper, setIsSuper] = useState(initial?.is_super ?? false);
  const [selected, setSelected] = useState<Set<string>>(new Set(initial?.permission_codenames ?? []));
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());

  function toggleCategory(category: string) {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category); else next.add(category);
      return next;
    });
  }

  function togglePermission(codename: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(codename)) next.delete(codename); else next.add(codename);
      return next;
    });
  }

  function toggleAllInCategory(codenames: string[], allSelected: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      codenames.forEach((c) => (allSelected ? next.delete(c) : next.add(c)));
      return next;
    });
  }

  function handleSubmit() {
    if (!name.trim()) {
      toast.error("Role name is required");
      return;
    }
    onSubmit({
      name: name.trim(),
      description: description.trim() || undefined,
      color,
      is_super: isSuper,
      permission_codenames: Array.from(selected),
    });
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <h2 className="font-heading text-sm font-semibold">{initial ? "Edit Role" : "Create Custom Role"}</h2>
          <button onClick={onClose} className="text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          <div>
            <label className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-muted))]">Role Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Recruiter, Payroll Admin, Team Lead…"
              className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[hsl(var(--foreground-muted))]">Description (optional)</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this role for?"
              className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))]"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-[hsl(var(--foreground-muted))]">Color</label>
            <div className="flex gap-2">
              {ROLE_COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => setColor(c)}
                  className="h-7 w-7 rounded-full ring-offset-2"
                  style={{ backgroundColor: c, boxShadow: color === c ? `0 0 0 2px ${c}` : undefined }}
                />
              ))}
            </div>
          </div>

          <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-[hsl(var(--border))] p-3">
            <input type="checkbox" checked={isSuper} onChange={(e) => setIsSuper(e.target.checked)} className="mt-0.5" />
            <div>
              <p className="text-sm font-medium">Full access</p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">
                Grants every permission automatically, including any added in the future. Overrides the checkboxes below.
              </p>
            </div>
          </label>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="text-xs font-medium text-[hsl(var(--foreground-muted))]">
                Permissions {!isSuper && `(${selected.size} selected)`}
              </label>
            </div>

            {isSuper ? (
              <p className="rounded-lg border border-dashed border-[hsl(var(--border))] p-4 text-center text-xs text-[hsl(var(--foreground-muted))]">
                "Full access" is on — individual permissions don't apply.
              </p>
            ) : isLoading ? (
              <div className="flex justify-center py-8"><Loader2 size={16} className="animate-spin" /></div>
            ) : (
              <div className="space-y-1.5">
                {categories?.map((cat) => {
                  const codenames = cat.permissions.map((p) => p.codename);
                  const allSelected = codenames.every((c) => selected.has(c));
                  const someSelected = codenames.some((c) => selected.has(c));
                  const isExpanded = expandedCategories.has(cat.category);
                  return (
                    <div key={cat.category} className="rounded-lg border border-[hsl(var(--border))]">
                      <button
                        onClick={() => toggleCategory(cat.category)}
                        className="flex w-full items-center justify-between px-3 py-2.5"
                      >
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={allSelected}
                            ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected; }}
                            onClick={(e) => e.stopPropagation()}
                            onChange={() => toggleAllInCategory(codenames, allSelected)}
                          />
                          <span className="text-sm font-medium">{cat.category}</span>
                          <span className="text-xs text-[hsl(var(--foreground-muted))]">
                            ({codenames.filter((c) => selected.has(c)).length}/{codenames.length})
                          </span>
                        </div>
                        <ChevronDown size={14} className={`transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                      </button>
                      {isExpanded && (
                        <div className="space-y-1 border-t border-[hsl(var(--border))] px-3 py-2">
                          {cat.permissions.map((p) => (
                            <label key={p.codename} className="flex cursor-pointer items-start gap-2 py-1">
                              <input
                                type="checkbox"
                                checked={selected.has(p.codename)}
                                onChange={() => togglePermission(p.codename)}
                                className="mt-0.5"
                              />
                              <div className="min-w-0">
                                <p className="text-xs font-medium">{p.label}</p>
                                {p.is_sensitive && <Badge variant="warning" className="mt-0.5">Sensitive</Badge>}
                              </div>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-[hsl(var(--border))] px-6 py-4">
          <button onClick={onClose} className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--accent))]">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
          >
            {isSubmitting && <Loader2 size={14} className="animate-spin" />}
            {initial ? "Save Changes" : "Create Role"}
          </button>
        </div>
      </div>
    </>
  );
}

function ManageUsersModal({ role, onClose }: { role: Role; onClose: () => void }) {
  const { data: orgUsers } = useOrgUsers();
  const { data: roleUsers } = useRoleUsers(role.id, true);
  const assignMutation = useAssignRoleToUser(role.id);
  const unassignMutation = useUnassignRoleFromUser(role.id);

  const assignedIds = useMemo(() => new Set((roleUsers ?? []).map((u) => u.id)), [roleUsers]);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div>
            <h2 className="font-heading text-sm font-semibold">Users in "{role.name}"</h2>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">{assignedIds.size} assigned</p>
          </div>
          <button onClick={onClose} className="text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-1.5">
          {orgUsers?.map((u) => {
            const isAssigned = assignedIds.has(u.id);
            return (
              <div key={u.id} className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] px-3 py-2">
                <div>
                  <p className="text-sm font-medium">{u.first_name} {u.last_name}</p>
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">{u.email}</p>
                </div>
                <button
                  onClick={() => {
                    if (isAssigned) unassignMutation.mutate(u.id);
                    else assignMutation.mutate(u.id);
                  }}
                  disabled={assignMutation.isPending || unassignMutation.isPending}
                  className={`rounded-md px-3 py-1.5 text-xs font-medium ${
                    isAssigned
                      ? "border border-[hsl(var(--destructive))]/30 text-[hsl(var(--destructive))] hover:bg-[hsl(var(--status-error-bg))]"
                      : "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))]"
                  }`}
                >
                  {isAssigned ? "Remove" : "Add"}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

export function RolesManager() {
  const { data: roles, isLoading } = useRoles();
  const [showForm, setShowForm] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [managingUsersFor, setManagingUsersFor] = useState<Role | null>(null);

  const createMutation = useCreateRole();
  const updateMutation = useUpdateRole(editingRole?.id ?? "");
  const deleteMutation = useDeleteRole();

  async function handleCreate(input: RoleFormInput) {
    try {
      await createMutation.mutateAsync(input);
      toast.success("Role created");
      setShowForm(false);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message ?? "Couldn't create role";
      toast.error(msg);
    }
  }

  async function handleUpdate(input: RoleFormInput) {
    try {
      await updateMutation.mutateAsync(input);
      toast.success("Role updated");
      setEditingRole(null);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message ?? "Couldn't update role";
      toast.error(msg);
    }
  }

  async function handleDelete(role: Role) {
    if (!window.confirm(`Delete "${role.name}"?`)) return;
    try {
      await deleteMutation.mutateAsync(role.id);
      toast.success("Role deleted");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message ?? "Couldn't delete role — it may still have users assigned";
      toast.error(msg);
    }
  }

  return (
    <Card padding={false}>
      <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-5 py-4">
        <div>
          <h3 className="font-heading text-sm font-semibold">Roles & Permissions</h3>
          <p className="text-xs text-[hsl(var(--foreground-muted))]">
            Fully custom — create whatever roles fit your org and pick exactly what each one can do.
          </p>
        </div>
        <Button size="sm" icon={<Plus size={13} />} onClick={() => setShowForm(true)}>Create Role</Button>
      </div>

      <div className="px-5 py-4">
        {isLoading ? (
          <div className="flex justify-center py-8"><Loader2 size={16} className="animate-spin" /></div>
        ) : !roles || roles.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[hsl(var(--border))] p-8 text-center">
            <Shield size={24} className="mx-auto mb-2 text-[hsl(var(--foreground-muted))]" />
            <p className="text-sm font-medium">No roles yet</p>
            <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">
              As the org owner, you already have full access. Create roles when you're ready to bring teammates in.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {roles.map((role) => (
              <div key={role.id} className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))] p-3">
                <div className="flex items-center gap-3">
                  <div className="h-8 w-8 rounded-lg" style={{ backgroundColor: (role.color ?? "#94A3B8") + "22" }}>
                    <Shield size={16} className="m-2" style={{ color: role.color ?? "#94A3B8" }} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium">{role.name}</p>
                      {role.is_super && <Badge variant="info">Full access</Badge>}
                    </div>
                    <p className="text-xs text-[hsl(var(--foreground-muted))]">
                      {role.is_super ? "All permissions" : `${role.permission_codenames.length} permission(s)`} · {role.user_count} user(s)
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={() => setManagingUsersFor(role)} title="Manage users" className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))]">
                    <Users size={14} />
                  </button>
                  <button onClick={() => setEditingRole(role)} title="Edit role" className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))]">
                    <Pencil size={14} />
                  </button>
                  <button onClick={() => handleDelete(role)} title="Delete role" className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--status-error-bg))] hover:text-[hsl(var(--destructive))]">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showForm && (
        <RoleFormModal
          onClose={() => setShowForm(false)}
          onSubmit={handleCreate}
          isSubmitting={createMutation.isPending}
        />
      )}
      {editingRole && (
        <RoleFormModal
          initial={editingRole}
          onClose={() => setEditingRole(null)}
          onSubmit={handleUpdate}
          isSubmitting={updateMutation.isPending}
        />
      )}
      {managingUsersFor && (
        <ManageUsersModal role={managingUsersFor} onClose={() => setManagingUsersFor(null)} />
      )}
    </Card>
  );
}
