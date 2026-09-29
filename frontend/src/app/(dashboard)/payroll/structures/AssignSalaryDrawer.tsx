"use client";

/**
 * Assign a salary structure to an employee.
 *
 * Until this existed there was no way to put an employee on a structure
 * from the UI at all — which meant a payroll run would generate zero
 * payslips and give no hint why, because "employee has no current salary
 * assignment" is a condition you can only see by querying for it.
 *
 * Two things this surfaces that the raw endpoint doesn't:
 *
 *  1. The existing assignment, if there is one, with a plain statement
 *     that saving supersedes it from the effective date. The backend
 *     silently marks the previous row not-current; doing that invisibly
 *     to someone who thought they were editing is how you get two
 *     salaries in one month.
 *
 *  2. A live preview of what the structure resolves to at the basic
 *     salary being typed. Percentage components are the whole point of a
 *     structure and their value isn't knowable until a basic is chosen.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import apiClient from "@/services/api-client";
import { Badge, Button, Card, Skeleton } from "@/components/atoms";
import {
  Drawer, EmployeeSelect, Field, Input, Select, SaveButton,
} from "@/components/molecules/PayrollKit";
import {
  fmtMoney, useAssignEmployeeSalary, useEmployeeSalary, payrollKeys,
} from "@/services/payroll.service";

interface StructureComponent {
  id: string; name: string; code: string; component_type: string;
  calculation_type: string; amount: string | null; percentage: string | null;
  is_taxable: boolean; display_order: number;
}

interface SalaryStructure {
  id: string; name: string; code: string; currency: string;
  is_default: boolean; version: number; components: StructureComponent[];
}

/**
 * Preview arithmetic only. It resolves fixed amounts and percentages of
 * basic — NOT formulas or percentage-of-gross, both of which depend on
 * evaluation order the server owns. Those are shown as "calculated on
 * generation" rather than guessed at, because a preview that is wrong
 * about one line is worse than one that admits what it doesn't know.
 */
function resolveComponent(c: StructureComponent, basic: number): number | null {
  if (c.calculation_type === "fixed") return parseFloat(c.amount ?? "0");
  if (c.calculation_type === "percentage_of_basic") return (basic * parseFloat(c.percentage ?? "0")) / 100;
  return null;
}

