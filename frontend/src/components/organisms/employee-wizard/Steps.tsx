"use client";

import { useFormContext, useWatch } from "react-hook-form";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, Briefcase, Calendar, CreditCard, Droplet, Globe, Mail, MapPin, Phone, ShieldCheck, User, Users,
} from "lucide-react";
import apiClient from "@/services/api-client";
import { Avatar } from "@/components/atoms";
import { OptionsNotice, SelectField, TextField } from "./fields";
import {
  BLOOD_GROUPS, CURRENCY_OPTIONS, EMPLOYMENT_TYPE_OPTIONS, GENDER_OPTIONS, JOB_NATURE_OPTIONS, RELATIONSHIP_OPTIONS,
  type EmployeeWizardValues,
} from "./wizard";

// ── Database-backed options (same endpoints and cache keys as the old drawer) ─
type Option = { id: string; label: string; extra?: string };

function useOptions(key: string, path: string, pick: (row: Record<string, unknown>) => Option) {
  const q = useQuery({
    queryKey: [key],
    queryFn: async () => (await apiClient.get(path)).data as unknown,
  });
  const raw = q.data as { items?: Record<string, unknown>[] } | Record<string, unknown>[] | undefined;
  const rows = Array.isArray(raw) ? raw : (raw?.items ?? []);
  return { options: rows.map(pick), isLoading: q.isLoading, isError: q.isError, refetch: () => void q.refetch() };
}

const byName = (r: Record<string, unknown>): Option => ({ id: String(r.id), label: String(r.name ?? "") });

export function useWizardOptions() {
  const departments = useOptions("departments", "/departments", byName);
  const designations = useOptions("designations", "/designations", (r) => ({ id: String(r.id), label: String(r.title ?? r.name ?? "") }));
  const branches = useOptions("branches", "/branches", byName);
  const roles = useOptions("roles", "/roles", byName);
  const shifts = useOptions("shifts", "/shifts", (r) => ({
    id: String(r.id),
    label: `${String(r.name)} (${String(r.start_time).slice(0, 5)}–${String(r.end_time).slice(0, 5)})`,
    extra: r.is_active === false ? "inactive" : undefined,
  }));
  return { departments, designations, branches, roles, shifts };
}
export type WizardOptions = ReturnType<typeof useWizardOptions>;

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 gap-x-5 gap-y-5 sm:grid-cols-2">{children}</div>;
}

// ── Step 1 · Personal ────────────────────────────────────────────────────────
export function PersonalStep() {
  const { control } = useFormContext<EmployeeWizardValues>();
  const [first, last] = useWatch({ control, name: ["first_name", "last_name"] });
  const full = `${first ?? ""} ${last ?? ""}`.trim();
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-4">
        <Avatar name={full || "New employee"} size="lg" />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{full || "New employee"}</p>
          <p className="text-xs text-[hsl(var(--foreground-muted))]">A profile photo can be added later as a document.</p>
        </div>
      </div>
      <Grid>
        <TextField name="first_name" label="First name" required icon={User} placeholder="John" autoComplete="off" />
        <TextField name="last_name" label="Last name" required icon={User} placeholder="Smith" autoComplete="off" />
        <TextField name="email" label="Work email" required icon={Mail} type="email" placeholder="john@company.com" autoComplete="off"
          hint="This becomes their login email." />
        <TextField name="phone" label="Phone" icon={Phone} type="tel" placeholder="+1 234 567 8900" />
        <TextField name="date_of_birth" label="Date of birth" icon={Calendar} type="date" />
        <SelectField name="gender" label="Gender">
          <option value="">Select gender</option>
          {GENDER_OPTIONS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
        </SelectField>
        <TextField name="nationality" label="Nationality" icon={Globe} placeholder="e.g. Pakistani, American" />
        <SelectField name="blood_group" label="Blood group" icon={Droplet}>
          <option value="">Select</option>
          {BLOOD_GROUPS.map((b) => <option key={b} value={b}>{b}</option>)}
        </SelectField>
      </Grid>
    </div>
  );
}

