"use client";

import { useEffect, useRef, useState } from "react";
import { useFieldArray, useFormContext } from "react-hook-form";
import { Plus, Trash2, Users, MapPin, FileText, Landmark, GraduationCap, Briefcase, Phone, Wallet, Camera, Award, Languages, Wrench, Baby } from "lucide-react";
import { Input, Label, Select, SectionHeader } from "./fields";
import { resolveMediaUrl } from "@/utils/media";
import {
  ALLOWANCE_PRESETS,
  DEDUCTION_PRESETS,
  MAX_EMERGENCY_CONTACTS,
  MAX_PAY_ITEMS,
  newPayItem,
  previewTotals,
  type PayItemKind,
  type ProfileFormValues,
} from "./profileForm";

// All sections read the surrounding <FormProvider>, so the Employee drawer
// just drops them into the right tab.

const ghostButton =
  "inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1.5 text-xs font-semibold text-[hsl(var(--foreground-subtle))] hover:bg-[hsl(var(--accent))] transition-colors";

function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--destructive))]"
    >
      <Trash2 size={15} />
    </button>
  );
}

// ── Personal tab: family, contact, addresses, ID documents ──────────────────
function AddressFields({ prefix, disabled }: { prefix: "address" | "permanent_address"; disabled?: boolean }) {
  const { register } = useFormContext<ProfileFormValues>();
  const who = prefix === "address" ? "Current" : "Permanent";
  return (
    <div className="space-y-3">
      <div>
        <Label>Street / Area</Label>
        <Input aria-label={`${who} street`} disabled={disabled} placeholder="House 12, Street 4" {...register(`${prefix}.street`)} />
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <Label>City</Label>
          <Input aria-label={`${who} city`} disabled={disabled} {...register(`${prefix}.city`)} />
        </div>
        <div>
          <Label>State / Province</Label>
          <Input aria-label={`${who} state`} disabled={disabled} {...register(`${prefix}.state`)} />
        </div>
        <div>
          <Label>Postal Code</Label>
          <Input aria-label={`${who} postal code`} disabled={disabled} {...register(`${prefix}.postal_code`)} />
        </div>
      </div>
      <div>
        <Label>Country</Label>
        <Input aria-label={`${who} country`} disabled={disabled} {...register(`${prefix}.country`)} />
      </div>
    </div>
  );
}

