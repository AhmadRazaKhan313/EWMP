"use client";
import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button, Card, CardHeader, PageHeader, Skeleton } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { useRoles } from "@/services/roles.service";
import {
  useConvertOffer, useDecideOffer, useOffer, useRevokeOffer, useSendOffer, useSubmitOffer, useTemplates,
} from "@/services/onboarding.service";
import { Field, Modal, OfferStatusBadge, fmtDate, inputCls } from "@/components/onboarding/ui";

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-2 text-sm">
      <dt className="text-[hsl(var(--foreground-muted))]">{k}</dt>
      <dd className="text-right font-medium">{v ?? "—"}</dd>
    </div>
  );
}

export default function OfferDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const has = useAuthStore((s) => s.hasPermission);
  const { data: offer, isLoading } = useOffer(id);
  const submit = useSubmitOffer(id);
  const decide = useDecideOffer(id);
  const send = useSendOffer(id);
  const revoke = useRevokeOffer(id);
  const convert = useConvertOffer(id);
  const { data: roles } = useRoles();
  const { data: templates } = useTemplates("onboarding");
  const [link, setLink] = useState<string | null>(null);
  const [showConvert, setShowConvert] = useState(false);
  const [roleId, setRoleId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [created, setCreated] = useState<{ employee_code: string; temporary_password: string | null } | null>(null);

  if (isLoading || !offer) return <Skeleton className="h-64 w-full" />;
  const s = offer.status;
  const canManage = has("offers.manage");
  const canApprove = has("offers.approve");

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader title={offer.candidate_name} description={`${offer.job_title} · version ${offer.version}`}
        action={<OfferStatusBadge status={s} />} />

      <div className="flex flex-wrap gap-3">
        {canManage && s === "draft" && (
          <Button disabled={submit.isPending} onClick={() => submit.mutate()}>Submit for approval</Button>)}
        {canApprove && s === "pending_approval" && (<>
          <Button disabled={decide.isPending} onClick={() => decide.mutate({ decision: "approved" })}>Approve</Button>
          <Button variant="destructive" disabled={decide.isPending} onClick={() => decide.mutate({ decision: "rejected" })}>Reject</Button></>)}
        {canManage && ["approved", "sent", "viewed", "expired"].includes(s) && (
          <Button disabled={send.isPending}
            onClick={() => send.mutate({}, { onSuccess: (o) => setLink(o.link ?? null) })}>
            {s === "approved" ? "Send to candidate" : "Send a new link"}</Button>)}
        {canManage && ["approved", "sent", "viewed"].includes(s) && (
          <Button variant="secondary" disabled={revoke.isPending} onClick={() => revoke.mutate()}>Withdraw offer</Button>)}
        {canManage && s === "accepted" && !offer.employee_id && (
          <Button onClick={() => setShowConvert(true)}>Create employee</Button>)}
        {offer.employee_id && (
          <Button variant="secondary" onClick={() => router.push(`/employees/${offer.employee_id}`)}>Open employee</Button>)}
      </div>

      {link && (
        <Card>
          <p className="text-sm font-medium">Candidate link (shown only now — copy it if the email does not arrive)</p>
          <input readOnly className={`${inputCls} mt-2 font-mono`} value={link} onFocus={(e) => e.currentTarget.select()} />
        </Card>)}

      <Card padding={false}>
        <CardHeader title="Offer details" />
        <dl className="divide-y divide-[hsl(var(--border))] px-6">
          <Row k="Email" v={offer.candidate_email} />
          <Row k="Joining date" v={fmtDate(offer.joining_date)} />
          <Row k="Monthly salary" v={offer.salary != null ? `${offer.currency} ${Number(offer.salary).toLocaleString()}` : null} />
          <Row k="Probation" v={offer.probation_months != null ? `${offer.probation_months} months` : null} />
          <Row k="Sent" v={fmtDate(offer.sent_at)} />
          <Row k="Viewed" v={fmtDate(offer.viewed_at)} />
          <Row k="Expires" v={fmtDate(offer.expires_at)} />
          {offer.accepted_name && <Row k="Signed by" v={offer.accepted_name} />}
          {offer.decline_reason && <Row k="Decline reason" v={offer.decline_reason} />}
        </dl>
      </Card>

      {offer.approvals.length > 0 && (
        <Card padding={false}>
          <CardHeader title="Approvals" />
          <ul className="divide-y divide-[hsl(var(--border))] px-6 text-sm">
            {offer.approvals.map((a, i) => (
              <li key={i} className="py-2">{a.decision === "approved" ? "Approved" : "Rejected"} · {fmtDate(a.at)}{a.note ? ` — ${a.note}` : ""}</li>))}
          </ul>
        </Card>)}

      {showConvert && (
        <Modal title="Create employee from this offer" onClose={() => setShowConvert(false)}>
          {created ? (
            <div className="space-y-3 text-sm">
              <p>Employee <b>{created.employee_code}</b> created and the onboarding checklist has started.</p>
              {created.temporary_password && (<p>Temporary password (shown once): <code className="font-mono">{created.temporary_password}</code></p>)}
              <Button onClick={() => router.push("/onboarding/cases")}>Go to checklists</Button>
            </div>
          ) : (
            <div className="space-y-4">
              <Field label="Role" hint="Decides what the new hire can do after they log in.">
                <select className={inputCls} value={roleId} onChange={(e) => setRoleId(e.target.value)}>
                  <option value="">Select a role…</option>
                  {roles?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select></Field>
              <Field label="Checklist template" hint="Leave empty to use the default.">
                <select className={inputCls} value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                  <option value="">Default</option>
                  {templates?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select></Field>
              <Button disabled={!roleId || convert.isPending}
                onClick={() => convert.mutate({ role_id: roleId, template_id: templateId || undefined },
                  { onSuccess: (r) => setCreated(r) })}>
                {convert.isPending ? "Creating…" : "Create employee"}</Button>
            </div>)}
        </Modal>)}
    </div>
  );
}
