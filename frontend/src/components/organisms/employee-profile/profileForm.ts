import { z } from "zod";

// Everything the Add/Edit Employee form holds beyond the original basics:
// family, addresses, ID documents, bank, insurance, any number of emergency
// contacts, education / work history and recurring pay items. The same schema,
// defaults and API mapping serve BOTH "Add" and "Edit", so the two can never
// drift apart (before, "Add" silently dropped fields that "Edit" saved).

const optionalText = z.string().optional();

const addressShape = z.object({
  street: optionalText,
  city: optionalText,
  state: optionalText,
  postal_code: optionalText,
  country: optionalText,
});

export const profileShape = {
  marital_status: optionalText,
  father_name: optionalText,
  mother_name: optionalText,
  spouse_name: optionalText,

  personal_email: z.union([z.string().email("Invalid email"), z.literal("")]).optional(),
  personal_phone: optionalText,
  address: addressShape.optional(),
  permanent_address: addressShape.optional(),
  permanent_same: z.boolean().optional(),

  national_id: optionalText,
  passport_number: optionalText,
  passport_expiry: optionalText,
  driving_license_number: optionalText,
  driving_license_expiry: optionalText,
  national_id_type: optionalText,
  tax_number: optionalText,
  social_security_number: optionalText,
  provident_fund_number: optionalText,
  visa_number: optionalText,
  visa_expiry: optionalText,
  religion: optionalText,
  place_of_birth: optionalText,
  home_phone: optionalText,
  previous_employee_id: optionalText,
  referral_source: optionalText,
  hobbies: optionalText,
  social_links: z.object({ linkedin: optionalText, twitter: optionalText, github: optionalText, facebook: optionalText, website: optionalText }).optional(),

  bank_name: optionalText,
  bank_account_title: optionalText,
  bank_account_number: optionalText,
  bank_iban: optionalText,
  health_insurance_provider: optionalText,
  health_insurance_number: optionalText,

  emergency_contacts: z
    .array(z.object({ name: optionalText, relationship: optionalText, phone: optionalText, email: optionalText }))
    .default([]),
  education: z
    .array(z.object({ degree: optionalText, institute: optionalText, year: optionalText, grade: optionalText }))
    .default([]),
  work_experience: z
    .array(z.object({ company: optionalText, designation: optionalText, from_date: optionalText, to_date: optionalText }))
    .default([]),
  dependents: z
    .array(z.object({ name: optionalText, relationship: optionalText, date_of_birth: optionalText }))
    .default([]),
  skills: z.array(z.object({ name: optionalText, level: optionalText })).default([]),
  languages: z.array(z.object({ name: optionalText, fluency: optionalText })).default([]),
  certifications: z
    .array(z.object({ name: optionalText, issued_by: optionalText, issued_date: optionalText, expiry_date: optionalText }))
    .default([]),
  compensation_items: z
    .array(
      z.object({
        id: optionalText,
        name: optionalText,
        kind: z.enum(["earning", "deduction"]),
        calculation: z.enum(["fixed", "percent_of_basic"]),
        amount: optionalText,
        percentage: optionalText,
        is_taxable: z.boolean(),
        frequency: z.enum(["recurring", "one_time"]),
        effective_from: optionalText,
        effective_to: optionalText,
      }),
    )
    .default([]),
};

const profileSchema = z.object(profileShape);
export type ProfileFormValues = z.infer<typeof profileSchema>;
export type PayItem = ProfileFormValues["compensation_items"][number];
export type PayItemKind = PayItem["kind"];

export const MAX_EMERGENCY_CONTACTS = 20;
export const MAX_PAY_ITEMS = 50;

export const EMPTY_ADDRESS = { street: "", city: "", state: "", postal_code: "", country: "" };

export const profileDefaults = {
  marital_status: "",
  father_name: "",
  mother_name: "",
  spouse_name: "",
  personal_email: "",
  personal_phone: "",
  address: { ...EMPTY_ADDRESS },
  permanent_address: { ...EMPTY_ADDRESS },
  permanent_same: false,
  national_id: "",
  passport_number: "",
  passport_expiry: "",
  driving_license_number: "",
  driving_license_expiry: "",
  national_id_type: "",
  tax_number: "",
  social_security_number: "",
  provident_fund_number: "",
  visa_number: "",
  visa_expiry: "",
  religion: "",
  place_of_birth: "",
  home_phone: "",
  previous_employee_id: "",
  referral_source: "",
  hobbies: "",
  social_links: { linkedin: "", twitter: "", github: "", facebook: "", website: "" },
  bank_name: "",
  bank_account_title: "",
  bank_account_number: "",
  bank_iban: "",
  health_insurance_provider: "",
  health_insurance_number: "",
  emergency_contacts: [] as ProfileFormValues["emergency_contacts"],
  education: [] as ProfileFormValues["education"],
  work_experience: [] as ProfileFormValues["work_experience"],
  dependents: [] as ProfileFormValues["dependents"],
  skills: [] as ProfileFormValues["skills"],
  languages: [] as ProfileFormValues["languages"],
  certifications: [] as ProfileFormValues["certifications"],
  compensation_items: [] as ProfileFormValues["compensation_items"],
};

