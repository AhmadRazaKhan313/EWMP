"use client";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Skeleton } from "@/components/atoms";
import { apiErrorMessage, preboardingApi, type EmergencyContact } from "@/services/onboarding.service";
import { Field, fmtDate, inputCls } from "@/components/onboarding/ui";

type Form = Record<string, string>;
const TEXT_FIELDS: { key: string; label: string; required?: boolean; type?: string }[] = [
  { key: "personal_phone", label: "Mobile number", required: true },
  { key: "personal_email", label: "Personal email", type: "email" },
  { key: "address", label: "Current address", required: true },
  { key: "permanent_address", label: "Permanent address" },
  { key: "national_id", label: "National ID (CNIC) number", required: true },
  { key: "date_of_birth", label: "Date of birth", type: "date" },
  { key: "nationality", label: "Nationality" },
  { key: "blood_group", label: "Blood group" },
  { key: "bank_name", label: "Bank name" },
  { key: "bank_account_title", label: "Account title" },
  { key: "bank_account_number", label: "Account number" },
  { key: "bank_iban", label: "IBAN" },
];

export default function PreboardingPage() {
  const { token } = useParams<{ token: string }>();
  const qc = useQueryClient();
  const { data, isLoading, isError } = useQuery({ queryKey: ["preboarding", token], queryFn: () => preboardingApi.get(token), retry: false });
  const [form, setForm] = useState<Form>({});
  const [gender, setGender] = useState("");
  const [contacts, setContacts] = useState<EmergencyContact[]>([{ name: "", phone: "" }]);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const loaded = useRef(false);

  useEffect(() => {
    if (!data || loaded.current) return;
    loaded.current = true;
    const f: Form = {};
    for (const [k, v] of Object.entries(data.form)) if (typeof v === "string") f[k] = v;
    setForm(f); setGender(f.gender ?? "");
    if (data.form.emergency_contacts?.length) setContacts(data.form.emergency_contacts);
    setAck(data.policy_acknowledged);
  }, [data]);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg(null);
    try { await fn(); await qc.invalidateQueries({ queryKey: ["preboarding", token] }); setMsg({ ok: true, text: ok }); }
    catch (e) { setMsg({ ok: false, text: apiErrorMessage(e, "Something went wrong. Please try again.") }); }
    finally { setBusy(false); }
  };

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (isError || !data) return <Card><p className="text-center text-sm">This link is not valid or has expired. Please contact HR for a new one.</p></Card>;

  const body = () => ({
    ...form, gender: gender || undefined,
    emergency_contacts: contacts.filter((c) => c.name.trim() && c.phone.trim()),
  });
  const missing = TEXT_FIELDS.filter((f) => f.required && !form[f.key]?.trim());
  const save = (submit: boolean) =>
    run(() => preboardingApi.save(token, { form: body(), submit, acknowledge_policy: ack }),
      submit ? "Submitted. Thank you!" : "Saved. You can come back to this link later.");

  return (
    <div className="space-y-6">
      <div className="text-center">
        <p className="text-sm text-[hsl(var(--foreground-muted))]">{data.company_name}</p>
        <h1 className="font-heading text-2xl font-semibold">Welcome{data.first_name ? `, ${data.first_name}` : ""}!</h1>
        <p className="mt-1 text-sm text-[hsl(var(--foreground-muted))]">Please complete your details before your first day on {fmtDate(data.joining_date)}.</p>
        {data.submitted && <div className="mt-3"><Badge variant="success">Submitted — you can still update it</Badge></div>}
      </div>

      <Card>
        <h2 className="mb-4 font-heading text-base font-semibold">Your details</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {TEXT_FIELDS.map((f) => (
            <Field key={f.key} label={f.label + (f.required ? " *" : "")}>
              <input type={f.type ?? "text"} className={inputCls} value={form[f.key] ?? ""}
                     onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} /></Field>))}
          <Field label="Gender">
            <select className={inputCls} value={gender} onChange={(e) => setGender(e.target.value)}>
              <option value="">—</option><option value="male">Male</option><option value="female">Female</option>
              <option value="non_binary">Non-binary</option><option value="prefer_not_to_say">Prefer not to say</option></select></Field>
        </div>
      </Card>

      <Card>
        <h2 className="mb-4 font-heading text-base font-semibold">Emergency contacts</h2>
        <div className="space-y-3">
          {contacts.map((c, i) => (
            <div key={i} className="grid gap-3 sm:grid-cols-3">
              <input className={inputCls} placeholder="Name" aria-label={`Contact ${i + 1} name`} value={c.name}
                     onChange={(e) => setContacts(contacts.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <input className={inputCls} placeholder="Phone" aria-label={`Contact ${i + 1} phone`} value={c.phone}
                     onChange={(e) => setContacts(contacts.map((x, j) => (j === i ? { ...x, phone: e.target.value } : x)))} />
              <input className={inputCls} placeholder="Relationship" aria-label={`Contact ${i + 1} relationship`} value={c.relationship ?? ""}
                     onChange={(e) => setContacts(contacts.map((x, j) => (j === i ? { ...x, relationship: e.target.value } : x)))} />
            </div>))}
          {contacts.length < 5 && <Button variant="secondary" size="sm" onClick={() => setContacts([...contacts, { name: "", phone: "" }])}>Add another</Button>}
        </div>
      </Card>

      {data.documents.length > 0 && (
        <Card>
          <h2 className="mb-4 font-heading text-base font-semibold">Documents</h2>
          <ul className="space-y-3">
            {data.documents.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 text-sm">
                <div>
                  <span className="font-medium">{d.title}{d.is_required && " *"}</span>
                  {d.status === "rejected" && d.rejection_reason && <p className="text-xs text-[hsl(var(--destructive))]">Rejected: {d.rejection_reason}</p>}
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={d.status === "verified" ? "success" : d.status === "rejected" ? "error" : "default"}>{d.status}</Badge>
                  {d.status !== "verified" && (
                    <input type="file" aria-label={`Upload ${d.title}`} accept=".pdf,.png,.jpg,.jpeg" disabled={busy}
                           className="max-w-48 text-xs"
                           onChange={(e) => { const file = e.target.files?.[0]; if (file) void run(() => preboardingApi.upload(token, d.id, file), `${d.title} uploaded.`); e.target.value = ""; }} />)}
                </div>
              </li>))}
          </ul>
        </Card>)}

      <Card>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-0.5" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          I have read the company policies and agree to follow them.
        </label>
      </Card>

      {msg && <p role={msg.ok ? "status" : "alert"} className={msg.ok ? "text-sm text-[hsl(var(--success))]" : "text-sm text-[hsl(var(--destructive))]"}>{msg.text}</p>}
      {missing.length > 0 && <p className="text-xs text-[hsl(var(--foreground-muted))]">To submit, please fill in: {missing.map((m) => m.label).join(", ")}.</p>}
      <div className="flex gap-3">
        <Button variant="secondary" disabled={busy} onClick={() => save(false)}>Save for later</Button>
        <Button disabled={busy || missing.length > 0 || !ack} onClick={() => save(true)}>Submit</Button>
      </div>
    </div>
  );
}
