"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Download, Upload } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge, Button, Card, PageHeader } from "@/components/atoms";
import { apiErrorMessage } from "@/services/payroll.service";
import { downloadCsv, importEmployees, type ImportResult } from "@/services/employeeLifecycle.service";

/** Escape a cell for the credentials file (and neutralise spreadsheet formulas). */
function cell(v: string): string {
  const safe = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v;
  return `"${safe.replace(/"/g, '""')}"`;
}

function downloadCredentials(rows: ImportResult["rows"]) {
  const lines = ["email,employee_code,temporary_password"].concat(
    rows.filter((r) => r.ok && r.temporary_password).map((r) => [r.email, r.employee_code ?? "", r.temporary_password ?? ""].map(cell).join(",")),
  );
  const url = window.URL.createObjectURL(new Blob([lines.join("\r\n")], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "new-employee-logins.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

/** Bulk import: pick a CSV, preview (dry run) the result row by row, then import for real. */
export default function ImportEmployeesPage() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(dryRun: boolean) {
    if (!file) return;
    setBusy(true);
    try {
      const r = await importEmployees(file, dryRun);
      setResult(r);
      if (!dryRun) {
        qc.invalidateQueries({ queryKey: ["employees"] });
        toast.success(`${r.created} employee(s) created${r.failed ? `, ${r.failed} skipped` : ""}`);
      }
    } catch (err) {
      toast.error(apiErrorMessage(err, "Could not read that file"));
    } finally {
      setBusy(false);
    }
  }

  const imported = !!result && !result.dry_run;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Import employees"
        description="Add many employees at once from a CSV file."
        action={<Link href="/employees"><Button variant="outline" icon={<ArrowLeft size={14} />}>Employees</Button></Link>}
      />

      <Card>
        <ol className="list-decimal space-y-2 pl-5 text-sm">
          <li>
            <button className="text-[hsl(var(--primary))] underline" onClick={() => downloadCsv("/employees/import/template", "employee-import-template.csv")}>
              Download the template
            </button>{" "}
            and fill one row per person. Role is required and must match a role name in your organisation.
          </li>
          <li>Choose the file and press <b>Check file</b>. Nothing is created yet; each row shows OK or what is wrong.</li>
          <li>Press <b>Import</b> to create the valid rows. Rows with errors are skipped; fix them and import again.</li>
        </ol>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            aria-label="CSV file"
            className="hidden"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); }}
          />
          <Button variant="outline" icon={<Upload size={14} />} onClick={() => input.current?.click()}>
            {file ? file.name : "Choose CSV"}
          </Button>
          <Button disabled={!file || busy || imported} onClick={() => run(true)}>Check file</Button>
          <Button disabled={!file || busy || !result?.dry_run || result.created === 0} onClick={() => run(false)}>
            Import {result?.dry_run ? `${result.created} valid row(s)` : ""}
          </Button>
        </div>
      </Card>

      {result && (
        <Card padding={false}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[hsl(var(--border))] px-5 py-3">
            <p className="text-sm font-medium" data-testid="import-summary">
              {result.dry_run ? "Check result" : "Import finished"}: {result.created} {result.dry_run ? "ready" : "created"}, {result.failed} with errors, {result.total} rows
            </p>
            {imported && result.rows.some((r) => r.temporary_password) && (
              <Button size="sm" variant="outline" icon={<Download size={13} />} onClick={() => downloadCredentials(result.rows)}>
                Download login passwords
              </Button>
            )}
          </div>
          {imported && result.rows.some((r) => r.temporary_password) && (
            <p className="border-b border-[hsl(var(--border))] bg-[hsl(var(--warning-subtle))] px-5 py-2 text-xs">
              Temporary passwords are shown only now. Download them and share them securely; each person must change theirs at first login.
            </p>
          )}
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[hsl(var(--border))] text-left text-xs text-[hsl(var(--foreground-muted))]">
                <th className="px-5 py-2 font-medium">Row</th>
                <th className="px-3 py-2 font-medium">Email</th>
                <th className="px-3 py-2 font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {result.rows.map((r) => (
                <tr key={r.row} className="border-b border-[hsl(var(--border))] last:border-0">
                  <td className="px-5 py-2">{r.row}</td>
                  <td className="px-3 py-2">{r.email}</td>
                  <td className="px-3 py-2">
                    {r.ok ? <Badge variant="success">{result.dry_run ? "OK" : r.employee_code}</Badge> : <span className="text-[hsl(var(--destructive))]">{r.error}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
