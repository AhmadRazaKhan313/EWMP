"use client";

import { useState, useEffect, useRef } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { X, Loader2, User, Briefcase, MapPin, Phone, CreditCard, FileText, Upload, Download, Trash2, Lock, AlertTriangle, Copy, Check } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/utils/cn";
import apiClient from "@/services/api-client";
import { useAuthStore } from "@/store/auth.store";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/atoms";
import {
  DOCUMENT_TYPE_LABELS,
  type DocumentType,
  useEmployeeDocuments,
  useUploadEmployeeDocument,
  useDeleteEmployeeDocument,
  downloadEmployeeDocument,
} from "@/services/employeeDocuments.service";

// ── Schema ────────────────────────────────────────────────────────────────────
const employeeSchema = z.object({
  // Personal
  first_name: z.string().min(1, "Required"),
  last_name: z.string().min(1, "Required"),
  email: z.string().email("Invalid email"),
  phone: z.string().optional(),
  date_of_birth: z.string().optional(),
  gender: z.enum(["male", "female", "non_binary", "prefer_not_to_say"]).optional(),
  nationality: z.string().optional(),
  blood_group: z.string().optional(),

  // Employment
  date_of_joining: z.string().min(1, "Required"),
  employment_type: z.enum(["full_time", "part_time", "contract", "intern", "freelance"]),
  job_nature: z.string().optional(), // required in both create+edit — enforced in onSubmit
  role_id: z.string().optional(), // required on CREATE only — enforced in onSubmit
  department_id: z.string().optional(),
  designation_id: z.string().optional(),
  branch_id: z.string().optional(),
  work_location: z.string().optional(),
  is_remote: z.boolean().default(false),

  // Compensation
  current_salary: z.string().optional(),
  currency: z.string().default("USD"),

  // Emergency
  emergency_name: z.string().optional(),
  emergency_phone: z.string().optional(),
  emergency_relationship: z.string().optional(),
});

type EmployeeForm = z.infer<typeof employeeSchema>;

// Employment Status (Job Nature) — the employee's contractual standing.
// Backend enum: app/models/employee.py::JobNature (job_nature_enum).
const JOB_NATURE_OPTIONS: { value: string; label: string }[] = [
  { value: "permanent", label: "Permanent / Regular" },
  { value: "probationary", label: "Probationary" },
  { value: "contractual", label: "Contractual / Fixed-Term" },
  { value: "intern", label: "Intern / Trainee" },
  { value: "part_time", label: "Part-Time" },
  { value: "temporary", label: "Temporary / Casual" },
];

// A document chosen during "Add Employee", held in memory until the employee
// row exists. Documents FK to employees.id, so they can't be uploaded before
// the employee is created — we stage them here and flush them right after the
// create call returns the new id (see onSubmit).
type StagedDoc = {
  file: File;
  document_type: string;
  title: string;
  expiry_date?: string;
  notes?: string;
};

// ── Field Components ──────────────────────────────────────────────────────────
function Label({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="block text-xs font-medium text-[hsl(var(--foreground-subtle))] mb-1">
      {children} {required && <span className="text-[hsl(var(--destructive))]">*</span>}
    </label>
  );
}

