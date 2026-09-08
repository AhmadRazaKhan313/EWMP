"use client";
import { useEffect, useState, useCallback } from "react";
import { Shield, Building2, Loader2, Plus, X, ArrowRightLeft, Star } from "lucide-react";
import { toast } from "sonner";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import type { ColumnDef } from "@tanstack/react-table";
import apiClient from "@/services/api-client";
import { useAuthStore } from "@/store/auth.store";
import { authService } from "@/services/auth.service";
import { cn } from "@/utils/cn";
import { DataTable } from "@/components/molecules/DataTable";

const schema = z.object({
  org_name: z.string().min(2, "Required"),
  org_slug: z.string().min(2, "Required").regex(/^[a-z0-9-]+$/, "Lowercase, numbers, hyphens only"),
  owner_first_name: z.string().min(1, "Required"),
  owner_last_name: z.string().min(1, "Required"),
  owner_email: z.string().email("Valid email required"),
  timezone: z.string().default("UTC"),
  country: z.string().optional(),
});
type FormData = z.infer<typeof schema>;

interface OrgRow {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  is_current: boolean;
  employee_count: number;
}

/** Shown right after a successful create — the only moment this
 * temporary password is ever visible, since the backend never stores or
 * re-returns it afterward (only its bcrypt hash is kept). If the admin
 * closes this without copying it, the fix is a normal password reset for
 * that owner_email, not a way to recover this exact string. */
interface NewOrgCredentials {
  orgName: string;
  ownerEmail: string;
  temporaryPassword: string;
}

const inp = "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] hover:border-[hsl(var(--border-strong))]";