// ── Step 2 · Role & department ───────────────────────────────────────────────
export function RoleStep({ options }: { options: WizardOptions }) {
  const { register } = useFormContext<EmployeeWizardValues>();
  const { roles, departments, designations, branches, shifts } = options;
  return (
    <div className="space-y-5">
      <Grid>
        <div>
          <SelectField name="role_id" label="Role" required icon={ShieldCheck} disabled={roles.options.length === 0}
            hint="Decides what this employee can access.">
            <option value="">{roles.isLoading ? "Loading roles…" : "Select a role"}</option>
            {roles.options.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </SelectField>
          {roles.isError && <OptionsNotice isLoading={false} isError isEmpty={false} what="roles" onRetry={roles.refetch} />}
        </div>
        <SelectField name="job_nature" label="Employment status" required icon={Briefcase}>
          <option value="">Select employment status</option>
          {JOB_NATURE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </SelectField>
      </Grid>

      {!roles.isLoading && !roles.isError && roles.options.length === 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--destructive))]/40 bg-[hsl(var(--destructive))]/5 p-3">
          <AlertTriangle size={16} aria-hidden className="mt-0.5 shrink-0 text-[hsl(var(--destructive))]" />
          <p className="text-xs text-[hsl(var(--foreground-subtle))]">
            No roles exist yet. Create one in <span className="font-medium">Settings → Roles</span> first — every employee must be assigned a role.
          </p>
        </div>
      )}

      <Grid>
        <TextField name="date_of_joining" label="Date of joining" required icon={Calendar} type="date" />
        <SelectField name="employment_type" label="Employment type" icon={Briefcase}>
          {EMPLOYMENT_TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </SelectField>
        <div>
          <SelectField name="department_id" label="Department" icon={Users}>
            <option value="">Select department</option>
            {departments.options.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
          </SelectField>
          <OptionsNotice isLoading={departments.isLoading} isError={departments.isError} isEmpty={departments.options.length === 0} what="departments" onRetry={departments.refetch} />
        </div>
        <div>
          <SelectField name="designation_id" label="Designation" icon={Briefcase}>
            <option value="">Select designation</option>
            {designations.options.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
          </SelectField>
          <OptionsNotice isLoading={designations.isLoading} isError={designations.isError} isEmpty={designations.options.length === 0} what="designations" onRetry={designations.refetch} />
        </div>
        <div>
          <SelectField name="branch_id" label="Branch" icon={MapPin}>
            <option value="">Select branch</option>
            {branches.options.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
          </SelectField>
          <OptionsNotice isLoading={branches.isLoading} isError={branches.isError} isEmpty={branches.options.length === 0} what="branches" onRetry={branches.refetch} />
        </div>
        <TextField name="work_location" label="Work location" icon={MapPin} placeholder="e.g. Karachi Office, Floor 3" />
        <div className="sm:col-span-2">
          <SelectField name="default_shift_id" label="Shift" icon={Calendar}
            hint="Decides when this employee counts as late or absent, and which days are their weekly off.">
            <option value="">No shift (organisation work week)</option>
            {shifts.options.filter((s) => s.extra !== "inactive").map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </SelectField>
          <OptionsNotice isLoading={shifts.isLoading} isError={shifts.isError} isEmpty={false} what="shifts" onRetry={shifts.refetch} />
        </div>
      </Grid>

      <label htmlFor="f-is_remote" className="flex cursor-pointer items-center gap-3 rounded-xl border border-[hsl(var(--border))] p-3 hover:bg-[hsl(var(--background-subtle))]">
        <input id="f-is_remote" type="checkbox" className="h-4 w-4 rounded accent-[hsl(var(--brand-600))]" {...register("is_remote")} />
        <span>
          <span className="block text-sm font-medium">Remote employee</span>
          <span className="block text-xs text-[hsl(var(--foreground-muted))]">This employee works remotely.</span>
        </span>
      </label>
    </div>
  );
}

// ── Step 3 · Pay ─────────────────────────────────────────────────────────────
export function PayStep() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        <TextField name="current_salary" label="Basic salary" icon={CreditCard} type="number" inputMode="decimal" step="0.01" min="0"
          placeholder="0.00" className="sm:col-span-2" />
        <SelectField name="currency" label="Currency">
          {CURRENCY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </SelectField>
      </div>
      <p className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-4 text-sm text-[hsl(var(--foreground-muted))]">
        Detailed salary structure (allowances, deductions, bonuses) can be configured from the Payroll module after the employee is created.
      </p>
    </div>
  );
}

// ── Step 4 · Emergency contact ───────────────────────────────────────────────
export function EmergencyStep() {
  return (
    <Grid>
      <TextField name="emergency_name" label="Contact name" icon={User} placeholder="Jane Smith" className="sm:col-span-2" />
      <TextField name="emergency_phone" label="Phone number" icon={Phone} type="tel" placeholder="+1 234 567 8900" />
      <SelectField name="emergency_relationship" label="Relationship">
        <option value="">Select</option>
        {RELATIONSHIP_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
      </SelectField>
    </Grid>
  );
}
