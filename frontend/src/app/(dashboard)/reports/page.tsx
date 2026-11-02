"use client";

import { useEffect, useMemo, useState } from "react";
import { BarChart2, Download, FileSpreadsheet, Search } from "lucide-react";
import { Button, Card, EmptyState, PageHeader, Skeleton } from "@/components/atoms";
import { apiErrorText } from "@/utils/api-error";
import {
  currentMonth,
  downloadHubReport,
  useDepartmentOptions,
  useHubReport,
  useReportCatalog,
  type CatalogItem,
  type ReportColumn,
  type ReportRow,
} from "@/services/reports.service";

const INPUT =
  "h-10 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 text-sm " +
  "text-[hsl(var(--foreground))] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[hsl(var(--brand-100))]";

const MONEY = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const INT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function formatCell(value: string | number | null | undefined, type: ReportColumn["type"]): string {
  if (value === null || value === undefined || value === "") return "—";
  if (type === "text") return String(value);
  if (type === "date") {
    const d = new Date(`${String(value).slice(0, 10)}T00:00:00`);
    return Number.isNaN(d.getTime())
      ? String(value)
      : d.toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
  }
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  if (type === "money") return MONEY.format(n);
  if (type === "percent") return `${n}%`;
  if (type === "hours") return n.toFixed(1);
  return INT.format(n);
}

function Tile({ label, value, type }: { label: string; value: string | number | null; type: ReportColumn["type"] }) {
  return (
    <Card className="!p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-[hsl(var(--foreground-muted))]">{label}</p>
      <p className="mt-1 font-heading text-2xl font-semibold tabular-nums">{formatCell(value, type)}</p>
    </Card>
  );
}

function groupByCategory(items: CatalogItem[]): [string, CatalogItem[]][] {
  const map = new Map<string, CatalogItem[]>();
  for (const it of items) map.set(it.category, [...(map.get(it.category) ?? []), it]);
  return [...map.entries()];
}