export function AssignSalaryDrawer({
  employeeId: fixedEmployeeId,
  employeeName,
  onClose,
}: {
  employeeId?: string;
  employeeName?: string;
  onClose: () => void;
}) {
  const [employeeId, setEmployeeId] = useState(fixedEmployeeId ?? "");
  const [structureId, setStructureId] = useState("");
  const [basic, setBasic] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(new Date().toISOString().slice(0, 10));
  const [overrides, setOverrides] = useState<Record<string, string>>({});

  const assign = useAssignEmployeeSalary();
  const existing = useEmployeeSalary(employeeId || null);

  const structuresQuery = useQuery({
    queryKey: payrollKeys.structures(),
    queryFn: async () =>
      (await apiClient.get<{ items: SalaryStructure[]; total: number }>("/payroll/salary-structures")).data,
  });

  const structures = useMemo(() => structuresQuery.data?.items ?? [], [structuresQuery.data]);
  const structure = structures.find((s) => s.id === structureId);

  // Default to the org's default structure rather than leaving the field
  // blank — that's what "default" is for, and it's the right answer for
  // most assignments.
  useEffect(() => {
    if (structureId) return;
    const preferred = structures.find((s) => s.is_default) ?? structures[0];
    if (preferred) setStructureId(preferred.id);
  }, [structures, structureId]);

  // Prefill from the current assignment so this reads as an edit when
  // one exists, not as a blank form that silently replaces it.
  useEffect(() => {
    if (existing.data?.assigned) {
      setStructureId((prev) => prev || existing.data.salary_structure_id || "");
      setBasic((prev) => prev || (existing.data.basic_salary ?? ""));
    }
  }, [existing.data]);

  const basicNum = parseFloat(basic) || 0;
  const currency = structure?.currency ?? "USD";

  const preview = (structure?.components ?? []).map((c) => {
    const override = overrides[c.code];
    const overridden = override !== undefined && override.trim() !== "";
    return {
      component: c,
      value: overridden ? parseFloat(override) : resolveComponent(c, basicNum),
      overridden,
    };
  });

  const earnings = preview.filter((p) => p.component.component_type === "earning");
  const deductions = preview.filter((p) => p.component.component_type === "deduction");
  const knownGross = earnings.reduce((s, p) => s + (p.value ?? 0), 0);
  const knownDeductions = deductions.reduce((s, p) => s + (p.value ?? 0), 0);
  const hasUnknown = preview.some((p) => p.value === null);

  const valid = !!employeeId && !!structureId && basicNum > 0;

  return (
    <Drawer
      title="Assign Salary Structure"
      description={employeeName ? `For ${employeeName}` : "Put an employee on a structure so runs can generate their payslip"}
      width="max-w-2xl"
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <SaveButton
            pending={assign.isPending}
            disabled={!valid}
            onClick={() =>
              assign.mutate(
                {
                  employeeId,
                  salary_structure_id: structureId,
                  basic_salary: basicNum,
                  effective_from: effectiveFrom,
                  component_overrides: Object.fromEntries(
                    Object.entries(overrides)
                      .filter(([, v]) => v.trim() !== "")
                      .map(([k, v]) => [k, parseFloat(v)]),
                  ),
                },
                { onSuccess: onClose },
              )
            }
          >
            {existing.data?.assigned ? "Replace Assignment" : "Assign Structure"}
          </SaveButton>
        </>
      }
    >
      {!fixedEmployeeId && (
        <Field label="Employee" required>
          <EmployeeSelect value={employeeId} onChange={(id) => setEmployeeId(id)} />
        </Field>
      )}

      {employeeId && existing.isPending && <Skeleton className="h-16" />}

      {existing.data?.assigned && (
        <Card className="bg-[hsl(var(--info-subtle))]">
          <div className="flex items-start gap-2.5">
            <Info size={15} className="mt-0.5 shrink-0 text-[hsl(var(--info))]" />
            <div className="text-xs">
              <p className="font-medium">
                Already on a structure at {fmtMoney(existing.data.basic_salary, currency)} basic, effective{" "}
                {existing.data.effective_from}.
              </p>
              <p className="mt-0.5 text-[hsl(var(--foreground-subtle))]">
                Saving supersedes that assignment from the effective date below — it isn&apos;t deleted, so payslips
                already generated keep the figures they were calculated with.
              </p>
            </div>
          </div>
        </Card>
      )}

      <Field label="Salary structure" required>
        {structuresQuery.isPending ? (
          <Skeleton className="h-9" />
        ) : structures.length === 0 ? (
          <p className="rounded-md border border-[hsl(var(--border))] px-3 py-2 text-sm text-[hsl(var(--foreground-muted))]">
            No structures exist yet — create one first.
          </p>
        ) : (
          <Select value={structureId} onChange={(e) => { setStructureId(e.target.value); setOverrides({}); }}>
            {structures.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.code}) · v{s.version}{s.is_default ? " · default" : ""}
              </option>
            ))}
          </Select>
        )}
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label={`Basic salary${structure ? ` (${currency})` : ""}`} required>
          <Input type="number" min={0} value={basic} onChange={(e) => setBasic(e.target.value)} placeholder="0.00" />
        </Field>
        <Field label="Effective from" required hint="Payroll runs before this date are unaffected.">
          <Input type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
        </Field>
      </div>

      {structure && basicNum > 0 && (
        <div className="border-t border-[hsl(var(--border))] pt-4">
          <h3 className="text-sm font-semibold">What this resolves to</h3>
          <p className="mb-2.5 text-[11px] text-[hsl(var(--foreground-muted))]">
            Override any line for this employee only — leave blank to use the structure&apos;s own value.
          </p>

          <div className="space-y-1.5">
            {preview.map(({ component: c, value, overridden }) => (
              <div key={c.id} className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">
                    {c.name}
                    {c.component_type === "deduction" && (
                      <span className="ml-1.5 text-[10px] text-[hsl(var(--destructive))]">deduction</span>
                    )}
                    {c.component_type === "employer_contribution" && (
                      <span className="ml-1.5 text-[10px] text-[hsl(var(--info))]">employer</span>
                    )}
                  </p>
                  <p className="font-mono text-[10px] text-[hsl(var(--foreground-muted))]">
                    {c.code} ·{" "}
                    {c.calculation_type === "fixed" ? "fixed"
                      : c.calculation_type === "percentage_of_basic" ? `${c.percentage}% of basic`
                      : c.calculation_type === "percentage_of_gross" ? `${c.percentage}% of gross`
                      : "formula"}
                  </p>
                </div>

                <span className="w-28 shrink-0 text-right font-mono text-xs">
                  {value === null ? (
                    <span className="text-[hsl(var(--foreground-muted))]">on generation</span>
                  ) : (
                    fmtMoney(value, currency)
                  )}
                </span>

                <Input
                  type="number"
                  value={overrides[c.code] ?? ""}
                  onChange={(e) => setOverrides((p) => ({ ...p, [c.code]: e.target.value }))}
                  placeholder="Override"
                  className={`w-28 shrink-0 text-xs ${overridden ? "border-[hsl(var(--info))]" : ""}`}
                />
              </div>
            ))}
          </div>

          <div className="mt-3 space-y-1 rounded-lg bg-[hsl(var(--accent))] p-3">
            <div className="flex items-center justify-between text-sm">
              <span>Gross earnings</span>
              <span className="font-mono font-semibold">{fmtMoney(knownGross, currency)}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span>Deductions</span>
              <span className="font-mono font-semibold text-[hsl(var(--destructive))]">
                -{fmtMoney(knownDeductions, currency)}
              </span>
            </div>
            <div className="flex items-center justify-between border-t border-[hsl(var(--border))] pt-1 text-sm font-semibold">
              <span>Net</span>
              <span className="font-mono">{fmtMoney(knownGross - knownDeductions, currency)}</span>
            </div>
            {hasUnknown && (
              <p className="pt-1 text-[10px] text-[hsl(var(--foreground-muted))]">
                Formula and percentage-of-gross lines resolve when the run generates, so they aren&apos;t in this total.
                Tax and contribution rules apply on top of it.
              </p>
            )}
          </div>

          {Object.values(overrides).some((v) => v.trim() !== "") && (
            <Badge variant="info" className="mt-2">
              {Object.values(overrides).filter((v) => v.trim() !== "").length} override(s) apply to this employee only
            </Badge>
          )}
        </div>
      )}
    </Drawer>
  );
}