export const ALLOWANCE_PRESETS = ["Medical", "Fuel", "Mobile", "Conveyance", "House Rent", "Utilities"];
export const DEDUCTION_PRESETS = ["Loan EMI", "Provident Fund", "Insurance", "Advance Recovery"];

export function newPayItem(kind: PayItemKind, name = ""): PayItem {
  return {
    id: "", name, kind, calculation: "fixed", amount: "", percentage: "", is_taxable: kind === "earning",
    frequency: "recurring", effective_from: "", effective_to: "",
  };
}

// ── API -> form ──────────────────────────────────────────────────────────────
type Json = Record<string, unknown>;
const str = (v: unknown): string => (v === null || v === undefined ? "" : String(v));

function addressFromApi(a: unknown) {
  const o = (a && typeof a === "object" ? a : {}) as Json;
  return {
    street: str(o.street),
    city: str(o.city),
    state: str(o.state),
    postal_code: str(o.postal_code),
    country: str(o.country),
  };
}

const sameAddress = (a: ReturnType<typeof addressFromApi>, b: ReturnType<typeof addressFromApi>) =>
  JSON.stringify(a) === JSON.stringify(b) && Object.values(a).some(Boolean);

export function profileFromApi(data: Json): typeof profileDefaults {
  const address = addressFromApi(data.address);
  const permanent = addressFromApi(data.permanent_address);
  const list = (v: unknown): Json[] => (Array.isArray(v) ? (v as Json[]) : []);
  return {
    marital_status: str(data.marital_status),
    father_name: str(data.father_name),
    mother_name: str(data.mother_name),
    spouse_name: str(data.spouse_name),
    personal_email: str(data.personal_email),
    personal_phone: str(data.personal_phone),
    address,
    permanent_address: permanent,
    permanent_same: sameAddress(address, permanent),
    national_id: str(data.national_id),
    passport_number: str(data.passport_number),
    passport_expiry: str(data.passport_expiry),
    driving_license_number: str(data.driving_license_number),
    driving_license_expiry: str(data.driving_license_expiry),
    national_id_type: str(data.national_id_type),
    tax_number: str(data.tax_number),
    social_security_number: str(data.social_security_number),
    provident_fund_number: str(data.provident_fund_number),
    visa_number: str(data.visa_number),
    visa_expiry: str(data.visa_expiry),
    religion: str(data.religion),
    place_of_birth: str(data.place_of_birth),
    home_phone: str(data.home_phone),
    previous_employee_id: str(data.previous_employee_id),
    referral_source: str(data.referral_source),
    hobbies: str(data.hobbies),
    social_links: {
      linkedin: str(((data.social_links ?? {}) as Json).linkedin),
      twitter: str(((data.social_links ?? {}) as Json).twitter),
      github: str(((data.social_links ?? {}) as Json).github),
      facebook: str(((data.social_links ?? {}) as Json).facebook),
      website: str(((data.social_links ?? {}) as Json).website),
    },
    bank_name: str(data.bank_name),
    bank_account_title: str(data.bank_account_title),
    bank_account_number: str(data.bank_account_number),
    bank_iban: str(data.bank_iban),
    health_insurance_provider: str(data.health_insurance_provider),
    health_insurance_number: str(data.health_insurance_number),
    emergency_contacts: list(data.emergency_contacts).map((c) => ({
      name: str(c.name), relationship: str(c.relationship), phone: str(c.phone), email: str(c.email),
    })),
    education: list(data.education).map((e) => ({
      degree: str(e.degree), institute: str(e.institute), year: str(e.year), grade: str(e.grade),
    })),
    work_experience: list(data.work_experience).map((w) => ({
      company: str(w.company), designation: str(w.designation), from_date: str(w.from_date), to_date: str(w.to_date),
    })),
    dependents: list(data.dependents).map((d) => ({
      name: str(d.name), relationship: str(d.relationship), date_of_birth: str(d.date_of_birth),
    })),
    skills: list(data.skills).map((k) => ({ name: str(k.name), level: str(k.level) })),
    languages: list(data.languages).map((l) => ({ name: str(l.name), fluency: str(l.fluency) })),
    certifications: list(data.certifications).map((c) => ({
      name: str(c.name), issued_by: str(c.issued_by), issued_date: str(c.issued_date), expiry_date: str(c.expiry_date),
    })),
    compensation_items: list(data.compensation_items).map((i) => ({
      id: str(i.id),
      name: str(i.name),
      kind: i.kind === "deduction" ? ("deduction" as const) : ("earning" as const),
      calculation: i.calculation === "percent_of_basic" ? ("percent_of_basic" as const) : ("fixed" as const),
      amount: Number(i.amount) ? str(Number(i.amount)) : "",
      percentage: Number(i.percentage) ? str(Number(i.percentage)) : "",
      is_taxable: i.is_taxable !== false,
      frequency: i.frequency === "one_time" ? ("one_time" as const) : ("recurring" as const),
      effective_from: str(i.effective_from),
      effective_to: str(i.effective_to),
    })),
  };
}

