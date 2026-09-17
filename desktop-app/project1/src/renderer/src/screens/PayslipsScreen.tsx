import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Loader2, Wallet } from "lucide-react";
import { getMyPayslips, downloadPayslipPdf } from "../services/payslipsService";
import type { MyPayslipItem, PayslipStatus } from "../types/hrms";
import { formatDate, formatMoney } from "../lib/format";
import { Badge, Button, Card, EmptyState, ErrorState, SkeletonList, cn } from "../components/ui";

/**
 * Employee self-service payslip history — GET /payroll/payslips/me, the
 * same endpoint the web app's MyPayslipsView uses. No run management, no
 * admin table: just my own payslips and a PDF download, which is exactly
 * what a plain employee (no payroll.* permissions) is allowed to see.
 *
 * Restyled onto the shared Card/Badge primitives. NET is the figure
 * people open this screen for, so it is the only number given weight;
 * gross and deductions sit beside it as context rather than competing.
 * The most recent payslip is emphasised in place rather than lifted into
 * a separate hero card — one list, one download button per row, nothing
 * rendered twice.
 *
 * Badge text is the RAW status string from the backend ("paid",
 * "generated"), capitalised in CSS only. Substituting a display label
 * here would change textContent and break anything reading the real
 * status, tests included.
 */

const STATUS_VARIANT: Record<PayslipStatus, "default" | "info" | "success" | "error"> = {
  draft: "default",
  generated: "info",
  sent: "info",
  paid: "success",
  reversed: "error",
};

export default function PayslipsScreen(): JSX.Element {
  const payslipsQuery = useQuery({ queryKey: ["payroll", "payslips", "me"], queryFn: getMyPayslips });
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  async function handleDownload(payslip: MyPayslipItem): Promise<void> {
    setDownloadError(null);
    setDownloadingId(payslip.id);
    try {
      const blob = await downloadPayslipPdf(payslip.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `payslip-${payslip.run.pay_date}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      setDownloadError("Could not download this payslip. It may still be generating — try again in a minute.");
    } finally {
      setDownloadingId(null);
    }
  }

  const items = payslipsQuery.data ?? [];

  return (
    <div className="flex w-full flex-col gap-[18px] p-6">
      <header>
        <h1 className="font-heading text-[22px] font-semibold tracking-tight text-[hsl(var(--foreground))]">
          Payslips
        </h1>
        <p className="mt-0.5 text-xs text-[hsl(var(--foreground-muted))]">
          Your salary history and PDF downloads
        </p>
      </header>

      {downloadError && <ErrorState message={downloadError} />}

      {payslipsQuery.isLoading ? (
        <SkeletonList rows={4} height="h-[92px]" />
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Wallet size={20} />}
            title="No payslips yet"
            body="Your payslips appear here once payroll has been run for a period that includes you."
          />
        </Card>
      ) : (
        <ul data-testid="payslips-list" className="flex flex-col gap-2.5">
          {items.map((p, i) => (
            <li key={p.id}>
              <Card
                testId="payslip-row"
                className={cn(
                  "flex flex-wrap items-center gap-4",
                  // Most recent first (the endpoint orders newest-first) —
                  // outlined rather than recoloured, so emphasis doesn't
                  // cost a second colour in the palette.
                  i === 0 && "outline outline-2 -outline-offset-2 outline-[hsl(var(--primary))]",
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-[hsl(var(--foreground))]">{p.run.name}</span>
                    <Badge variant={STATUS_VARIANT[p.status]} className="capitalize">
                      {p.status}
                    </Badge>
                    {i === 0 && <Badge variant="info">Most recent</Badge>}
                  </div>
                  <p className="num mt-1 text-xs text-[hsl(var(--foreground-muted))]">
                    {formatDate(p.run.period_start)} – {formatDate(p.run.period_end)} · paid{" "}
                    {formatDate(p.run.pay_date)}
                  </p>
                </div>

                <div className="text-right">
                  <p className="num font-heading text-xl font-semibold tracking-tight text-[hsl(var(--foreground))]">
                    {formatMoney(p.net_salary, p.run.currency)}
                  </p>
                  <p className="num mt-0.5 text-[11px] text-[hsl(var(--foreground-muted))]">
                    <span>{formatMoney(p.gross_salary, p.run.currency)}</span> gross ·{" "}
                    <span>{formatMoney(p.total_deductions, p.run.currency)}</span> deducted
                  </p>
                </div>

                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void handleDownload(p)}
                  disabled={downloadingId === p.id}
                  data-testid="payslip-download-button"
                  aria-label={`Download payslip for ${p.run.name}`}
                >
                  {downloadingId === p.id ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                  PDF
                </Button>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