function Input({ error, className, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { error?: boolean }) {
  return (
    <input
      {...props}
      className={cn(
        "w-full rounded-md border px-3 py-2 text-sm outline-none transition-colors",
        "bg-[hsl(var(--background))] placeholder:text-[hsl(var(--foreground-muted))]",
        "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
        error
          ? "border-[hsl(var(--destructive))]"
          : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
        className,
      )}
    />
  );
}

function Select({ error, children, className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & { error?: boolean }) {
  return (
    <select
      {...props}
      className={cn(
        "w-full rounded-md border px-3 py-2 text-sm outline-none transition-colors",
        "bg-[hsl(var(--background))]",
        "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
        error
          ? "border-[hsl(var(--destructive))]"
          : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
        className,
      )}
    >
      {children}
    </select>
  );
}

function SectionHeader({ icon: Icon, title }: { icon: React.ElementType; title: string }) {
  return (
    <div className="flex items-center gap-2 border-b border-[hsl(var(--border))] pb-2 mb-4">
      <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[hsl(var(--secondary))]">
        <Icon size={13} className="text-[hsl(var(--foreground-subtle))]" />
      </div>
      <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">{title}</h3>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────
interface EmployeeDrawerProps {
  open: boolean;
  onClose: () => void;
  employeeId?: string; // if editing
}

export function EmployeeDrawer({ open, onClose, employeeId }: EmployeeDrawerProps) {
  const qc = useQueryClient();
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<"personal" | "employment" | "compensation" | "emergency" | "documents">("personal");

  // Set right after a brand-new employee is created, so the drawer can
  // stay open and switch into "edit" behavior — documents can only be
  // attached to an employee that already exists (they need a real
  // employee_id), so without this, "Add Employee" could never lead
  // straight into adding documents; the user would have to close the
  // drawer and reopen it in Edit mode just to reach the Documents tab.
  const [createdEmployeeId, setCreatedEmployeeId] = useState<string | null>(null);
  const effectiveEmployeeId = employeeId ?? createdEmployeeId ?? undefined;
  const isEdit = !!effectiveEmployeeId;
  const justCreated = !employeeId && !!createdEmployeeId;

  // Documents staged on the "Add" form before the employee exists. Flushed to
  // the server (via the same upload mutation the edit panel uses) right after
  // the employee is created.
  const [stagedDocs, setStagedDocs] = useState<StagedDoc[]>([]);
  const uploadDoc = useUploadEmployeeDocument();

  function handleClose() {
    setCreatedEmployeeId(null);
    setStagedDocs([]);
    setActiveTab("personal");
    onClose();
  }

  const { register, handleSubmit, reset, formState: { errors } } = useForm<EmployeeForm>({
    resolver: zodResolver(employeeSchema),
    defaultValues: {
      employment_type: "full_time",
      job_nature: "probationary",
      currency: "USD",
      is_remote: false,
    },
  });

  // Real org-structure options, fetched live instead of hardcoded — dropdown
  // values now match real DB UUIDs, so saving department/designation/branch
  // actually works instead of failing (or silently no-op-ing) on fake ids.
  const { data: departments } = useQuery({
    queryKey: ["departments"],
    queryFn: async () => (await apiClient.get("/departments")).data,
    enabled: open,
  });
  const { data: designations } = useQuery({
    queryKey: ["designations"],
    queryFn: async () => (await apiClient.get("/designations")).data,
    enabled: open,
  });
  const { data: branches } = useQuery({
    queryKey: ["branches"],
    queryFn: async () => (await apiClient.get("/branches")).data,
    enabled: open,
  });
  // Roles for the required create-time assignment. Every new employee must be
  // given exactly one role (see backend EmployeeCreateSchema.role_id) — a
  // role-less user has zero permissions and an unusable app.
  const { data: roles } = useQuery({
    queryKey: ["roles"],
    queryFn: async () => (await apiClient.get("/roles")).data,
    enabled: open,
  });

  const departmentOptions: { id: string; name: string }[] = departments?.items ?? departments ?? [];
  const designationOptions: { id: string; title?: string; name?: string }[] = designations?.items ?? designations ?? [];
  const branchOptions: { id: string; name: string }[] = branches?.items ?? branches ?? [];
  const roleOptions: { id: string; name: string }[] = roles?.items ?? roles ?? [];

  // Tracks the role the employee had when the Edit form was opened, so
  // onSubmit can tell "role_id present in form state" apart from "role_id
  // actually changed by the user". Without this, every edit save would
  // include role_id in the PATCH body even when untouched, and the backend
  // now requires the stricter "roles.manage" permission whenever role_id is
  // present — a user with only "employees.update" (e.g. HR data-entry) would
  // get a 403 on totally unrelated edits like updating a phone number.
  const initialRoleIdRef = useRef<string>("");
  const canManageRoles = useAuthStore((s) => s.hasPermission("roles.manage"));

  // Load employee data if editing — prefill every field the form has,
  // not just first/last/email/joining date/type/currency.
  useEffect(() => {
    if (isEdit && open) {
      apiClient.get(`/employees/${effectiveEmployeeId}`).then(({ data }) => {
        initialRoleIdRef.current = data.role_id || "";
        reset({
          first_name: data.first_name || "",
          last_name: data.last_name || "",
          email: data.email || "",
          phone: data.work_phone || "",
          date_of_birth: data.date_of_birth || "",
          gender: data.gender || undefined,
          blood_group: data.blood_group || "",
          nationality: data.nationality || "",
          date_of_joining: data.date_of_joining || "",
          employment_type: data.employment_type || "full_time",
          job_nature: data.job_nature || "probationary",
          role_id: data.role_id || "",
          department_id: data.department_id || "",
          designation_id: data.designation_id || "",
          branch_id: data.branch_id || "",
          work_location: data.work_location || "",
          is_remote: !!data.is_remote,
          current_salary: data.current_salary ? String(data.current_salary) : "",
          currency: data.currency || "USD",
          emergency_name: data.emergency_contact?.name || "",
          emergency_phone: data.emergency_contact?.phone || "",
          emergency_relationship: data.emergency_contact?.relationship || "",
        });
      });
    } else if (!isEdit && open) {
      reset({ employment_type: "full_time", job_nature: "probationary", currency: "USD", is_remote: false });
    }
  }, [isEdit, effectiveEmployeeId, open, reset]);

  async function onSubmit(values: EmployeeForm) {
    // Role is mandatory on create (a role-less user has zero permissions).
    // Job Nature is mandatory in both create and edit — every employee must
    // have an explicit employment status, never a silent/implicit default.
    if (!isEdit && !values.role_id) {
      toast.error("Please assign a role — every employee must have one.");
      setActiveTab("employment");
      return;
    }
    if (!values.job_nature) {
      toast.error("Please select an employment status (Job Nature).");
      setActiveTab("employment");
      return;
    }
    setIsLoading(true);
    try {
      const emergency_contact = values.emergency_name
        ? {
            name: values.emergency_name,
            phone: values.emergency_phone || null,
            relationship: values.emergency_relationship || null,
          }
        : null;

      if (isEdit) {
        const roleChanged = (values.role_id || "") !== initialRoleIdRef.current;
        await apiClient.patch(`/employees/${effectiveEmployeeId}`, {
          first_name: values.first_name,
          last_name: values.last_name,
          date_of_joining: values.date_of_joining,
          employment_type: values.employment_type,
          job_nature: values.job_nature,
          // Omitted entirely unless actually changed — see initialRoleIdRef
          // comment above. Sending it unconditionally would 403 on every
          // edit save for users without "roles.manage".
          ...(roleChanged ? { role_id: values.role_id || null } : {}),
          department_id: values.department_id || null,
          designation_id: values.designation_id || null,
          branch_id: values.branch_id || null,
          work_location: values.work_location || null,
          is_remote: values.is_remote,
          current_salary: values.current_salary ? parseFloat(values.current_salary) : null,
          currency: values.currency,
          work_phone: values.phone || null,
          date_of_birth: values.date_of_birth || null,
          gender: values.gender || null,
          nationality: values.nationality || null,
          blood_group: values.blood_group || null,
          emergency_contact,
        });
        toast.success("Employee updated successfully");
      } else {
        // Single atomic call — backend creates the User + Employee together
        // in one DB transaction, so a failure here can no longer leave a
        // login-capable User account with no Employee profile behind.
        const res = await apiClient.post("/employees", {
          first_name: values.first_name,
          last_name: values.last_name,
          email: values.email,
          date_of_joining: values.date_of_joining,
          employment_type: values.employment_type,
          job_nature: values.job_nature,
          role_id: values.role_id,
          department_id: values.department_id || null,
          designation_id: values.designation_id || null,
          branch_id: values.branch_id || null,
          work_location: values.work_location || null,
          is_remote: values.is_remote,
          current_salary: values.current_salary ? parseFloat(values.current_salary) : null,
          currency: values.currency,
          phone: values.phone || null,
          date_of_birth: values.date_of_birth || null,
          gender: values.gender || null,
          nationality: values.nationality || null,
          blood_group: values.blood_group || null,
          emergency_contact,
        });

        if (res.data?.temporary_password) {
          const password: string = res.data.temporary_password;
          toast.custom(
            (id) => (
              <div className="flex items-center gap-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-3 shadow-[var(--shadow-md)]">
                <div className="text-sm">
                  <p className="font-medium">Employee added</p>
                  <p className="text-[hsl(var(--foreground-muted))]">
                    Temporary password: <span className="font-mono font-semibold text-[hsl(var(--foreground))]">{password}</span>
                  </p>
                </div>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(password);
                    toast.success("Password copied", { duration: 2000 });
                  }}
                  title="Copy password"
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[hsl(var(--border))] hover:bg-[hsl(var(--accent))]"
                >
                  <Copy size={14} />
                </button>
                <button
                  onClick={() => toast.dismiss(id)}
                  title="Dismiss"
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))]"
                >
                  <X size={14} />
                </button>
              </div>
            ),
            { duration: Infinity },
          );
        } else {
          toast.success("Employee added successfully");
        }

        void qc.invalidateQueries({ queryKey: ["employees"] });
        void qc.invalidateQueries({ queryKey: ["employee-stats"] });

        // Stay open and switch into the now-available Documents tab
        // instead of closing — a brand-new employee can't have documents
        // attached until they exist, so this is the first moment it's
        // possible. Closing here (the old behavior) meant the only way
        // to attach onboarding documents was to close and reopen the
        // drawer in Edit mode, which most people would never think to do.
        if (res.data?.id) {
          const newId = res.data.id as string;

          // Flush any documents staged on the Add form now that the employee
          // (and its id) exists — documents FK to employees.id, so this is the
          // earliest they can be uploaded. Best-effort per file: a failure
          // doesn't undo the created employee; the user can retry any that
          // failed from the Documents tab, which is where we land next.
          if (stagedDocs.length > 0) {
            let failed = 0;
            for (const d of stagedDocs) {
              try {
                await uploadDoc.mutateAsync({
                  employeeId: newId,
                  file: d.file,
                  documentType: d.document_type as DocumentType,
                  title: d.title,
                  expiryDate: d.expiry_date || undefined,
                  notes: d.notes || undefined,
                });
              } catch {
                failed++;
              }
            }
            setStagedDocs([]);
            if (failed > 0) {
              toast.error(`${failed} document(s) failed to upload — retry from the Documents tab.`);
            } else {
              toast.success(`${stagedDocs.length} document(s) uploaded`);
            }
          }

          setCreatedEmployeeId(newId);
          setActiveTab("documents");
          setIsLoading(false);
          return;
        }

        handleClose();
        reset();
        setIsLoading(false);
        return;
      }

      void qc.invalidateQueries({ queryKey: ["employees"] });
      void qc.invalidateQueries({ queryKey: ["employee-stats"] });
      handleClose();
      reset();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message ?? "Something went wrong";
      toast.error(msg);
    } finally {
      setIsLoading(false);
    }
  }

  if (!open) return null;

  const tabs = [
    { id: "personal" as const,      label: "Personal" },
    { id: "employment" as const,     label: "Employment" },
    { id: "compensation" as const,   label: "Compensation" },
    { id: "emergency" as const,      label: "Emergency" },
    { id: "documents" as const,      label: "Documents" },
  ];

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
        onClick={handleClose}
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-2xl flex-col bg-[hsl(var(--background))] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div>
            <h2 className="font-heading text-lg font-semibold">
              {justCreated ? "Employee Added" : isEdit ? "Edit Employee" : "Add New Employee"}
            </h2>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">
              {justCreated
                ? "Now's a good time to attach their documents"
                : isEdit
                ? "Update employee information"
                : "Fill in the details to onboard a new employee"}
            </p>
          </div>
          <button
            onClick={handleClose}
            className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
          >
            <X size={16} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[hsl(var(--border))] px-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "px-4 py-3 text-sm font-medium border-b-2 transition-colors",
                activeTab === tab.id
                  ? "border-[hsl(var(--foreground))] text-[hsl(var(--foreground))]"
                  : "border-transparent text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto px-6 py-5">

            {/* ── Personal Tab ── */}
            {activeTab === "personal" && (
              <div className="space-y-5">
                <SectionHeader icon={User} title="Personal Information" />

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label required>First Name</Label>
                    <Input placeholder="John" error={!!errors.first_name} {...register("first_name")} />
                    {errors.first_name && <p className="mt-1 text-xs text-[hsl(var(--destructive))]">{errors.first_name.message}</p>}
                  </div>
                  <div>
                    <Label required>Last Name</Label>
                    <Input placeholder="Smith" error={!!errors.last_name} {...register("last_name")} />
                    {errors.last_name && <p className="mt-1 text-xs text-[hsl(var(--destructive))]">{errors.last_name.message}</p>}
                  </div>
                </div>

                <div>
                  <Label required>Work Email</Label>
                  <Input
                    type="email"
                    placeholder="john@company.com"
                    error={!!errors.email}
                    disabled={isEdit}
                    {...register("email")}
                  />
                  {isEdit && (
                    <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">
                      Login email can&apos;t be changed here.
                    </p>
                  )}
                  {errors.email && <p className="mt-1 text-xs text-[hsl(var(--destructive))]">{errors.email.message}</p>}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label>Phone</Label>
                    <Input type="tel" placeholder="+1 234 567 8900" {...register("phone")} />
                  </div>
                  <div>
                    <Label>Date of Birth</Label>
                    <Input type="date" {...register("date_of_birth")} />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label>Gender</Label>
                    <Select {...register("gender")}>
                      <option value="">Select gender</option>
                      <option value="male">Male</option>
                      <option value="female">Female</option>
                      <option value="non_binary">Non-binary</option>
                      <option value="prefer_not_to_say">Prefer not to say</option>
                    </Select>
                  </div>
                  <div>
                    <Label>Blood Group</Label>
                    <Select {...register("blood_group")}>
                      <option value="">Select</option>
                      {["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"].map(bg => (
                        <option key={bg} value={bg}>{bg}</option>
                      ))}
                    </Select>
                  </div>
                </div>

                <div>
                  <Label>Nationality</Label>
                  <Input placeholder="e.g. Pakistani, American" {...register("nationality")} />
                </div>
              </div>
            )}

            {/* ── Employment Tab ── */}
            {activeTab === "employment" && (
              <div className="space-y-5">
                <SectionHeader icon={Briefcase} title="Employment Details" />

                {/* Role — required on create (a role-less employee has zero
                    permissions and an unusable app). Also editable later,
                    but changing an EXISTING employee's role needs the
                    stricter "roles.manage" permission (matches the dedicated
                    /roles endpoints) — disabled here rather than letting the
                    user pick a new role and only find out it's rejected on
                    save. Creating still allows setting it either way: initial
                    assignment isn't a "reassignment". */}
                <div>
                  <Label required={!isEdit}>Role</Label>
                  {roleOptions.length > 0 ? (
                    <Select {...register("role_id")} disabled={isEdit && !canManageRoles}>
                      <option value="">Select a role</option>
                      {roleOptions.map((r) => (
                        <option key={r.id} value={r.id}>{r.name}</option>
                      ))}
                    </Select>
                  ) : (
                    <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--destructive))]/40 bg-[hsl(var(--destructive))]/5 p-3">
                      <AlertTriangle size={16} className="mt-0.5 shrink-0 text-[hsl(var(--destructive))]" />
                      <p className="text-xs text-[hsl(var(--foreground-subtle))]">
                        No roles exist yet. Create one in <span className="font-medium">Settings → Roles</span> first — every employee must be assigned a role.
                      </p>
                    </div>
                  )}
                  <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">
                    {isEdit && !canManageRoles
                      ? "You don't have permission to change an employee's role."
                      : "Determines what this employee can access. Required."}
                  </p>
                </div>

                {/* Employment Status (Job Nature) — the employee's contractual
                    standing (permanent/probationary/contractual/intern/
                    part-time/temporary). Required in both create and edit;
                    backend: Employee.job_nature (job_nature_enum). */}
                <div>
                  <Label required>Employment Status (Job Nature)</Label>
                  <Select {...register("job_nature")}>
                    <option value="">Select employment status</option>
                    {JOB_NATURE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </Select>
                  <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">
                    E.g. Permanent, Probationary, Contractual, Intern, Part-Time, or Temporary.
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label required>Date of Joining</Label>
                    <Input type="date" error={!!errors.date_of_joining} {...register("date_of_joining")} />
                    {errors.date_of_joining && <p className="mt-1 text-xs text-[hsl(var(--destructive))]">{errors.date_of_joining.message}</p>}
                  </div>
                  <div>
                    <Label>Employment Type</Label>
                    <Select {...register("employment_type")}>
                      <option value="full_time">Full Time</option>
                      <option value="part_time">Part Time</option>
                      <option value="contract">Contract</option>
                      <option value="intern">Intern</option>
                      <option value="freelance">Freelance</option>
                    </Select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label>Department</Label>
                    <Select {...register("department_id")}>
                      <option value="">Select department</option>
                      {departmentOptions.map((d) => (
                        <option key={d.id} value={d.id}>{d.name}</option>
                      ))}
                    </Select>
                  </div>
                  <div>
                    <Label>Designation</Label>
                    <Select {...register("designation_id")}>
                      <option value="">Select designation</option>
                      {designationOptions.map((d) => (
                        <option key={d.id} value={d.id}>{d.title ?? d.name}</option>
                      ))}
                    </Select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label>Branch</Label>
                    <Select {...register("branch_id")}>
                      <option value="">Select branch</option>
                      {branchOptions.map((b) => (
                        <option key={b.id} value={b.id}>{b.name}</option>
                      ))}
                    </Select>
                  </div>
                  <div>
                    <Label>Work Location</Label>
                    <Input placeholder="e.g. Karachi Office, Floor 3" {...register("work_location")} />
                  </div>
                </div>

                <div className="flex items-center gap-3 rounded-lg border border-[hsl(var(--border))] p-3">
                  <input
                    type="checkbox"
                    id="is_remote"
                    className="h-4 w-4 rounded"
                    {...register("is_remote")}
                  />
                  <div>
                    <label htmlFor="is_remote" className="text-sm font-medium cursor-pointer">Remote Employee</label>
                    <p className="text-xs text-[hsl(var(--foreground-muted))]">This employee works remotely</p>
                  </div>
                </div>
              </div>
            )}

            {/* ── Compensation Tab ── */}
            {activeTab === "compensation" && (
              <div className="space-y-5">
                <SectionHeader icon={CreditCard} title="Compensation" />

                <div className="grid grid-cols-3 gap-4">
                  <div className="col-span-2">
                    <Label>Basic Salary</Label>
                    <Input
                      type="number"
                      placeholder="0.00"
                      step="0.01"
                      {...register("current_salary")}
                    />
                  </div>
                  <div>
                    <Label>Currency</Label>
                    <Select {...register("currency")}>
                      <option value="USD">USD</option>
                      <option value="PKR">PKR</option>
                      <option value="EUR">EUR</option>
                      <option value="GBP">GBP</option>
                      <option value="AED">AED</option>
                      <option value="SAR">SAR</option>
                    </Select>
                  </div>
                </div>

                <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-4">
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">
                    💡 Detailed salary structure (allowances, deductions, bonuses) can be configured from the Payroll module after the employee is created.
                  </p>
                </div>
              </div>
            )}

            {/* ── Emergency Tab ── */}
            {activeTab === "emergency" && (
              <div className="space-y-5">
                <SectionHeader icon={Phone} title="Emergency Contact" />

                <div>
                  <Label>Contact Name</Label>
                  <Input placeholder="Jane Smith" {...register("emergency_name")} />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label>Phone Number</Label>
                    <Input type="tel" placeholder="+1 234 567 8900" {...register("emergency_phone")} />
                  </div>
                  <div>
                    <Label>Relationship</Label>
                    <Select {...register("emergency_relationship")}>
                      <option value="">Select</option>
                      <option value="spouse">Spouse</option>
                      <option value="parent">Parent</option>
                      <option value="sibling">Sibling</option>
                      <option value="child">Child</option>
                      <option value="friend">Friend</option>
                      <option value="other">Other</option>
                    </Select>
                  </div>
                </div>
              </div>
            )}
            {/* ── Documents Tab ── */}
            {activeTab === "documents" && (
              isEdit ? (
                // Employee already exists → upload straight to the server.
                <DocumentsPanel employeeId={effectiveEmployeeId as string} />
              ) : (
                // Still on the Add form → stage locally; uploaded on save.
                <StagedDocumentsPanel
                  staged={stagedDocs}
                  onAdd={(d) => setStagedDocs((prev) => [...prev, d])}
                  onRemove={(i) => setStagedDocs((prev) => prev.filter((_, idx) => idx !== i))}
                />
              )
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-[hsl(var(--border))] px-6 py-4">
            <div className="flex gap-2">
              {tabs.map((tab, i) => (
                <div
                  key={tab.id}
                  className={cn(
                    "h-1.5 w-6 rounded-full transition-colors",
                    activeTab === tab.id ? "bg-[hsl(var(--primary))]" : "bg-[hsl(var(--border))]",
                  )}
                />
              ))}
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={handleClose}
                className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--accent))] transition-colors"
              >
                {justCreated && activeTab === "documents" ? "Done" : "Cancel"}
              </button>
              {/* Documents is the last tab now, so Next walks all the way to it
                  — previously Next stopped at Emergency and the Documents tab
                  was only reachable by clicking its pill, which is easy to miss. */}
              {activeTab !== "documents" ? (
                <button
                  type="button"
                  onClick={() => {
                    const tabOrder = ["personal", "employment", "compensation", "emergency", "documents"];
                    const idx = tabOrder.indexOf(activeTab);
                    setActiveTab(tabOrder[idx + 1] as typeof activeTab);
                  }}
                  className="rounded-md bg-[hsl(var(--secondary))] px-4 py-2 text-sm font-medium hover:bg-[hsl(var(--secondary-hover))] transition-colors"
                >
                  Next →
                </button>
              ) : null}
              {/* Submit is shown on every tab except the Documents tab in EDIT
                  mode (there the panel uploads directly and "Done" closes). In
                  ADD mode it stays visible on Documents too, so the user can
                  create the employee — staged documents upload right after. */}
              {(activeTab !== "documents" || !isEdit) && (
                <button
                  type="submit"
                  disabled={isLoading}
                  className="flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60 transition-colors"
                >
                  {isLoading && <Loader2 size={14} className="animate-spin" />}
                  {isLoading
                    ? "Saving..."
                    : isEdit
                    ? "Save Changes"
                    : stagedDocs.length > 0
                    ? `Add Employee & Upload ${stagedDocs.length} doc${stagedDocs.length > 1 ? "s" : ""}`
                    : "Add Employee"}
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
    </>
  );
}