// ── form -> API ──────────────────────────────────────────────────────────────
const orNull = (v?: string) => {
  const t = (v ?? "").trim();
  return t === "" ? null : t;
};

function addressToApi(a?: Partial<typeof EMPTY_ADDRESS>) {
  if (!a) return null;
  const cleaned = Object.fromEntries(Object.entries(a).map(([k, v]) => [k, (v ?? "").trim()]));
  return Object.values(cleaned).some(Boolean) ? cleaned : null;
}

// Only the links that were filled in; null clears them all.
function socialToApi(s?: Partial<Record<string, string>>) {
  const out = Object.fromEntries(
    Object.entries(s ?? {}).map(([k, v]) => [k, (v ?? "").trim()]).filter(([, v]) => v),
  );
  return Object.keys(out).length ? out : null;
}

export function profileToApi(v: ProfileFormValues) {
  return {
    marital_status: orNull(v.marital_status),
    father_name: orNull(v.father_name),
    mother_name: orNull(v.mother_name),
    spouse_name: orNull(v.spouse_name),
    personal_email: orNull(v.personal_email),
    personal_phone: orNull(v.personal_phone),
    address: addressToApi(v.address),
    permanent_address: addressToApi(v.permanent_same ? v.address : v.permanent_address),
    national_id: orNull(v.national_id),
    passport_number: orNull(v.passport_number),
    passport_expiry: orNull(v.passport_expiry),
    driving_license_number: orNull(v.driving_license_number),
    driving_license_expiry: orNull(v.driving_license_expiry),
    national_id_type: orNull(v.national_id_type),
    tax_number: orNull(v.tax_number),
    social_security_number: orNull(v.social_security_number),
    provident_fund_number: orNull(v.provident_fund_number),
    visa_number: orNull(v.visa_number),
    visa_expiry: orNull(v.visa_expiry),
    religion: orNull(v.religion),
    place_of_birth: orNull(v.place_of_birth),
    home_phone: orNull(v.home_phone),
    previous_employee_id: orNull(v.previous_employee_id),
    referral_source: orNull(v.referral_source),
    hobbies: orNull(v.hobbies),
    social_links: socialToApi(v.social_links),
    bank_name: orNull(v.bank_name),
    bank_account_title: orNull(v.bank_account_title),
    bank_account_number: orNull(v.bank_account_number),
    bank_iban: orNull(v.bank_iban),
    health_insurance_provider: orNull(v.health_insurance_provider),
    health_insurance_number: orNull(v.health_insurance_number),
    emergency_contacts: (v.emergency_contacts ?? [])
      .filter((c) => (c.name ?? "").trim())
      .map((c) => ({
        name: c.name!.trim(),
        relationship: orNull(c.relationship),
        phone: orNull(c.phone),
        email: orNull(c.email),
      })),
    education: (v.education ?? [])
      .filter((e) => (e.degree ?? "").trim())
      .map((e) => ({
        degree: e.degree!.trim(), institute: orNull(e.institute), year: orNull(e.year), grade: orNull(e.grade),
      })),
    work_experience: (v.work_experience ?? [])
      .filter((w) => (w.company ?? "").trim())
      .map((w) => ({
        company: w.company!.trim(), designation: orNull(w.designation),
        from_date: orNull(w.from_date), to_date: orNull(w.to_date),
      })),
    dependents: (v.dependents ?? [])
      .filter((d) => (d.name ?? "").trim())
      .map((d) => ({ name: d.name!.trim(), relationship: orNull(d.relationship), date_of_birth: orNull(d.date_of_birth) })),
    skills: (v.skills ?? [])
      .filter((k) => (k.name ?? "").trim())
      .map((k) => ({ name: k.name!.trim(), level: orNull(k.level) })),
    languages: (v.languages ?? [])
      .filter((l) => (l.name ?? "").trim())
      .map((l) => ({ name: l.name!.trim(), fluency: orNull(l.fluency) })),
    certifications: (v.certifications ?? [])
      .filter((c) => (c.name ?? "").trim())
      .map((c) => ({
        name: c.name!.trim(), issued_by: orNull(c.issued_by),
        issued_date: orNull(c.issued_date), expiry_date: orNull(c.expiry_date),
      })),
    compensation_items: (v.compensation_items ?? [])
      .filter((i) => (i.name ?? "").trim())
      .map((i) => ({
        ...(i.id ? { id: i.id } : {}),
        name: i.name!.trim(),
        kind: i.kind,
        calculation: i.calculation,
        amount: i.calculation === "fixed" ? Number(i.amount || 0) : 0,
        percentage: i.calculation === "percent_of_basic" ? Number(i.percentage || 0) : 0,
        is_taxable: i.kind === "earning" ? i.is_taxable : false,
        frequency: i.frequency,
        effective_from: orNull(i.effective_from),
        // A one-time item happens once, so it has no end date.
        effective_to: i.frequency === "one_time" ? null : orNull(i.effective_to),
      })),
  };
}

