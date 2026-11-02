"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Skeleton } from "@/components/atoms";
import { apiErrorMessage, publicOfferApi } from "@/services/onboarding.service";
import { fmtDate, inputCls } from "@/components/onboarding/ui";

const MESSAGES: Record<string, string> = {
  accepted: "Thank you — you have accepted this offer. We will be in touch with the next steps.",
  declined: "You have declined this offer. Thank you for letting us know.",
  expired: "This offer has expired. Please contact the company if you are still interested.",
  revoked: "This offer is no longer available.",
  revised: "A newer version of this offer has been issued. Please use the latest link you received.",
};

export default function PublicOfferPage() {
  const { token } = useParams<{ token: string }>();
  const qc = useQueryClient();
  const { data: offer, isLoading, isError } = useQuery({
    queryKey: ["public-offer", token], queryFn: () => publicOfferApi.get(token), retry: false,
  });
  const [name, setName] = useState("");
  const [agree, setAgree] = useState(false);
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); await qc.invalidateQueries({ queryKey: ["public-offer", token] }); }
    catch (e) { setError(apiErrorMessage(e, "Something went wrong. Please try again.")); }
    finally { setBusy(false); }
  };

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (isError || !offer) return <Card><p className="text-center text-sm">This link is not valid. Please check the link in your email.</p></Card>;

  return (
    <div className="space-y-6">
      <div className="text-center">
        <p className="text-sm text-[hsl(var(--foreground-muted))]">{offer.company_name}</p>
        <h1 className="font-heading text-2xl font-semibold">Offer of employment</h1>
      </div>
      <Card>
        <p className="text-sm">Dear {offer.candidate_name},</p>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-[hsl(var(--foreground-muted))]">Position</dt><dd className="font-medium">{offer.job_title}</dd></div>
          <div><dt className="text-[hsl(var(--foreground-muted))]">Joining date</dt><dd className="font-medium">{fmtDate(offer.joining_date)}</dd></div>
          {offer.salary != null && (
            <div><dt className="text-[hsl(var(--foreground-muted))]">Monthly salary</dt>
              <dd className="font-medium">{offer.currency} {Number(offer.salary).toLocaleString()}</dd></div>)}
          {offer.expires_at && <div><dt className="text-[hsl(var(--foreground-muted))]">Valid until</dt><dd className="font-medium">{fmtDate(offer.expires_at)}</dd></div>}
        </dl>
        {offer.body && <div className="mt-5 whitespace-pre-wrap border-t border-[hsl(var(--border))] pt-5 text-sm">{offer.body}</div>}
      </Card>

      {!offer.can_respond ? (
        <Card><p className="text-center text-sm">{MESSAGES[offer.status] ?? "This offer can no longer be answered."}</p></Card>
      ) : declining ? (
        <Card>
          <label className="block text-sm font-medium">Reason (optional)
            <textarea className={`${inputCls} mt-1.5 min-h-24`} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
          {error && <p role="alert" className="mt-3 text-sm text-[hsl(var(--destructive))]">{error}</p>}
          <div className="mt-4 flex gap-3">
            <Button variant="destructive" disabled={busy} onClick={() => run(() => publicOfferApi.decline(token, reason))}>Decline offer</Button>
            <Button variant="secondary" onClick={() => setDeclining(false)}>Back</Button>
          </div>
        </Card>
      ) : (
        <Card>
          <h2 className="font-heading text-base font-semibold">Accept this offer</h2>
          <p className="mt-1 text-sm text-[hsl(var(--foreground-muted))]">Type your full name as your electronic signature.</p>
          <input className={`${inputCls} mt-3`} placeholder="Full name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Full name" />
          <label className="mt-3 flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            I have read and accept this offer.
          </label>
          {error && <p role="alert" className="mt-3 text-sm text-[hsl(var(--destructive))]">{error}</p>}
          <div className="mt-4 flex gap-3">
            <Button disabled={busy || name.trim().length < 2 || !agree} onClick={() => run(() => publicOfferApi.accept(token, name.trim(), agree))}>Accept offer</Button>
            <Button variant="secondary" onClick={() => setDeclining(true)}>Decline</Button>
          </div>
        </Card>
      )}
    </div>
  );
}
