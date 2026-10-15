"use client";

import { Pencil } from "lucide-react";
import { DOCUMENT_TYPE_LABELS, type DocumentType } from "@/services/employeeDocuments.service";
import type { WizardOptions } from "./Steps";
import {
  EMPLOYMENT_TYPE_OPTIONS, GENDER_OPTIONS, JOB_NATURE_OPTIONS, RELATIONSHIP_OPTIONS, STEPS, labelOf,
  type EmployeeWizardValues, type StagedDoc, type StepId,
} from "./wizard";

function Row({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 py-2 sm:grid-cols-[180px_1fr] sm:gap-4">
      <dt className="text-sm text-[hsl(var(--foreground-muted))]">{label}</dt>
      <dd className={value ? "break-words text-sm font-medium" : "text-sm text-[hsl(var(--foreground-muted))]"}>{value || "Not provided"}</dd>
    </div>
  );
}

function Section({ step, onEdit, children }: { step: StepId; onEdit: (i: number) => void; children: React.ReactNode }) {
  const index = STEPS.findIndex((s) => s.id === step);
  const meta = STEPS[index]!;
  return (
    <section className="rounded-xl border border-[hsl(var(--border))]" aria-labelledby={`rv-${step}`}>
      <header className="flex items-center justify-between border-b border-[hsl(var(--border))] px-4 py-3">
        <h3 id={`rv-${step}`} className="text-sm font-semibold">{meta.check}</h3>
        <button type="button" onClick={() => onEdit(index)} aria-label={`Edit ${meta.check}`}
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-[hsl(var(--brand-700))] hover:bg-[hsl(var(--accent))] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[hsl(var(--brand-100))]">
          <Pencil size={12} aria-hidden /> Edit
        </button>
      </header>
      <dl className="divide-y divide-[hsl(var(--border))] px-4">{children}</dl>
    </section>
  );
}

export function ReviewStep({
  values, docs, options, onEdit, createdNotice,
}: {
  values: EmployeeWizardValues;
  docs: StagedDoc[];
  options: WizardOptions;
  onEdit: (stepIndex: number) => void;
  createdNotice?: React.ReactNode;
}) {
  const v = values;
  const name = (list: { id: string; label: string }[], id: string) => list.find((o) => o.id === id)?.label ?? "";
  const salary = v.current_salary ? `${v.currency} ${Number(v.current_salary).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "";

  return (
    <div className="space-y-4">
      {createdNotice}
      <Section step="personal" onEdit={onEdit}>
        <Row label="Full name" value={`${v.first_name} ${v.last_name}`.trim()} />
        <Row label="Work email" value={v.email} />
        <Row label="Phone" value={v.phone} />
        <Row label="Date of birth" value={v.date_of_birth} />
        <Row label="Gender" value={labelOf(GENDER_OPTIONS, v.gender)} />
        <Row label="Nationality" value={v.nationality} />
        <Row label="Blood group" value={v.blood_group} />
      </Section>

      <Section step="role" onEdit={onEdit}>
        <Row label="Role" value={name(options.roles.options, v.role_id)} />
        <Row label="Employment status" value={labelOf(JOB_NATURE_OPTIONS, v.job_nature)} />
        <Row label="Date of joining" value={v.date_of_joining} />
        <Row label="Employment type" value={labelOf(EMPLOYMENT_TYPE_OPTIONS, v.employment_type)} />
        <Row label="Department" value={name(options.departments.options, v.department_id)} />
        <Row label="Designation" value={name(options.designations.options, v.designation_id)} />
        <Row label="Branch" value={name(options.branches.options, v.branch_id)} />
        <Row label="Work location" value={v.work_location} />
        <Row label="Shift" value={name(options.shifts.options, v.default_shift_id) || "No shift (organisation work week)"} />
        <Row label="Remote" value={v.is_remote ? "Yes" : "No"} />
      </Section>

      <Section step="pay" onEdit={onEdit}>
        <Row label="Basic salary" value={salary} />
        <Row label="Currency" value={v.currency} />
      </Section>

      <Section step="emergency" onEdit={onEdit}>
        <Row label="Contact name" value={v.emergency_name} />
        <Row label="Phone" value={v.emergency_phone} />
        <Row label="Relationship" value={labelOf(RELATIONSHIP_OPTIONS, v.emergency_relationship)} />
      </Section>

      <Section step="documents" onEdit={onEdit}>
        {docs.length === 0 ? (
          <Row label="Documents" value="" />
        ) : (
          docs.map((d) => (
            <Row key={d.id} label={DOCUMENT_TYPE_LABELS[d.document_type as DocumentType] ?? d.document_type} value={`${d.title} (${d.file.name})`} />
          ))
        )}
      </Section>

      <p className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-4 text-sm text-[hsl(var(--foreground-muted))]">
        Creating the employee also creates their login. A temporary password is shown right after creation, and they will be asked to change it when they first sign in.
      </p>
    </div>
  );
}
