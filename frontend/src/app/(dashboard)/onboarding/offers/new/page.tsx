"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, PageHeader } from "@/components/atoms";
import { useCreateOffer, useDepartmentOptions, useDesignationOptions, type OfferInput } from "@/services/onboarding.service";
import { Field, inputCls } from "@/components/onboarding/ui";

export default function NewOfferPage() {
  const router = useRouter();
  const create = useCreateOffer();
  const { data: departments } = useDepartmentOptions();
  const { data: designations } = useDesignationOptions();
  const [f, setF] = useState({
    candidate_name: "", candidate_email: "", candidate_phone: "", job_title: "", department_id: "", designation_id: "",
    employment_type: "full_time", salary: "", currency: "PKR", joining_date: "", probation_months: "3",
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const valid = f.candidate_name.trim().length >= 2 && /\S+@\S+\.\S+/.test(f.candidate_email) && f.job_title.trim() && f.joining_date;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    const body: OfferInput = {
      candidate_name: f.candidate_name.trim(), candidate_email: f.candidate_email.trim(),
      candidate_phone: f.candidate_phone || null, job_title: f.job_title.trim(),
      department_id: f.department_id || null, designation_id: f.designation_id || null,
      employment_type: f.employment_type, salary: f.salary ? Number(f.salary) : null, currency: f.currency,
      joining_date: f.joining_date, probation_months: f.probation_months ? Number(f.probation_months) : null,
    };
    create.mutate(body, { onSuccess: (o) => router.push(`/onboarding/offers/${o.id}`) });
  };

  return (
    <form onSubmit={submit} className="max-w-3xl space-y-6">
      <PageHeader title="New offer" description="Saved as a draft first — you can review, get it approved and then send it." />
      <Card>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Candidate name"><input className={inputCls} value={f.candidate_name} onChange={set("candidate_name")} required /></Field>
          <Field label="Candidate email"><input type="email" className={inputCls} value={f.candidate_email} onChange={set("candidate_email")} required /></Field>
          <Field label="Phone"><input className={inputCls} value={f.candidate_phone} onChange={set("candidate_phone")} /></Field>
          <Field label="Job title"><input className={inputCls} value={f.job_title} onChange={set("job_title")} required /></Field>
          <Field label="Department">
            <select className={inputCls} value={f.department_id} onChange={set("department_id")}>
              <option value="">—</option>{departments?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select></Field>
          <Field label="Designation">
            <select className={inputCls} value={f.designation_id} onChange={set("designation_id")}>
              <option value="">—</option>{designations?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select></Field>
          <Field label="Employment type">
            <select className={inputCls} value={f.employment_type} onChange={set("employment_type")}>
              <option value="full_time">Full time</option><option value="part_time">Part time</option>
              <option value="contract">Contract</option><option value="intern">Intern</option>
            </select></Field>
          <Field label="Joining date"><input type="date" className={inputCls} value={f.joining_date} onChange={set("joining_date")} required /></Field>
          <Field label="Monthly salary"><input type="number" min="0" className={inputCls} value={f.salary} onChange={set("salary")} /></Field>
          <Field label="Currency"><input className={inputCls} value={f.currency} onChange={set("currency")} maxLength={3} /></Field>
          <Field label="Probation (months)"><input type="number" min="0" max="12" className={inputCls} value={f.probation_months} onChange={set("probation_months")} /></Field>
        </div>
      </Card>
      <div className="flex gap-3">
        <Button type="submit" disabled={!valid || create.isPending}>{create.isPending ? "Saving…" : "Save draft"}</Button>
        <Button variant="secondary" onClick={() => router.push("/onboarding/offers")}>Cancel</Button>
      </div>
    </form>
  );
}
