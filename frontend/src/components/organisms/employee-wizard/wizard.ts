/**
 * Add-Employee wizard: form schema, step map and payload builder.
 *
 * Pure logic, no React — so the rules (what is required, which step a field
 * belongs to, what gets sent to the API) can be tested on their own.
 *
 * The field set and the create payload are the SAME ones the old drawer used
 * (components/organisms/EmployeeDrawer.tsx). Backend contract: POST /employees,
 * EmployeeCreateSchema in backend/app/schemas/employee.py.
 */
import { z } from "zod";

// ── Steps ────────────────────────────────────────────────────────────────────
export const STEPS = [
  { id: "personal", check: "Personal information",   label: "Personal",   title: "Let's start with the basics",   subtitle: "Add the employee's personal information first." },
  { id: "role", check: "Role & department",       label: "Role",       title: "Role & department",             subtitle: "Where this person fits in the organisation and what they can access." },
  { id: "pay", check: "Pay & benefits",        label: "Pay",        title: "Pay & benefits",                subtitle: "Basic salary and currency. Allowances and deductions are set up in Payroll." },
  { id: "emergency", check: "Emergency contact",  label: "Emergency",  title: "Emergency contact",             subtitle: "Who we should call if something happens. Optional." },
  { id: "documents", check: "Documents",  label: "Documents",  title: "Documents",                     subtitle: "Attach onboarding documents. They upload as soon as the employee is created." },
  { id: "review", check: "Review & submit",     label: "Review",     title: "Review & create",               subtitle: "Check everything before creating the employee." },
] as const;

export type StepId = (typeof STEPS)[number]["id"];
export const LAST_STEP = STEPS.length - 1;

// ── Option lists (the fixed enums — database-backed lists come from the API) ─
export const GENDER_OPTIONS = [
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "non_binary", label: "Non-binary" },
  { value: "prefer_not_to_say", label: "Prefer not to say" },
] as const;

export const BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"] as const;

// Backend enum: app/models/employee.py::JobNature
export const JOB_NATURE_OPTIONS = [
  { value: "permanent", label: "Permanent / Regular" },
  { value: "probationary", label: "Probationary" },
  { value: "contractual", label: "Contractual / Fixed-Term" },
  { value: "intern", label: "Intern / Trainee" },
  { value: "part_time", label: "Part-Time" },
  { value: "temporary", label: "Temporary / Casual" },
] as const;

export const EMPLOYMENT_TYPE_OPTIONS = [
  { value: "full_time", label: "Full Time" },
  { value: "part_time", label: "Part Time" },
  { value: "contract", label: "Contract" },
  { value: "intern", label: "Intern" },
  { value: "freelance", label: "Freelance" },
] as const;

export const CURRENCY_OPTIONS = ["USD", "PKR", "EUR", "GBP", "AED", "SAR"] as const;

export const RELATIONSHIP_OPTIONS = [
  { value: "spouse", label: "Spouse" },
  { value: "parent", label: "Parent" },
  { value: "sibling", label: "Sibling" },
  { value: "child", label: "Child" },
  { value: "friend", label: "Friend" },
  { value: "other", label: "Other" },
] as const;

export function labelOf(options: readonly { value: string; label: string }[], value: string | undefined): string {
  return options.find((o) => o.value === value)?.label ?? "";
}

// ── Documents (same rules as the drawer's upload panel) ──────────────────────
export const DOC_ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx";
export const DOC_EXTENSIONS = ["pdf", "jpg", "jpeg", "png", "webp", "doc", "docx"] as const;
export const DOC_MAX_BYTES = 15 * 1024 * 1024;

export type StagedDoc = {
  id: string;
  file: File;
  document_type: string;
  title: string;
  expiry_date?: string;
  notes?: string;
};