// ── validation the field-level schema can't express ─────────────────────────
export type ProfileProblem = { tab: "personal" | "compensation" | "emergency" | "background"; message: string };

export function validateProfile(v: ProfileFormValues): ProfileProblem | null {
  for (const i of v.compensation_items ?? []) {
    const name = (i.name ?? "").trim();
    const value = i.calculation === "fixed" ? i.amount : i.percentage;
    const num = Number(value);
    if (!name && (value ?? "").trim()) {
      return { tab: "compensation", message: "Give every allowance / deduction a name." };
    }
    if (!name) continue;
    if (!(value ?? "").trim() || Number.isNaN(num) || num < 0) {
      return { tab: "compensation", message: `Enter a valid ${i.calculation === "fixed" ? "amount" : "percentage"} for "${name}".` };
    }
    if (i.calculation === "percent_of_basic" && num > 100) {
      return { tab: "compensation", message: `"${name}": a percentage can't be more than 100.` };
    }
  }
  for (const i of v.compensation_items ?? []) {
    const name = (i.name ?? "").trim();
    if (!name) continue;
    const from = (i.effective_from ?? "").trim();
    const to = (i.effective_to ?? "").trim();
    if (i.frequency === "one_time" && !from) {
      return { tab: "compensation", message: `"${name}" is a one-time item: pick the date it applies on.` };
    }
    if (i.frequency !== "one_time" && from && to && to < from) {
      return { tab: "compensation", message: `"${name}": the end date can't be before the start date.` };
    }
  }
  for (const c of v.emergency_contacts ?? []) {
    if (!(c.name ?? "").trim() && ((c.phone ?? "").trim() || (c.email ?? "").trim())) {
      return { tab: "emergency", message: "Every emergency contact needs a name." };
    }
  }
  for (const e of v.education ?? []) {
    if (!(e.degree ?? "").trim() && ((e.institute ?? "").trim() || (e.year ?? "").trim())) {
      return { tab: "background", message: "Every education row needs a degree / qualification." };
    }
  }
  for (const d of v.dependents ?? []) {
    if (!(d.name ?? "").trim() && ((d.relationship ?? "").trim() || (d.date_of_birth ?? "").trim())) {
      return { tab: "personal", message: "Every dependent needs a name." };
    }
  }
  for (const w of v.work_experience ?? []) {
    if (!(w.company ?? "").trim() && ((w.designation ?? "").trim() || (w.from_date ?? "").trim())) {
      return { tab: "background", message: "Every work-experience row needs a company." };
    }
  }
  return null;
}

// ── monthly preview (same maths as the payroll run) ─────────────────────────
export function previewTotals(basic: number, items: PayItem[]) {
  const amountOf = (i: PayItem) => {
    const raw = i.calculation === "fixed" ? Number(i.amount) : (basic * Number(i.percentage)) / 100;
    return Number.isFinite(raw) && raw > 0 ? raw : 0;
  };
  // One-time items (a bonus, an advance) are not part of a regular month.
  const named = items.filter((i) => (i.name ?? "").trim() && i.frequency !== "one_time");
  const allowances = named.filter((i) => i.kind === "earning").reduce((s, i) => s + amountOf(i), 0);
  const deductions = named.filter((i) => i.kind === "deduction").reduce((s, i) => s + amountOf(i), 0);
  const safeBasic = Number.isFinite(basic) && basic > 0 ? basic : 0;
  return { allowances, deductions, gross: safeBasic + allowances, net: safeBasic + allowances - deductions };
}