// ── Documents Panel ───────────────────────────────────────────────────────────
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const documentUploadSchema = z.object({
  document_type: z.string().min(1, "Required"),
  title: z.string().min(1, "Required"),
  expiry_date: z.string().optional(),
  notes: z.string().optional(),
});
type DocumentUploadForm = z.infer<typeof documentUploadSchema>;

function DocumentsPanel({ employeeId }: { employeeId: string }) {
  const [showUploadForm, setShowUploadForm] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const { data, isLoading } = useEmployeeDocuments(employeeId);
  const uploadMutation = useUploadEmployeeDocument();
  const deleteMutation = useDeleteEmployeeDocument();

  const { register, handleSubmit, reset, formState: { errors } } = useForm<DocumentUploadForm>({
    resolver: zodResolver(documentUploadSchema),
  });

  async function onUpload(values: DocumentUploadForm) {
    if (!selectedFile) {
      toast.error("Please choose a file to upload");
      return;
    }
    try {
      await uploadMutation.mutateAsync({
        employeeId,
        file: selectedFile,
        documentType: values.document_type as DocumentType,
        title: values.title,
        expiryDate: values.expiry_date || undefined,
        notes: values.notes || undefined,
      });
      toast.success("Document uploaded. It's now locked and cannot be edited.");
      reset();
      setSelectedFile(null);
      setShowUploadForm(false);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message ?? "Upload failed";
      toast.error(msg);
    }
  }

  async function onDelete(documentId: string, title: string) {
    if (!window.confirm(`Delete "${title}"? This permanently removes the file.`)) return;
    try {
      await deleteMutation.mutateAsync({ employeeId, documentId });
      toast.success("Document deleted");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message ?? "You don't have permission to delete documents";
      toast.error(msg);
    }
  }

  async function onDownload(documentId: string, fileName: string) {
    try {
      await downloadEmployeeDocument(employeeId, documentId, fileName);
    } catch {
      toast.error("Download failed");
    }
  }

  const documents = data?.items ?? [];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between border-b border-[hsl(var(--border))] pb-2 mb-4">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[hsl(var(--secondary))]">
            <FileText size={13} className="text-[hsl(var(--foreground-subtle))]" />
          </div>
          <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">Documents</h3>
        </div>
        <button
          type="button"
          onClick={() => setShowUploadForm((v) => !v)}
          className="flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))] transition-colors"
        >
          <Upload size={12} /> Add Document
        </button>
      </div>

      <p className="flex items-start gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-3 text-xs text-[hsl(var(--foreground-muted))]">
        <Lock size={13} className="mt-0.5 shrink-0" />
        Once uploaded, a document is locked — it cannot be edited or replaced. To correct a mistake, an HR admin deletes it and a new one is uploaded.
      </p>

      {showUploadForm && (
        <form
          onSubmit={handleSubmit(onUpload)}
          className="space-y-4 rounded-lg border border-[hsl(var(--border))] p-4"
        >
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label required>Document Type</Label>
              <Select error={!!errors.document_type} {...register("document_type")}>
                <option value="">Select type</option>
                {Object.entries(DOCUMENT_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label required>Title</Label>
              <Input placeholder="e.g. CNIC — Front Side" error={!!errors.title} {...register("title")} />
            </div>
          </div>

          <div>
            <Label required>File</Label>
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx"
              onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
              className="block w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-[hsl(var(--secondary))] file:px-3 file:py-1.5 file:text-xs file:font-medium"
            />
            <p className="mt-1 text-[11px] text-[hsl(var(--foreground-muted))]">PDF, JPG, PNG, WEBP, DOC, DOCX — max 15 MB</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Expiry Date (optional)</Label>
              <Input type="date" {...register("expiry_date")} />
            </div>
            <div>
              <Label>Notes (optional)</Label>
              <Input placeholder="Any additional context" {...register("notes")} />
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => { setShowUploadForm(false); reset(); setSelectedFile(null); }}
              className="rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--accent))]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={uploadMutation.isPending}
              className="flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))] disabled:opacity-60"
            >
              {uploadMutation.isPending && <Loader2 size={12} className="animate-spin" />}
              Upload
            </button>
          </div>
        </form>
      )}

      <div className="space-y-2">
        {isLoading && (
          <p className="text-xs text-[hsl(var(--foreground-muted))]">Loading documents…</p>
        )}
        {!isLoading && documents.length === 0 && (
          <div className="rounded-lg border border-dashed border-[hsl(var(--border))] p-6 text-center text-xs text-[hsl(var(--foreground-muted))]">
            No documents uploaded yet.
          </div>
        )}
        {documents.map((doc) => (
          <div
            key={doc.id}
            className="flex items-center gap-3 rounded-lg border border-[hsl(var(--border))] p-3"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--secondary))]">
              <FileText size={16} className="text-[hsl(var(--foreground-subtle))]" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <p className="truncate text-sm font-medium text-[hsl(var(--foreground))]">{doc.title}</p>
                <Lock size={10} className="shrink-0 text-[hsl(var(--foreground-muted))]" />
              </div>
              <p className="truncate text-xs text-[hsl(var(--foreground-muted))]">
                {DOCUMENT_TYPE_LABELS[doc.document_type]} · {doc.original_file_name} · {formatFileSize(doc.file_size_bytes)}
              </p>
              {doc.expiry_date && (
                <div className="mt-1">
                  {doc.is_expired ? (
                    <Badge variant="error"><AlertTriangle size={10} className="mr-1" />Expired {doc.expiry_date}</Badge>
                  ) : doc.days_until_expiry !== null && doc.days_until_expiry <= 30 ? (
                    <Badge variant="warning"><AlertTriangle size={10} className="mr-1" />Expires in {doc.days_until_expiry}d</Badge>
                  ) : (
                    <Badge variant="outline">Expires {doc.expiry_date}</Badge>
                  )}
                </div>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                title="Download"
                onClick={() => onDownload(doc.id, doc.original_file_name)}
                className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]"
              >
                <Download size={14} />
              </button>
              <button
                type="button"
                title="Delete (HR/admin only)"
                onClick={() => onDelete(doc.id, doc.title)}
                className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--status-error-bg))] hover:text-[hsl(var(--destructive))]"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Staged Documents Panel (Add flow) ─────────────────────────────────────────