/** null when the file is acceptable, otherwise the reason it is not. */
export function validateDocumentFile(file: File | null | undefined): string | null {
  if (!file) return "Choose a file to add.";
  const ext = file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "";
  if (!(DOC_EXTENSIONS as readonly string[]).includes(ext)) return "Use PDF, JPG, PNG, WEBP, DOC or DOCX.";
  if (file.size === 0) return "This file is empty.";
  if (file.size > DOC_MAX_BYTES) return "File is larger than 15 MB.";
  return null;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Form schema ──────────────────────────────────────────────────────────────
// Dates stay "YYYY-MM-DD" strings end to end (what <input type="date"> gives and
// what the API takes), so no timezone/locale parsing can shift a day.
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
// Permissive on purpose: international numbers, spaces, dashes, brackets.
const PHONE = /^\+?[\d\s().-]{6,20}$/;

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const optionalPhone = z
  .string()
  .trim()
  .refine((v) => v === "" || PHONE.test(v), "Enter a valid phone number");

export const employeeWizardSchema = z
  .object({
    // Personal
    first_name: z.string().trim().min(1, "First name is required").max(100),
    last_name: z.string().trim().min(1, "Last name is required").max(100),
    email: z.string().trim().min(1, "Work email is required").email("Enter a valid email address"),
    phone: optionalPhone,
    date_of_birth: z
      .string()
      .refine((v) => v === "" || (ISO_DATE.test(v) && v <= todayIso()), "Date of birth can't be in the future"),
    gender: z.enum(["", "male", "female", "non_binary", "prefer_not_to_say"]),
    nationality: z.string().trim().max(100),
    blood_group: z.string().refine((v) => v === "" || (BLOOD_GROUPS as readonly string[]).includes(v), "Pick a valid blood group"),

    // Role & employment
    role_id: z.string().min(1, "Assign a role — every employee needs one"),
    job_nature: z.string().min(1, "Select an employment status"),
    date_of_joining: z.string().min(1, "Joining date is required").refine((v) => ISO_DATE.test(v), "Enter a valid date"),
    employment_type: z.enum(["full_time", "part_time", "contract", "intern", "freelance"]),
    department_id: z.string(),
    designation_id: z.string(),
    branch_id: z.string(),
    default_shift_id: z.string(),
    work_location: z.string().trim().max(200),
    is_remote: z.boolean(),

    // Pay
    current_salary: z
      .string()
      .trim()
      .refine((v) => v === "" || (/^\d+(\.\d{1,2})?$/.test(v) && Number(v) >= 0), "Enter an amount like 85000 or 85000.50"),
    currency: z.string().length(3),

    // Emergency contact
    emergency_name: z.string().trim().max(200),
    emergency_phone: optionalPhone,
    emergency_relationship: z.string(),
  });

/**
 * Rules that span fields (kept out of the zod object so they run on their own
 * step, even while later steps are still blank). The old drawer silently dropped
 * the phone/relationship when no contact name was typed; flag it instead so
 * nothing the user entered disappears.
 */
export function crossFieldErrors(v: Pick<EmployeeWizardValues, "emergency_name" | "emergency_phone" | "emergency_relationship">) {
  const errs: { field: keyof EmployeeWizardValues; message: string }[] = [];
  if (!v.emergency_name.trim() && (v.emergency_phone.trim() || v.emergency_relationship)) {
    errs.push({ field: "emergency_name", message: "Add the contact's name, or clear the other fields" });
  }
  return errs;
}

export type EmployeeWizardValues = z.infer<typeof employeeWizardSchema>;

export const DEFAULT_VALUES: EmployeeWizardValues = {
  first_name: "", last_name: "", email: "", phone: "", date_of_birth: "", gender: "", nationality: "", blood_group: "",
  role_id: "", job_nature: "probationary", date_of_joining: "", employment_type: "full_time",
  department_id: "", designation_id: "", branch_id: "", default_shift_id: "", work_location: "", is_remote: false,
  current_salary: "", currency: "USD",
  emergency_name: "", emergency_phone: "", emergency_relationship: "",
};

/** Which step each field is edited on — drives "go to the step with the error". */
export const FIELD_STEP: Record<keyof EmployeeWizardValues, StepId> = {
  first_name: "personal", last_name: "personal", email: "personal", phone: "personal",
  date_of_birth: "personal", gender: "personal", nationality: "personal", blood_group: "personal",
  role_id: "role", job_nature: "role", date_of_joining: "role", employment_type: "role",
  department_id: "role", designation_id: "role", branch_id: "role", default_shift_id: "role",
  work_location: "role", is_remote: "role",
  current_salary: "pay", currency: "pay",
  emergency_name: "emergency", emergency_phone: "emergency", emergency_relationship: "emergency",
};

export function fieldsOfStep(step: StepId): (keyof EmployeeWizardValues)[] {
  return (Object.keys(FIELD_STEP) as (keyof EmployeeWizardValues)[]).filter((f) => FIELD_STEP[f] === step);
}

/** Index of the first step that owns one of the given fields, or -1. */
export function firstStepWithError(fields: string[]): number {
  const idx = fields
    .map((f) => FIELD_STEP[f as keyof EmployeeWizardValues])
    .filter(Boolean)
    .map((s) => STEPS.findIndex((x) => x.id === s));
  return idx.length ? Math.min(...idx) : -1;
}

// ── API payload ──────────────────────────────────────────────────────────────
/**
 * Body for POST /employees — exactly the fields the old drawer sent.
 * Blank optional values become null; salary is sent as a number.
 */
export function buildCreatePayload(v: EmployeeWizardValues) {
  const emergency_contact = v.emergency_name
    ? { name: v.emergency_name, phone: v.emergency_phone || null, relationship: v.emergency_relationship || null }
    : null;
  return {
    first_name: v.first_name,
    last_name: v.last_name,
    email: v.email,
    date_of_joining: v.date_of_joining,
    employment_type: v.employment_type,
    job_nature: v.job_nature,
    role_id: v.role_id,
    department_id: v.department_id || null,
    designation_id: v.designation_id || null,
    branch_id: v.branch_id || null,
    default_shift_id: v.default_shift_id || null,
    work_location: v.work_location || null,
    is_remote: v.is_remote,
    current_salary: v.current_salary ? parseFloat(v.current_salary) : null,
    currency: v.currency,
    phone: v.phone || null,
    date_of_birth: v.date_of_birth || null,
    gender: v.gender || null,
    nationality: v.nationality || null,
    blood_group: v.blood_group || null,
    emergency_contact,
  };
}

/**
 * The create endpoint's schema does not list nationality, blood group or the
 * emergency contact (the backend ignores unknown fields there), while the
 * update endpoint stores them. So after a successful create the wizard saves
 * them with the same PATCH the Edit drawer uses. null when there is nothing to save.
 */
export function buildFollowUpPatch(v: EmployeeWizardValues) {
  const p = buildCreatePayload(v);
  const patch: Record<string, unknown> = {};
  if (p.nationality) patch.nationality = p.nationality;
  if (p.blood_group) patch.blood_group = p.blood_group;
  if (p.emergency_contact) patch.emergency_contact = p.emergency_contact;
  return Object.keys(patch).length ? patch : null;
}

/** A readable message from an axios-style error, or "" when there is none. */
export function serverMessage(err: unknown): string {
  const e = err as { response?: { data?: { message?: string; detail?: unknown } } };
  const m = e?.response?.data?.message;
  if (typeof m === "string" && m) return m;
  const d = e?.response?.data?.detail;
  return typeof d === "string" ? d : "";
}

/** A server field name -> wizard field, when the server names one we have. */
export function serverFieldErrors(err: unknown): { field: keyof EmployeeWizardValues; message: string }[] {
  const e = err as { response?: { data?: { errors?: unknown; detail?: unknown } } };
  const raw = e?.response?.data?.errors ?? e?.response?.data?.detail;
  if (!Array.isArray(raw)) return [];
  const out: { field: keyof EmployeeWizardValues; message: string }[] = [];
  for (const item of raw as { loc?: unknown[]; field?: string; msg?: string; message?: string }[]) {
    const name = (item.field ?? (Array.isArray(item.loc) ? String(item.loc[item.loc.length - 1]) : "")) as string;
    const field = (name === "date_of_joining" || name in FIELD_STEP ? name : "") as keyof EmployeeWizardValues;
    const message = item.msg ?? item.message;
    if (field && message) out.push({ field, message });
  }
  return out;
}