export default function ReportsPage() {
  const catalog = useReportCatalog();
  const [selected, setSelected] = useState<string | null>(null);
  const [month, setMonth] = useState(currentMonth());
  const [departmentId, setDepartmentId] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<"xlsx" | "csv" | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const items = catalog.data?.items ?? [];
  const groups = useMemo(() => groupByCategory(items), [items]);
  const current = items.find((i) => i.key === selected) ?? null;

  // Open the first report once the list arrives.
  useEffect(() => {
    const first = items[0];
    if (!selected && first) setSelected(first.key);
  }, [items, selected]);

  // Wait for a pause in typing before asking the server again.
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  const filters = { month, departmentId: departmentId || undefined, search: current?.uses_search && search ? search : undefined };
  const report = useHubReport(selected, filters);
  const departments = useDepartmentOptions();

  async function download(format: "xlsx" | "csv") {
    if (!selected) return;
    setBusy(format);
    setDownloadError(null);
    try {
      await downloadHubReport(selected, format, filters);
    } catch (err) {
      setDownloadError(apiErrorText(err, "Could not download the report."));
    } finally {
      setBusy(null);
    }
  }

  const data = report.data;
  const totals = data?.totals ?? null;
  const canExport = catalog.data?.can_export ?? false;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        description="Pick a report, set the month, and download it as an Excel sheet."
        action={
          canExport ? (
            <div className="flex gap-2">
              <Button variant="outline" icon={<FileSpreadsheet size={14} />} onClick={() => void download("xlsx")} disabled={!data || busy !== null}>
                {busy === "xlsx" ? "Preparing…" : "Download Excel"}
              </Button>
              <Button variant="outline" icon={<Download size={14} />} onClick={() => void download("csv")} disabled={!data || busy !== null}>
                {busy === "csv" ? "Preparing…" : "CSV"}
              </Button>
            </div>
          ) : undefined
        }
      />

      {catalog.isError && (
        <Card>
          <p className="text-sm text-[hsl(var(--destructive))]">{apiErrorText(catalog.error, "Could not load the reports.")}</p>
        </Card>
      )}

      {catalog.isLoading && <Skeleton className="h-64 w-full" />}

      {catalog.data && items.length === 0 && (
        <Card>
          <EmptyState icon={BarChart2} title="No reports available" description="You do not have access to any report yet." />
        </Card>
      )}

      {items.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
          <nav aria-label="Reports" className="space-y-5">
            {groups.map(([category, list]) => (
              <div key={category}>
                <p className="mb-1 px-2 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--foreground-muted))]">{category}</p>
                <ul className="space-y-0.5">
                  {list.map((it) => (
                    <li key={it.key}>
                      <button
                        type="button"
                        onClick={() => { setSelected(it.key); setDownloadError(null); }}
                        aria-current={it.key === selected ? "page" : undefined}
                        title={it.description}
                        className={`w-full rounded-md px-2 py-2 text-left text-sm transition-colors ${
                          it.key === selected
                            ? "bg-[hsl(var(--brand-50))] font-medium text-[hsl(var(--brand-700))]"
                            : "text-[hsl(var(--foreground))] hover:bg-[hsl(var(--background-subtle))]"
                        }`}
                      >
                        {it.title}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>

          <section className="min-w-0 space-y-5">
            {current && (
              <div>
                <h2 className="font-heading text-lg font-semibold">{current.title}</h2>
                <p className="text-sm text-[hsl(var(--foreground-muted))]">{current.description}</p>
              </div>
            )}

            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-xs font-medium text-[hsl(var(--foreground-subtle))]">
                Month
                <input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} className={INPUT} aria-label="Month" />
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-[hsl(var(--foreground-subtle))]">
                Department
                <select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} className={INPUT} aria-label="Department">
                  <option value="">All departments</option>
                  {(departments.data ?? []).map((d) => (<option key={d.id} value={d.id}>{d.name}</option>))}
                </select>
              </label>
              {current?.uses_search && (
                <label className="relative flex flex-col gap-1 text-xs font-medium text-[hsl(var(--foreground-subtle))]">
                  Search
                  <Search size={14} className="pointer-events-none absolute bottom-3 left-3 text-[hsl(var(--foreground-muted))]" />
                  <input type="search" value={searchInput} onChange={(e) => setSearchInput(e.target.value)}
                    placeholder="Name or employee code" className={`${INPUT} w-64 pl-9`} aria-label="Search employees" />
                </label>
              )}
            </div>

            {downloadError && <p role="alert" className="text-sm text-[hsl(var(--destructive))]">{downloadError}</p>}

            {report.isError && (
              <Card>
                <p className="text-sm text-[hsl(var(--destructive))]">{apiErrorText(report.error, "Could not load the report.")}</p>
                <div className="mt-3"><Button variant="outline" size="sm" onClick={() => void report.refetch()}>Try again</Button></div>
              </Card>
            )}

            {report.isLoading && (
              <div className="space-y-3"><Skeleton className="h-20 w-full" /><Skeleton className="h-64 w-full" /></div>
            )}

            {data && (
              <>
                {data.subtitle && <p className="text-sm text-[hsl(var(--foreground-muted))]">{data.subtitle}</p>}

                {data.summary.length > 0 && (
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
                    {data.summary.map((t) => (<Tile key={t.label} label={t.label} value={t.value} type={t.type} />))}
                  </div>
                )}

                {data.rows.length === 0 ? (
                  <Card>
                    <EmptyState icon={BarChart2} title="Nothing to show" description="No data matches these filters for this month." />
                  </Card>
                ) : (
                  <Card padding={false} className="overflow-x-auto">
                    <table className="w-full text-sm" style={{ minWidth: Math.max(640, data.columns.length * 110) }}>
                      <thead>
                        <tr className="border-b border-[hsl(var(--border))] text-xs uppercase tracking-wide text-[hsl(var(--foreground-muted))]">
                          {data.columns.map((c) => (
                            <th key={c.key} className={`px-3 py-3 font-medium ${c.type === "text" ? "text-left" : "text-right"}`}>{c.label}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.rows.map((r: ReportRow, i) => (
                          <tr key={i} className="border-b border-[hsl(var(--border))] hover:bg-[hsl(var(--background-subtle))]">
                            {data.columns.map((c) => (
                              <td key={c.key} className={`px-3 py-3 ${c.type === "text" ? "text-left" : "text-right tabular-nums"}`}>
                                {formatCell(r[c.key], c.type)}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                      {totals && (
                        <tfoot>
                          <tr className="bg-[hsl(var(--background-subtle))] font-semibold">
                            {data.columns.map((c) => (
                              <td key={c.key} className={`px-3 py-3 ${c.type === "text" ? "text-left" : "text-right tabular-nums"}`}>
                                {totals[c.key] == null ? "" : formatCell(totals[c.key], c.type)}
                              </td>
                            ))}
                          </tr>
                        </tfoot>
                      )}
                    </table>
                  </Card>
                )}

                {data.notes.map((n) => (<p key={n} className="text-xs text-[hsl(var(--foreground-muted))]">{n}</p>))}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