export default function AdminSetupPage() {
  const setUser = useAuthStore((s) => s.setUser);
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [isLoadingList, setIsLoadingList] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [newOrgCreds, setNewOrgCreds] = useState<NewOrgCredentials | null>(null);

  const { register, handleSubmit, setValue, reset, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { timezone: "UTC" },
  });

  const loadOrgs = useCallback(async () => {
    setIsLoadingList(true);
    try {
      const { data } = await apiClient.get("/admin/organizations");
      setOrgs(data.organizations ?? []);
    } catch {
      toast.error("Could not load organizations");
    } finally {
      setIsLoadingList(false);
    }
  }, []);

  useEffect(() => {
    loadOrgs();
  }, [loadOrgs]);

  function handleOrgNameChange(e: React.ChangeEvent<HTMLInputElement>) {
    // Just derive the slug here — react-hook-form already updates
    // org_name's own value on every keystroke via the {...register(...)}
    // spread on the <input> itself, so nothing needs to be forwarded
    // manually. (Calling register("org_name").onChange(e) again here used
    // to re-invoke this same handler — since it's registered as that
    // field's onChange option — causing infinite recursion / "Maximum
    // call stack size exceeded".)
    const slug = e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    if (slug.length >= 2) setValue("org_slug", slug);
  }

  async function onSubmit(values: FormData) {
    setIsSubmitting(true);
    try {
      const { data } = await apiClient.post("/admin/organizations", values);
      toast.success(`Organization "${data.org_name}" created`);
      setNewOrgCreds({
        orgName: data.org_name,
        ownerEmail: data.owner_email,
        temporaryPassword: data.owner_temporary_password,
      });
      reset({ timezone: "UTC", org_name: "", org_slug: "", owner_first_name: "", owner_last_name: "", owner_email: "", country: "" });
      setShowForm(false);
      await loadOrgs();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message ?? "Could not create organization";
      toast.error(msg);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleSwitch(org: OrgRow) {
    if (org.is_current) return;
    setSwitchingId(org.id);
    try {
      await apiClient.post(`/admin/switch-organization/${org.id}`);
      const me = await authService.getMe();
      setUser(me);
      toast.success(`Switched to "${org.name}"`);
      await loadOrgs();
    } catch {
      toast.error("Could not switch organization");
    } finally {
      setSwitchingId(null);
    }
  }

  const columns: ColumnDef<OrgRow, unknown>[] = [
    {
      accessorKey: "name",
      header: "Organization",
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          <span className="font-medium">{row.original.name}</span>
          {row.original.is_current && (
            <span className="flex items-center gap-1 rounded-full bg-[hsl(var(--success-subtle))] px-2 py-0.5 text-[10px] font-semibold text-[hsl(var(--success))]">
              <Star size={10} /> Current
            </span>
          )}
        </div>
      ),
    },
    { accessorKey: "slug", header: "Slug" },
    { accessorKey: "employee_count", header: "Employees" },
    {
      accessorKey: "created_at",
      header: "Created",
      cell: ({ row }) => new Date(row.original.created_at).toLocaleDateString(),
    },
    {
      id: "actions",
      header: "",
      enableSorting: false,
      cell: ({ row }) =>
        row.original.is_current ? null : (
          <button
            onClick={() => handleSwitch(row.original)}
            disabled={switchingId === row.original.id}
            className="flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-2.5 py-1 text-xs font-medium hover:bg-[hsl(var(--accent))] disabled:opacity-50"
          >
            {switchingId === row.original.id ? <Loader2 size={12} className="animate-spin" /> : <ArrowRightLeft size={12} />}
            Switch here
          </button>
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[hsl(var(--primary))]">
            <Shield size={20} className="text-[hsl(var(--primary-foreground))]" />
          </div>
          <div>
            <h1 className="font-heading text-xl font-semibold">Organizations</h1>
            <p className="text-sm text-[hsl(var(--foreground-muted))]">Platform-admin only: create and switch between tenant organizations</p>
          </div>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className={cn(
            "flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors",
            "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))]",
          )}
        >
          {showForm ? <X size={15} /> : <Plus size={15} />}
          {showForm ? "Cancel" : "Add Organization"}
        </button>
      </div>

      {showForm && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-6 shadow-[var(--shadow-sm)]">
          <div className="flex items-center gap-2 mb-5 pb-4 border-b border-[hsl(var(--border))]">
            <Building2 size={16} className="text-[hsl(var(--foreground-subtle))]" />
            <h2 className="font-heading text-sm font-semibold">New Organization Details</h2>
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="block text-xs font-medium mb-1.5">Organization Name *</label>
                <input placeholder="Acme Corporation" className={cn(inp, errors.org_name && "border-[hsl(var(--destructive))]")}
                  {...register("org_name", { onChange: handleOrgNameChange })} />
                {errors.org_name && <p className="text-xs text-[hsl(var(--destructive))] mt-1">{errors.org_name.message}</p>}
              </div>

              <div className="col-span-2">
                <label className="block text-xs font-medium mb-1.5">Organization Slug *</label>
                <div className="flex items-center">
                  <span className="flex h-9 items-center rounded-l-md border border-r-0 border-[hsl(var(--border))] bg-[hsl(var(--secondary))] px-3 text-xs text-[hsl(var(--foreground-muted))]">ewmp.io/</span>
                  <input placeholder="acme-corp" className={cn(inp, "rounded-l-none", errors.org_slug && "border-[hsl(var(--destructive))]")}
                    {...register("org_slug")} />
                </div>
                {errors.org_slug && <p className="text-xs text-[hsl(var(--destructive))] mt-1">{errors.org_slug.message}</p>}
              </div>

              <div className="col-span-2">
                <label className="block text-xs font-medium mb-1.5">Owner First Name *</label>
                <input placeholder="Ali" className={cn(inp, errors.owner_first_name && "border-[hsl(var(--destructive))]")}
                  {...register("owner_first_name")} />
                {errors.owner_first_name && <p className="text-xs text-[hsl(var(--destructive))] mt-1">{errors.owner_first_name.message}</p>}
              </div>

              <div className="col-span-2">
                <label className="block text-xs font-medium mb-1.5">Owner Last Name *</label>
                <input placeholder="Khan" className={cn(inp, errors.owner_last_name && "border-[hsl(var(--destructive))]")}
                  {...register("owner_last_name")} />
                {errors.owner_last_name && <p className="text-xs text-[hsl(var(--destructive))] mt-1">{errors.owner_last_name.message}</p>}
              </div>

              <div className="col-span-2">
                <label className="block text-xs font-medium mb-1.5">Owner Email *</label>
                <input type="email" placeholder="owner@acme.com" className={cn(inp, errors.owner_email && "border-[hsl(var(--destructive))]")}
                  {...register("owner_email")} />
                {errors.owner_email && <p className="text-xs text-[hsl(var(--destructive))] mt-1">{errors.owner_email.message}</p>}
                <p className="text-xs text-[hsl(var(--foreground-muted))] mt-1">
                  This becomes the org's login — a temporary password is generated after creation for you to share with them.
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium mb-1.5">Timezone</label>
                <select className={inp} {...register("timezone")}>
                  <option value="UTC">UTC</option>
                  <option value="Asia/Karachi">Asia/Karachi (PKT)</option>
                  <option value="America/New_York">America/New_York (EST)</option>
                  <option value="America/Los_Angeles">America/Los_Angeles (PST)</option>
                  <option value="Europe/London">Europe/London (GMT)</option>
                  <option value="Europe/Berlin">Europe/Berlin (CET)</option>
                  <option value="Asia/Dubai">Asia/Dubai (GST)</option>
                  <option value="Asia/Kolkata">Asia/Kolkata (IST)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium mb-1.5">Country</label>
                <input placeholder="Pakistan" className={inp} {...register("country")} />
              </div>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className={cn(
                "mt-2 flex w-full items-center justify-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2.5 text-sm font-medium text-[hsl(var(--primary-foreground))]",
                "hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60 disabled:cursor-not-allowed transition-colors",
              )}
            >
              {isSubmitting && <Loader2 size={15} className="animate-spin" />}
              {isSubmitting ? "Creating organization..." : "Create Organization"}
            </button>
          </form>
        </div>
      )}

      {newOrgCreds && (
        <div className="rounded-xl border border-[hsl(var(--success))] bg-[hsl(var(--success-subtle))] p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-2">
              <p className="text-sm font-semibold">
                "{newOrgCreds.orgName}" created — share these login details with its owner
              </p>
              <p className="text-xs text-[hsl(var(--foreground-muted))]">
                This password is shown only once and isn't stored anywhere — if it's lost, reset it from the org's own Login screen ("Forgot password").
              </p>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-1 font-mono text-sm">
                <span><span className="text-[hsl(var(--foreground-muted))]">Email:</span> {newOrgCreds.ownerEmail}</span>
                <span><span className="text-[hsl(var(--foreground-muted))]">Temp password:</span> {newOrgCreds.temporaryPassword}</span>
              </div>
            </div>
            <button
              onClick={() => setNewOrgCreds(null)}
              className="shrink-0 text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
            >
              <X size={16} />
            </button>
          </div>
        </div>
      )}

      <DataTable data={orgs} columns={columns} isLoading={isLoadingList} searchPlaceholder="Search organizations…" />
    </div>
  );
}



// ahmadrazakhan1300@gmail.com
// xSLuGrYR7xYAAa1!