// On the Add form the employee doesn't exist yet, so documents can't be uploaded
// (they FK to employees.id). Instead we stage them in memory here — same fields
// as the real upload form — and the drawer flushes them to the server the moment
// the employee is created (see onSubmit's res.data?.id branch).
//
// Critical: NO nested <form>. This panel renders inside the drawer's outer
// <form onSubmit={handleSubmit(onSubmit)}>, and nesting forms is invalid HTML.
// "Add to list" is therefore a type="button" that runs react-hook-form's own
// validation via handleSubmit(addToList) — it never submits the outer form.
function StagedDocumentsPanel({
  staged,
  onAdd,
  onRemove,
}: {
  staged: StagedDoc[];
  onAdd: (doc: StagedDoc) => void;
  onRemove: (index: number) => void;
}) {
  const [showAddForm, setShowAddForm] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const { register, handleSubmit, reset, formState: { errors } } = useForm<DocumentUploadForm>({
    resolver: zodResolver(documentUploadSchema),
  });

  function addToList(values: DocumentUploadForm) {
    if (!selectedFile) {
      toast.error("Please choose a file to add");
      return;
    }
    onAdd({
      file: selectedFile,
      document_type: values.document_type,
      title: values.title,
      expiry_date: values.expiry_date || undefined,
      notes: values.notes || undefined,
    });
    reset();
    setSelectedFile(null);
    setShowAddForm(false);
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between border-b border-[hsl(var(--border))] pb-2 mb-4">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[hsl(var(--secondary))]">
            <FileText size={13} className="text-[hsl(var(--foreground-subtle))]" />
          </div>
          <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">Documents</h3>
        </div>
        <button
          type="button"
          onClick={() => setShowAddForm((v) => !v)}
          className="flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))] transition-colors"
        >
          <Upload size={12} /> Add Document
        </button>
      </div>

      <p className="flex items-start gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-3 text-xs text-[hsl(var(--foreground-muted))]">
        <Lock size={13} className="mt-0.5 shrink-0" />
        These files are held here until you save the employee — they upload automatically the moment the profile is created. Once uploaded, a document is locked and can only be removed by an HR admin.
      </p>

      {showAddForm && (
        <div className="space-y-4 rounded-lg border border-[hsl(var(--border))] p-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label required>Document Type</Label>
              <Select error={!!errors.document_type} {...register("document_type")}>
                <option value="">Select type</option>
                {Object.entries(DOCUMENT_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label required>Title</Label>
              <Input placeholder="e.g. CNIC — Front Side" error={!!errors.title} {...register("title")} />
            </div>
          </div>

          <div>
            <Label required>File</Label>
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx"
              onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
              className="block w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-[hsl(var(--secondary))] file:px-3 file:py-1.5 file:text-xs file:font-medium"
            />
            {selectedFile && (
              <p className="mt-1 text-[11px] text-[hsl(var(--foreground-muted))]">
                Selected: {selectedFile.name} · {formatFileSize(selectedFile.size)}
              </p>
            )}
            <p className="mt-1 text-[11px] text-[hsl(var(--foreground-muted))]">PDF, JPG, PNG, WEBP, DOC, DOCX — max 15 MB</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Expiry Date (optional)</Label>
              <Input type="date" {...register("expiry_date")} />
            </div>
            <div>
              <Label>Notes (optional)</Label>
              <Input placeholder="Any additional context" {...register("notes")} />
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => { setShowAddForm(false); reset(); setSelectedFile(null); }}
              className="rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--accent))]"
            >
              Cancel
            </button>
            {/* type="button" + handleSubmit: validates this sub-form and appends to
                the staged list WITHOUT submitting the drawer's outer <form>. */}
            <button
              type="button"
              onClick={handleSubmit(addToList)}
              className="flex items-center gap-1.5 rounded-md bg-[hsl(var(--primary))] px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary-foreground))] hover:bg-[hsl(var(--primary-hover))]"
            >
              <Upload size={12} /> Add to list
            </button>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {staged.length === 0 && !showAddForm && (
          <div className="rounded-lg border border-dashed border-[hsl(var(--border))] p-6 text-center text-xs text-[hsl(var(--foreground-muted))]">
            No documents added yet. They&apos;ll upload as soon as the employee is saved.
          </div>
        )}
        {staged.map((doc, i) => (
          <div
            key={i}
            className="flex items-center gap-3 rounded-lg border border-[hsl(var(--border))] p-3"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--secondary))]">
              <FileText size={16} className="text-[hsl(var(--foreground-subtle))]" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-[hsl(var(--foreground))]">{doc.title}</p>
              <p className="truncate text-xs text-[hsl(var(--foreground-muted))]">
                {DOCUMENT_TYPE_LABELS[doc.document_type as DocumentType]} · {doc.file.name} · {formatFileSize(doc.file.size)}
                {doc.expiry_date ? ` · expires ${doc.expiry_date}` : ""}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Badge variant="outline">Pending upload</Badge>
              <button
                type="button"
                title="Remove from list"
                onClick={() => onRemove(i)}
                className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--status-error-bg))] hover:text-[hsl(var(--destructive))]"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}