export function PersonalExtrasSection() {
  const { register, watch, formState: { errors } } = useFormContext<ProfileFormValues>();
  const same = watch("permanent_same");
  return (
    <div className="space-y-6">
      <div>
        <SectionHeader icon={Users} title="Family" />
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Marital Status</Label>
            <Select {...register("marital_status")}>
              <option value="">Select</option>
              <option value="single">Single</option>
              <option value="married">Married</option>
              <option value="divorced">Divorced</option>
              <option value="widowed">Widowed</option>
            </Select>
          </div>
          <div>
            <Label>Spouse Name</Label>
            <Input {...register("spouse_name")} />
          </div>
          <div>
            <Label>Father&apos;s Name</Label>
            <Input {...register("father_name")} />
          </div>
          <div>
            <Label>Mother&apos;s Name</Label>
            <Input {...register("mother_name")} />
          </div>
        </div>
      </div>

      <DependentsSection />

      <div>
        <SectionHeader icon={Phone} title="Personal Contact" />
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Personal Email</Label>
            <Input type="email" placeholder="name@gmail.com" error={!!errors.personal_email} {...register("personal_email")} />
            {errors.personal_email && (
              <p className="mt-1 text-xs text-[hsl(var(--destructive))]">{errors.personal_email.message}</p>
            )}
          </div>
          <div>
            <Label>Personal Phone</Label>
            <Input type="tel" {...register("personal_phone")} />
          </div>
        </div>
      </div>

      <div>
        <SectionHeader icon={MapPin} title="Current Address" />
        <AddressFields prefix="address" />
      </div>

      <div>
        <SectionHeader icon={MapPin} title="Permanent Address" />
        <label className="mb-3 flex items-center gap-2 text-sm">
          <input type="checkbox" aria-label="Same as current address" className="h-4 w-4" {...register("permanent_same")} />
          Same as current address
        </label>
        <AddressFields prefix="permanent_address" disabled={!!same} />
      </div>

      <div>
        <SectionHeader icon={FileText} title="Identity Documents" />
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <Label>CNIC / National ID</Label>
            <Input placeholder="00000-0000000-0" {...register("national_id")} />
          </div>
          <div>
            <Label>Passport Number</Label>
            <Input {...register("passport_number")} />
          </div>
          <div>
            <Label>Passport Expiry</Label>
            <Input type="date" {...register("passport_expiry")} />
          </div>
          <div>
            <Label>Driving Licence Number</Label>
            <Input {...register("driving_license_number")} />
          </div>
          <div>
            <Label>Driving Licence Expiry</Label>
            <Input type="date" {...register("driving_license_expiry")} />
          </div>
        </div>
      </div>

      <div>
        <SectionHeader icon={FileText} title="Tax, Social Security & Visa" />
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>ID Type</Label>
            <Select aria-label="ID Type" {...register("national_id_type")}>
              <option value="">Select</option>
              <option value="cnic">CNIC</option>
              <option value="passport">Passport</option>
              <option value="ssn">SSN</option>
              <option value="nin">NIN</option>
              <option value="other">Other</option>
            </Select>
          </div>
          <div>
            <Label>Tax Number (NTN / TIN)</Label>
            <Input aria-label="Tax Number (NTN / TIN)" {...register("tax_number")} />
          </div>
          <div>
            <Label>EOBI / Social Security No.</Label>
            <Input aria-label="EOBI / Social Security No." {...register("social_security_number")} />
          </div>
          <div>
            <Label>Provident Fund No.</Label>
            <Input aria-label="Provident Fund No." {...register("provident_fund_number")} />
          </div>
          <div>
            <Label>Visa / Work Permit No.</Label>
            <Input aria-label="Visa / Work Permit No." {...register("visa_number")} />
          </div>
          <div>
            <Label>Visa Expiry</Label>
            <Input type="date" aria-label="Visa Expiry" {...register("visa_expiry")} />
          </div>
        </div>
      </div>

      <div>
        <SectionHeader icon={Users} title="More About Me" />
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Religion</Label>
            <Input aria-label="Religion" {...register("religion")} />
          </div>
          <div>
            <Label>Place of Birth</Label>
            <Input aria-label="Place of Birth" {...register("place_of_birth")} />
          </div>
          <div>
            <Label>Home Phone</Label>
            <Input type="tel" aria-label="Home Phone" {...register("home_phone")} />
          </div>
          <div>
            <Label>Previous Employee ID</Label>
            <Input aria-label="Previous Employee ID" {...register("previous_employee_id")} />
          </div>
          <div>
            <Label>How did they hear about us?</Label>
            <Input aria-label="How did they hear about us?" {...register("referral_source")} />
          </div>
          <div className="col-span-2">
            <Label>Hobbies &amp; Interests</Label>
            <Input aria-label="Hobbies & Interests" {...register("hobbies")} />
          </div>
          {(
            [["linkedin", "LinkedIn"], ["twitter", "Twitter / X"], ["github", "GitHub"], ["facebook", "Facebook"], ["website", "Website"]] as const
          ).map(([k, label]) => (
            <div key={k}>
              <Label>{label}</Label>
              <Input type="url" placeholder="https://" aria-label={label} {...register(`social_links.${k}`)} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Compensation tab: allowances & deductions ───────────────────────────────
export function PayItemsSection({ currency, basic }: { currency: string; basic: number }) {
  const { register, control, watch } = useFormContext<ProfileFormValues>();
  const { fields, append, remove } = useFieldArray({ control, name: "compensation_items" });
  const items = watch("compensation_items") ?? [];
  const totals = previewTotals(basic, items);
  const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  const atLimit = fields.length >= MAX_PAY_ITEMS;

  function addPreset(kind: PayItemKind, name = "") {
    if (!atLimit) append(newPayItem(kind, name));
  }

  return (
    <div className="space-y-4">
      <SectionHeader icon={Wallet} title="Allowances & Deductions" />
      <p className="text-xs text-[hsl(var(--foreground-muted))]">
        Extra pay on top of the basic salary: allowances are added to every payslip, deductions are taken off. They
        apply to employees who have a salary structure assigned in Payroll; a percentage is worked out on that basic
        salary.
      </p>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-[hsl(var(--foreground-subtle))]">Add allowance:</span>
          {ALLOWANCE_PRESETS.map((p) => (
            <button key={p} type="button" className={ghostButton} onClick={() => addPreset("earning", p)}>
              <Plus size={12} /> {p}
            </button>
          ))}
          <button type="button" className={ghostButton} onClick={() => addPreset("earning")}>
            <Plus size={12} /> Other
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-[hsl(var(--foreground-subtle))]">Add deduction:</span>
          {DEDUCTION_PRESETS.map((p) => (
            <button key={p} type="button" className={ghostButton} onClick={() => addPreset("deduction", p)}>
              <Plus size={12} /> {p}
            </button>
          ))}
          <button type="button" className={ghostButton} onClick={() => addPreset("deduction")}>
            <Plus size={12} /> Other
          </button>
        </div>
      </div>

      {fields.length === 0 ? (
        <p className="rounded-md border border-dashed border-[hsl(var(--border))] px-4 py-6 text-center text-sm text-[hsl(var(--foreground-muted))]">
          No allowances or deductions yet. Use the buttons above to add Medical, Fuel, a loan instalment and so on.
        </p>
      ) : (
        <div className="space-y-3">
          {fields.map((field, index) => {
            const kind = items[index]?.kind ?? field.kind;
            const calc = items[index]?.calculation ?? field.calculation;
            const frequency = items[index]?.frequency ?? field.frequency;
            return (
              <div
                key={field.id}
                data-testid={`pay-item-${index}`}
                className="rounded-lg border border-[hsl(var(--border))] p-3"
              >
                <div className="grid grid-cols-12 items-end gap-3">
                  <div className="col-span-3">
                    <Label>Name</Label>
                    <Input aria-label={`Pay item ${index + 1} name`} placeholder="e.g. Medical" {...register(`compensation_items.${index}.name`)} />
                  </div>
                  <div className="col-span-3">
                    <Label>Type</Label>
                    <Select aria-label={`Pay item ${index + 1} type`} {...register(`compensation_items.${index}.kind`)}>
                      <option value="earning">Allowance (+)</option>
                      <option value="deduction">Deduction (−)</option>
                    </Select>
                  </div>
                  <div className="col-span-3">
                    <Label>Based on</Label>
                    <Select aria-label={`Pay item ${index + 1} based on`} {...register(`compensation_items.${index}.calculation`)}>
                      <option value="fixed">Fixed</option>
                      <option value="percent_of_basic">% of basic</option>
                    </Select>
                  </div>
                  <div className="col-span-2">
                    <Label>{calc === "fixed" ? `Amount (${currency})` : "Percent"}</Label>
                    {calc === "fixed" ? (
                      <Input
                        key="amount"
                        type="number" min="0" step="0.01" aria-label={`Pay item ${index + 1} amount`}
                        {...register(`compensation_items.${index}.amount`)}
                      />
                    ) : (
                      <Input
                        key="percentage"
                        type="number" min="0" max="100" step="0.01" aria-label={`Pay item ${index + 1} percentage`}
                        {...register(`compensation_items.${index}.percentage`)}
                      />
                    )}
                  </div>
                  <div className="col-span-1 flex justify-end">
                    <RemoveButton label={`Remove pay item ${index + 1}`} onClick={() => remove(index)} />
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-12 items-end gap-3">
                  <div className="col-span-4">
                    <Label>Applies</Label>
                    <Select aria-label={`Pay item ${index + 1} frequency`} {...register(`compensation_items.${index}.frequency`)}>
                      <option value="recurring">Every month (recurring)</option>
                      <option value="one_time">One time only</option>
                    </Select>
                  </div>
                  <div className="col-span-4">
                    <Label>{frequency === "one_time" ? "Applies on" : "Effective from"}</Label>
                    <Input type="date" aria-label={`Pay item ${index + 1} effective from`} {...register(`compensation_items.${index}.effective_from`)} />
                  </div>
                  {frequency !== "one_time" && (
                    <div className="col-span-4">
                      <Label>Effective to (optional)</Label>
                      <Input type="date" aria-label={`Pay item ${index + 1} effective to`} {...register(`compensation_items.${index}.effective_to`)} />
                    </div>
                  )}
                </div>
                {kind === "earning" && (
                  <label className="mt-2 flex items-center gap-2 text-xs text-[hsl(var(--foreground-subtle))]">
                    <input type="checkbox" aria-label={`Pay item ${index + 1} taxable`} className="h-3.5 w-3.5" {...register(`compensation_items.${index}.is_taxable`)} />
                    Counts as taxable income
                  </label>
                )}
              </div>
            );
          })}
        </div>
      )}

      {fields.length > 0 && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-4 text-sm" data-testid="pay-preview">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--foreground-muted))]">
            Monthly preview (before attendance &amp; tax)
          </p>
          <div className="space-y-1">
            <div className="flex justify-between"><span>Basic salary</span><span>{currency} {fmt(basic)}</span></div>
            <div className="flex justify-between"><span>+ Allowances</span><span>{currency} {fmt(totals.allowances)}</span></div>
            <div className="flex justify-between"><span>− Deductions</span><span>{currency} {fmt(totals.deductions)}</span></div>
            <div className="flex justify-between border-t border-[hsl(var(--border))] pt-1 font-semibold">
              <span>Take-home (approx.)</span><span>{currency} {fmt(totals.net)}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Compensation tab: bank & insurance ──────────────────────────────────────
export function BankInsuranceSection() {
  const { register } = useFormContext<ProfileFormValues>();
  return (
    <div className="space-y-6">
      <div>
        <SectionHeader icon={Landmark} title="Bank Account" />
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Bank Name</Label>
            <Input {...register("bank_name")} />
          </div>
          <div>
            <Label>Account Title</Label>
            <Input {...register("bank_account_title")} />
          </div>
          <div>
            <Label>Account Number</Label>
            <Input {...register("bank_account_number")} />
          </div>
          <div>
            <Label>IBAN</Label>
            <Input {...register("bank_iban")} />
          </div>
        </div>
      </div>
      <div>
        <SectionHeader icon={FileText} title="Health Insurance" />
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Provider</Label>
            <Input {...register("health_insurance_provider")} />
          </div>
          <div>
            <Label>Policy / Card Number</Label>
            <Input {...register("health_insurance_number")} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Emergency tab: any number of contacts ───────────────────────────────────
export function EmergencyContactsSection() {
  const { register, control } = useFormContext<ProfileFormValues>();
  const { fields, append, remove } = useFieldArray({ control, name: "emergency_contacts" });
  const atLimit = fields.length >= MAX_EMERGENCY_CONTACTS;

  return (
    <div className="space-y-4">
      <SectionHeader icon={Phone} title="Emergency Contacts" />
      {fields.length === 0 && (
        <p className="rounded-md border border-dashed border-[hsl(var(--border))] px-4 py-6 text-center text-sm text-[hsl(var(--foreground-muted))]">
          No emergency contacts yet.
        </p>
      )}
      {fields.map((field, index) => (
        <div key={field.id} data-testid={`emergency-contact-${index}`} className="rounded-lg border border-[hsl(var(--border))] p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-[hsl(var(--foreground-subtle))]">Contact {index + 1}</span>
            <RemoveButton label={`Remove emergency contact ${index + 1}`} onClick={() => remove(index)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Name</Label>
              <Input aria-label={`Emergency contact ${index + 1} name`} placeholder="Jane Smith" {...register(`emergency_contacts.${index}.name`)} />
            </div>
            <div>
              <Label>Relationship</Label>
              <Select aria-label={`Emergency contact ${index + 1} relationship`} {...register(`emergency_contacts.${index}.relationship`)}>
                <option value="">Select</option>
                <option value="spouse">Spouse</option>
                <option value="parent">Parent</option>
                <option value="sibling">Sibling</option>
                <option value="child">Child</option>
                <option value="friend">Friend</option>
                <option value="other">Other</option>
              </Select>
            </div>
            <div>
              <Label>Phone</Label>
              <Input type="tel" aria-label={`Emergency contact ${index + 1} phone`} {...register(`emergency_contacts.${index}.phone`)} />
            </div>
            <div>
              <Label>Email</Label>
              <Input type="email" aria-label={`Emergency contact ${index + 1} email`} {...register(`emergency_contacts.${index}.email`)} />
            </div>
          </div>
        </div>
      ))}
      <button
        type="button"
        className={ghostButton}
        disabled={atLimit}
        onClick={() => append({ name: "", relationship: "", phone: "", email: "" })}
      >
        <Plus size={12} /> Add emergency contact
      </button>
      {atLimit && (
        <p className="text-xs text-[hsl(var(--foreground-muted))]">
          You can add up to {MAX_EMERGENCY_CONTACTS} contacts.
        </p>
      )}
    </div>
  );
}

// ── Background tab: education & work experience ─────────────────────────────
export function BackgroundSection() {
  const { register, control } = useFormContext<ProfileFormValues>();
  const edu = useFieldArray({ control, name: "education" });
  const exp = useFieldArray({ control, name: "work_experience" });

  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <SectionHeader icon={GraduationCap} title="Education" />
        {edu.fields.map((field, index) => (
          <div key={field.id} data-testid={`education-${index}`} className="rounded-lg border border-[hsl(var(--border))] p-3">
            <div className="grid grid-cols-12 items-end gap-3">
              <div className="col-span-4">
                <Label>Degree / Qualification</Label>
                <Input aria-label={`Education ${index + 1} degree`} placeholder="BS Computer Science" {...register(`education.${index}.degree`)} />
              </div>
              <div className="col-span-4">
                <Label>Institute</Label>
                <Input aria-label={`Education ${index + 1} institute`} {...register(`education.${index}.institute`)} />
              </div>
              <div className="col-span-1">
                <Label>Year</Label>
                <Input aria-label={`Education ${index + 1} year`} maxLength={4} {...register(`education.${index}.year`)} />
              </div>
              <div className="col-span-2">
                <Label>Grade / CGPA</Label>
                <Input aria-label={`Education ${index + 1} grade`} {...register(`education.${index}.grade`)} />
              </div>
              <div className="col-span-1 flex justify-end">
                <RemoveButton label={`Remove education ${index + 1}`} onClick={() => edu.remove(index)} />
              </div>
            </div>
          </div>
        ))}
        <button type="button" className={ghostButton} onClick={() => edu.append({ degree: "", institute: "", year: "", grade: "" })}>
          <Plus size={12} /> Add education
        </button>
      </div>

      <div className="space-y-4">
        <SectionHeader icon={Briefcase} title="Previous Work Experience" />
        {exp.fields.map((field, index) => (
          <div key={field.id} data-testid={`experience-${index}`} className="rounded-lg border border-[hsl(var(--border))] p-3">
            <div className="grid grid-cols-12 items-end gap-3">
              <div className="col-span-5">
                <Label>Company</Label>
                <Input aria-label={`Experience ${index + 1} company`} {...register(`work_experience.${index}.company`)} />
              </div>
              <div className="col-span-3">
                <Label>Designation</Label>
                <Input aria-label={`Experience ${index + 1} designation`} {...register(`work_experience.${index}.designation`)} />
              </div>
              <div className="col-span-2">
                <Label>From</Label>
                <Input type="date" aria-label={`Experience ${index + 1} from`} {...register(`work_experience.${index}.from_date`)} />
              </div>
              <div className="col-span-2">
                <Label>To</Label>
                <Input type="date" aria-label={`Experience ${index + 1} to`} {...register(`work_experience.${index}.to_date`)} />
              </div>
            </div>
            <div className="mt-2 flex justify-end">
              <RemoveButton label={`Remove experience ${index + 1}`} onClick={() => exp.remove(index)} />
            </div>
          </div>
        ))}
        <button type="button" className={ghostButton} onClick={() => exp.append({ company: "", designation: "", from_date: "", to_date: "" })}>
          <Plus size={12} /> Add experience
        </button>
      </div>
    </div>
  );
}

// ── Personal tab: dependents ────────────────────────────────────────────────
export function DependentsSection() {
  const { register, control } = useFormContext<ProfileFormValues>();
  const { fields, append, remove } = useFieldArray({ control, name: "dependents" });
  return (
    <div className="space-y-3">
      <SectionHeader icon={Baby} title="Dependents" />
      {fields.map((field, index) => (
        <div key={field.id} data-testid={`dependent-${index}`} className="rounded-lg border border-[hsl(var(--border))] p-3">
          <div className="grid grid-cols-12 items-end gap-3">
            <div className="col-span-5">
              <Label>Name</Label>
              <Input aria-label={`Dependent ${index + 1} name`} {...register(`dependents.${index}.name`)} />
            </div>
            <div className="col-span-3">
              <Label>Relationship</Label>
              <Select aria-label={`Dependent ${index + 1} relationship`} {...register(`dependents.${index}.relationship`)}>
                <option value="">Select</option>
                <option value="spouse">Spouse</option>
                <option value="child">Child</option>
                <option value="parent">Parent</option>
                <option value="other">Other</option>
              </Select>
            </div>
            <div className="col-span-3">
              <Label>Date of Birth</Label>
              <Input type="date" aria-label={`Dependent ${index + 1} date of birth`} {...register(`dependents.${index}.date_of_birth`)} />
            </div>
            <div className="col-span-1 flex justify-end">
              <RemoveButton label={`Remove dependent ${index + 1}`} onClick={() => remove(index)} />
            </div>
          </div>
        </div>
      ))}
      <button type="button" className={ghostButton} onClick={() => append({ name: "", relationship: "", date_of_birth: "" })}>
        <Plus size={12} /> Add dependent
      </button>
    </div>
  );
}

// ── Background tab: skills, languages, certifications ───────────────────────
export function SkillsSection() {
  const { register, control } = useFormContext<ProfileFormValues>();
  const skills = useFieldArray({ control, name: "skills" });
  const langs = useFieldArray({ control, name: "languages" });
  const certs = useFieldArray({ control, name: "certifications" });

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <SectionHeader icon={Wrench} title="Skills" />
        {skills.fields.map((field, index) => (
          <div key={field.id} data-testid={`skill-${index}`} className="flex items-end gap-3">
            <div className="flex-1">
              <Label>Skill</Label>
              <Input aria-label={`Skill ${index + 1} name`} placeholder="e.g. React, Accounting" {...register(`skills.${index}.name`)} />
            </div>
            <div className="w-44">
              <Label>Level</Label>
              <Select aria-label={`Skill ${index + 1} level`} {...register(`skills.${index}.level`)}>
                <option value="">Select</option>
                <option value="beginner">Beginner</option>
                <option value="intermediate">Intermediate</option>
                <option value="expert">Expert</option>
              </Select>
            </div>
            <RemoveButton label={`Remove skill ${index + 1}`} onClick={() => skills.remove(index)} />
          </div>
        ))}
        <button type="button" className={ghostButton} onClick={() => skills.append({ name: "", level: "" })}>
          <Plus size={12} /> Add skill
        </button>
      </div>

      <div className="space-y-3">
        <SectionHeader icon={Languages} title="Languages" />
        {langs.fields.map((field, index) => (
          <div key={field.id} data-testid={`language-${index}`} className="flex items-end gap-3">
            <div className="flex-1">
              <Label>Language</Label>
              <Input aria-label={`Language ${index + 1} name`} placeholder="e.g. Urdu, English" {...register(`languages.${index}.name`)} />
            </div>
            <div className="w-44">
              <Label>Fluency</Label>
              <Select aria-label={`Language ${index + 1} fluency`} {...register(`languages.${index}.fluency`)}>
                <option value="">Select</option>
                <option value="basic">Basic</option>
                <option value="conversational">Conversational</option>
                <option value="fluent">Fluent</option>
                <option value="native">Native</option>
              </Select>
            </div>
            <RemoveButton label={`Remove language ${index + 1}`} onClick={() => langs.remove(index)} />
          </div>
        ))}
        <button type="button" className={ghostButton} onClick={() => langs.append({ name: "", fluency: "" })}>
          <Plus size={12} /> Add language
        </button>
      </div>

      <div className="space-y-3">
        <SectionHeader icon={Award} title="Certifications & Licences" />
        {certs.fields.map((field, index) => (
          <div key={field.id} data-testid={`certification-${index}`} className="rounded-lg border border-[hsl(var(--border))] p-3">
            <div className="grid grid-cols-12 items-end gap-3">
              <div className="col-span-4">
                <Label>Certification</Label>
                <Input aria-label={`Certification ${index + 1} name`} {...register(`certifications.${index}.name`)} />
              </div>
              <div className="col-span-3">
                <Label>Issued by</Label>
                <Input aria-label={`Certification ${index + 1} issued by`} {...register(`certifications.${index}.issued_by`)} />
              </div>
              <div className="col-span-2">
                <Label>Issued</Label>
                <Input type="date" aria-label={`Certification ${index + 1} issued`} {...register(`certifications.${index}.issued_date`)} />
              </div>
              <div className="col-span-2">
                <Label>Expires</Label>
                <Input type="date" aria-label={`Certification ${index + 1} expires`} {...register(`certifications.${index}.expiry_date`)} />
              </div>
              <div className="col-span-1 flex justify-end">
                <RemoveButton label={`Remove certification ${index + 1}`} onClick={() => certs.remove(index)} />
              </div>
            </div>
          </div>
        ))}
        <button type="button" className={ghostButton} onClick={() => certs.append({ name: "", issued_by: "", issued_date: "", expiry_date: "" })}>
          <Plus size={12} /> Add certification
        </button>
      </div>
    </div>
  );
}

// ── Profile photo ───────────────────────────────────────────────────────────
export const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
export const PHOTO_TYPES = ["image/png", "image/jpeg", "image/webp"];

/** Why a chosen file can't be used as a photo, or null if it is fine. */
export function photoProblem(file: File): string | null {
  if (!PHOTO_TYPES.includes(file.type)) return "Photo must be a PNG, JPEG or WebP image.";
  if (file.size > MAX_PHOTO_BYTES) return "Photo must be smaller than 5 MB.";
  return null;
}

export function ProfilePhotoField({
  name,
  currentUrl,
  file,
  removed,
  onPick,
  onRemove,
  onError,
}: {
  name: string;
  currentUrl?: string | null;
  file: File | null;
  removed: boolean;
  onPick: (file: File) => void;
  onRemove: () => void;
  onError: (message: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);

  // A local preview of the picked file; released when it changes or goes away.
  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const shown = preview ?? (removed ? null : resolveMediaUrl(currentUrl));
  const initials = name.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "?";

  return (
    <div className="flex items-center gap-4" data-testid="photo-field">
      <div className="relative flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-full bg-[hsl(var(--accent))] text-xl font-semibold text-[hsl(var(--accent-foreground))]">
        {shown ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={shown} alt="Profile photo" className="h-full w-full object-cover" />
        ) : (
          initials
        )}
      </div>
      <div className="space-y-1.5">
        <div className="flex gap-2">
          <button type="button" className={ghostButton} onClick={() => inputRef.current?.click()}>
            <Camera size={13} /> {shown ? "Change photo" : "Upload photo"}
          </button>
          {shown && (
            <button type="button" className={ghostButton} onClick={onRemove}>
              <Trash2 size={13} /> Remove
            </button>
          )}
        </div>
        <p className="text-xs text-[hsl(var(--foreground-muted))]">PNG, JPEG or WebP, up to 5 MB.</p>
        <input
          ref={inputRef}
          type="file"
          accept={PHOTO_TYPES.join(",")}
          aria-label="Profile photo file"
          className="hidden"
          onChange={(e) => {
            const picked = e.target.files?.[0];
            e.target.value = "";
            if (!picked) return;
            const problem = photoProblem(picked);
            if (problem) onError(problem);
            else onPick(picked);
          }}
        />
      </div>
    </div>
  );
}
