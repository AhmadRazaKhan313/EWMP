"use client";

/**
 * Tax rules and contribution rules.
 *
 * The engine deliberately ships with no country's brackets baked in
 * (see PayrollTaxRule's docstring) — every tenant configures their own.
 * That made the absence of a UI here particularly costly: there was no
 * way at all to set up tax for a new org without Postman, and tax is the
 * one thing that can't be left unconfigured.
 *
 * The bracket editor validates before submitting rather than only
 * catching the backend's 400, because bracket mistakes are easy to make
 * by copy-paste (reversed ranges, a gap between two bands) and the
 * server returns them one at a time.
 */

import { useState } from "react";
import { Plus, Percent, Trash2, PiggyBank, Landmark } from "lucide-react";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";
import {
  Drawer, Field, Input, Select, Textarea, Checkbox, SaveButton, Tabs,
  QueryError, ListSkeleton,
} from "@/components/molecules/PayrollKit";
import {
  fmtDate, fmtMoney, humanize,
  useTaxRules, useCreateTaxRule, useDeactivateTaxRule,
  useContributionRules, useCreateContributionRule, useDeactivateContributionRule,
  type TaxRule, type ContributionRule,
} from "@/services/payroll.service";
import { PayrollNav } from "../PayrollNav";

type Tab = "tax" | "contributions";

export default function TaxRulesPage() {
  const [tab, setTab] = useState<Tab>("tax");
  const [drawer, setDrawer] = useState(false);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payroll"
        description="Manage salary processing, payslips, and compensation."
        action={
          <Button icon={<Plus size={15} />} onClick={() => setDrawer(true)}>
            {tab === "tax" ? "New Tax Rule" : "New Contribution Rule"}
          </Button>
        }
      />
      <PayrollNav />

      <Tabs<Tab>
        active={tab}
        onChange={setTab}
        tabs={[{ id: "tax", label: "Tax Rules" }, { id: "contributions", label: "Contributions" }]}
      />

      {tab === "tax" ? <TaxRulesList /> : <ContributionRulesList />}

      {drawer && tab === "tax" && <TaxRuleDrawer onClose={() => setDrawer(false)} />}
      {drawer && tab === "contributions" && <ContributionRuleDrawer onClose={() => setDrawer(false)} />}
    </div>
  );
}

// ── Tax rules ─────────────────────────────────────────────────────────────
function TaxRulesList() {
  const query = useTaxRules();
  const deactivate = useDeactivateTaxRule();

  if (query.isPending) return <ListSkeleton />;
  if (query.isError) return <QueryError error={query.error} onRetry={query.refetch} />;

  const rules = query.data?.items ?? [];
  if (rules.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={Percent}
          title="No tax rules configured"
          description="This engine ships with no jurisdiction's brackets built in — you configure the bands that apply to your org. Until one exists, no income tax is deducted from any payslip."
        />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {rules.map((r) => <TaxRuleCard key={r.id} rule={r} onDeactivate={() => deactivate.mutate(r.id)} />)}
    </div>
  );
}

function TaxRuleCard({ rule, onDeactivate }: { rule: TaxRule; onDeactivate: () => void }) {
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-heading text-sm font-semibold">{rule.name}</h3>
            {rule.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="default">Inactive</Badge>}
          </div>
          <p className="text-xs text-[hsl(var(--foreground-muted))]">
            {rule.country} · {rule.tax_year} · {humanize(rule.calculation_base)} ·
            effective {fmtDate(rule.effective_from)}
            {rule.effective_to ? ` to ${fmtDate(rule.effective_to)}` : " onwards"}
          </p>
        </div>
        {rule.is_active && (
          <button
            onClick={() => {
              if (window.confirm(`Deactivate "${rule.name}"? Payslips already generated keep their numbers; future runs stop using these brackets.`)) {
                onDeactivate();
              }
            }}
            title="Deactivate rule"
            aria-label="Deactivate rule"
            className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--status-error-bg))] hover:text-[hsl(var(--destructive))]"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>

      {rule.notes && <p className="mt-2 text-xs text-[hsl(var(--foreground-subtle))]">{rule.notes}</p>}

      <div className="mt-3 border-t border-[hsl(var(--border))] pt-3">
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--foreground-muted))]">
          Brackets — marginal
        </p>
        <div className="space-y-1">
          {rule.brackets.map((b, i) => (
            <div key={b.id ?? i} className="flex items-center justify-between text-sm">
              <span className="font-mono text-xs">
                {fmtMoney(b.min_amount)} – {b.max_amount === null ? "and above" : fmtMoney(b.max_amount)}
              </span>
              <span className="font-mono text-xs font-medium">{b.rate_percentage}%</span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

interface BracketDraft { key: string; min: string; max: string; rate: string }

const newBracket = (min = ""): BracketDraft => ({ key: crypto.randomUUID(), min, max: "", rate: "" });

function TaxRuleDrawer({ onClose }: { onClose: () => void }) {
  const create = useCreateTaxRule();
  const [name, setName] = useState("");
  const [country, setCountry] = useState("");
  const [taxYear, setTaxYear] = useState(`${new Date().getFullYear()}-${String(new Date().getFullYear() + 1).slice(2)}`);
  const [base, setBase] = useState("monthly_taxable_income");
  const [from, setFrom] = useState(new Date().toISOString().slice(0, 10));
  const [to, setTo] = useState("");
  const [notes, setNotes] = useState("");
  const [brackets, setBrackets] = useState<BracketDraft[]>([newBracket("0")]);

  function update(key: string, patch: Partial<BracketDraft>) {
    setBrackets((prev) => prev.map((b) => (b.key === key ? { ...b, ...patch } : b)));
  }

  /**
   * Same three checks the backend runs, applied here so the whole set is
   * reported at once. The server validates bracket by bracket and stops
   * at the first failure, which turns fixing a pasted-in table into a
   * round trip per row.
   */
  const bracketErrors: string[] = [];
  const parsed = brackets
    .map((b) => ({ ...b, minN: parseFloat(b.min), maxN: b.max === "" ? null : parseFloat(b.max), rateN: parseFloat(b.rate) }))
    .sort((a, b) => a.minN - b.minN);

  parsed.forEach((b, i) => {
    if (Number.isNaN(b.minN)) bracketErrors.push("Every bracket needs a lower bound.");
    if (Number.isNaN(b.rateN) || b.rateN < 0 || b.rateN > 100) bracketErrors.push("Rates must be between 0 and 100.");
    if (b.maxN !== null && b.maxN <= b.minN) bracketErrors.push(`A bracket's upper bound must be above ${b.min}.`);
    const prev = i > 0 ? parsed[i - 1] : undefined;
    if (prev && prev.maxN !== null) {
      if (b.minN < prev.maxN) bracketErrors.push("Brackets must not overlap.");
      if (b.minN > prev.maxN) {
        bracketErrors.push(`Income between ${fmtMoney(prev.maxN)} and ${fmtMoney(b.minN)} falls in no bracket.`);
      }
    }
  });

  const uniqueErrors = [...new Set(bracketErrors)];
  const valid =
    name.trim() !== "" && country.trim() !== "" && taxYear.trim() !== "" &&
    brackets.length > 0 && uniqueErrors.length === 0;

  return (
    <Drawer
      title="New Tax Rule"
      description="A named set of marginal brackets for one jurisdiction and year"
      width="max-w-2xl"
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <SaveButton
            pending={create.isPending}
            disabled={!valid}
            onClick={() =>
              create.mutate(
                {
                  name: name.trim(), country: country.trim(), tax_year: taxYear.trim(),
                  calculation_base: base, effective_from: from, effective_to: to || null,
                  notes: notes || null,
                  brackets: parsed.map((b, i) => ({
                    min_amount: b.minN, max_amount: b.maxN, rate_percentage: b.rateN, display_order: i,
                  })),
                },
                { onSuccess: onClose },
              )
            }
          >
            Create Tax Rule
          </SaveButton>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="Rule name" required>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Salaried Individuals FY2026-27" />
        </Field>
        <Field label="Country" required>
          <Input value={country} onChange={(e) => setCountry(e.target.value)} placeholder="Pakistan" />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Tax year" required>
          <Input value={taxYear} onChange={(e) => setTaxYear(e.target.value)} placeholder="2026-27" />
        </Field>
        <Field label="Applied to">
          <Select value={base} onChange={(e) => setBase(e.target.value)}>
            <option value="monthly_taxable_income">Monthly taxable income</option>
            <option value="annual_taxable_income">Annual taxable income</option>
          </Select>
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Effective from" required>
          <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="Effective to" hint="Leave blank for open-ended.">
          <Input type="date" min={from} value={to} onChange={(e) => setTo(e.target.value)} />
        </Field>
      </div>

      <Field label="Notes">
        <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Reference to the statute or circular these came from" />
      </Field>

      <div className="border-t border-[hsl(var(--border))] pt-4">
        <div className="mb-2 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold">Brackets</h3>
            <p className="text-[11px] text-[hsl(var(--foreground-muted))]">
              Marginal, not flat — each rate applies only to the income inside its own band.
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            icon={<Plus size={12} />}
            onClick={() => {
              const last = brackets[brackets.length - 1];
              setBrackets((p) => [...p, newBracket(last?.max || "")]);
            }}
          >
            Add bracket
          </Button>
        </div>

        <div className="space-y-2">
          {brackets.map((b) => (
            <div key={b.key} className="flex items-center gap-2">
              <Input type="number" value={b.min} onChange={(e) => update(b.key, { min: e.target.value })} placeholder="From" className="font-mono text-xs" />
              <Input type="number" value={b.max} onChange={(e) => update(b.key, { max: e.target.value })} placeholder="To (blank = no cap)" className="font-mono text-xs" />
              <div className="relative w-24 shrink-0">
                <Input type="number" value={b.rate} onChange={(e) => update(b.key, { rate: e.target.value })} placeholder="0" className="pr-6 font-mono text-xs" />
                <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-[hsl(var(--foreground-muted))]">%</span>
              </div>
              <button
                onClick={() => setBrackets((p) => p.filter((x) => x.key !== b.key))}
                disabled={brackets.length === 1}
                title="Remove bracket"
                aria-label="Remove bracket"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--status-error-bg))] hover:text-[hsl(var(--destructive))] disabled:opacity-35"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>

        {uniqueErrors.length > 0 && (
          <ul className="mt-2 space-y-0.5">
            {uniqueErrors.map((e) => (
              <li key={e} className="text-[11px] text-[hsl(var(--destructive))]">{e}</li>
            ))}
          </ul>
        )}
      </div>
    </Drawer>
  );
}

// ── Contribution rules ────────────────────────────────────────────────────
function ContributionRulesList() {
  const query = useContributionRules();
  const deactivate = useDeactivateContributionRule();

  if (query.isPending) return <ListSkeleton />;
  if (query.isError) return <QueryError error={query.error} onRetry={query.refetch} />;

  const rules = query.data?.items ?? [];
  if (rules.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={PiggyBank}
          title="No contribution rules configured"
          description="Provident fund, social security, pension — anything where the employee and the employer each put in a share. The employee's share is deducted from net pay; the employer's is recorded but doesn't affect it."
        />
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {rules.map((r) => <ContributionCard key={r.id} rule={r} onDeactivate={() => deactivate.mutate(r.id)} />)}
    </div>
  );
}

function Share({ label, percentage, fixed }: { label: string; percentage: string | null; fixed: string | null }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-[hsl(var(--foreground-muted))]">{label}</span>
      <span className="font-mono text-xs font-medium">
        {percentage ? `${percentage}%` : fixed ? fmtMoney(fixed) : "—"}
      </span>
    </div>
  );
}

function ContributionCard({ rule, onDeactivate }: { rule: ContributionRule; onDeactivate: () => void }) {
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-heading text-sm font-semibold">{rule.name}</h3>
            {rule.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="default">Inactive</Badge>}
            {rule.is_taxable && <Badge variant="warning">Taxable</Badge>}
          </div>
          <p className="font-mono text-[11px] text-[hsl(var(--foreground-muted))]">
            {rule.code} · on {rule.calculation_base}
          </p>
        </div>
        {rule.is_active && (
          <button
            onClick={() => {
              if (window.confirm(`Deactivate "${rule.name}"? Future runs stop applying it.`)) onDeactivate();
            }}
            title="Deactivate rule"
            aria-label="Deactivate rule"
            className="flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--status-error-bg))] hover:text-[hsl(var(--destructive))]"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>

      <div className="mt-3 space-y-1 border-t border-[hsl(var(--border))] pt-3">
        <Share label="Employee pays" percentage={rule.employee_percentage} fixed={rule.employee_fixed_amount} />
        <Share label="Employer pays" percentage={rule.employer_percentage} fixed={rule.employer_fixed_amount} />
        {(rule.min_base || rule.max_base) && (
          <div className="flex items-center justify-between pt-1 text-[11px] text-[hsl(var(--foreground-muted))]">
            <span>Base clamped to</span>
            <span className="font-mono">
              {rule.min_base ? fmtMoney(rule.min_base) : "no floor"} – {rule.max_base ? fmtMoney(rule.max_base) : "no ceiling"}
            </span>
          </div>
        )}
      </div>
    </Card>
  );
}

function ContributionRuleDrawer({ onClose }: { onClose: () => void }) {
  const create = useCreateContributionRule();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [base, setBase] = useState<"basic" | "gross">("basic");
  const [empPct, setEmpPct] = useState("");
  const [empFixed, setEmpFixed] = useState("");
  const [erPct, setErPct] = useState("");
  const [erFixed, setErFixed] = useState("");
  const [minBase, setMinBase] = useState("");
  const [maxBase, setMaxBase] = useState("");
  const [taxable, setTaxable] = useState(false);
  const [from, setFrom] = useState(new Date().toISOString().slice(0, 10));

  const num = (v: string) => (v.trim() === "" ? null : parseFloat(v));
  const hasAnyShare = [empPct, empFixed, erPct, erFixed].some((v) => v.trim() !== "" && parseFloat(v) > 0);
  const boundsOk =
    minBase.trim() === "" || maxBase.trim() === "" || parseFloat(minBase) <= parseFloat(maxBase);
  const valid = name.trim() !== "" && code.trim() !== "" && hasAnyShare && boundsOk;

  return (
    <Drawer
      title="New Contribution Rule"
      description="A shared employee/employer contribution such as a provident fund"
      onClose={onClose}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <SaveButton
            pending={create.isPending}
            disabled={!valid}
            onClick={() =>
              create.mutate(
                {
                  name: name.trim(), code: code.trim().toUpperCase(), calculation_base: base,
                  employee_percentage: num(empPct), employee_fixed_amount: num(empFixed),
                  employer_percentage: num(erPct), employer_fixed_amount: num(erFixed),
                  min_base: num(minBase), max_base: num(maxBase),
                  is_taxable: taxable, effective_from: from,
                },
                { onSuccess: onClose },
              )
            }
          >
            Create Rule
          </SaveButton>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="Name" required>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Employees' Provident Fund" />
        </Field>
        <Field label="Code" required hint="Used as the payslip line code.">
          <Input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="EPF" className="font-mono" />
        </Field>
      </div>

      <Field label="Calculated on">
        <Select value={base} onChange={(e) => setBase(e.target.value as "basic" | "gross")}>
          <option value="basic">Basic salary</option>
          <option value="gross">Gross salary</option>
        </Select>
      </Field>

      <div className="rounded-lg border border-[hsl(var(--border))] p-3">
        <p className="mb-2 text-xs font-semibold">Employee share</p>
        <p className="mb-2 text-[11px] text-[hsl(var(--foreground-muted))]">
          Deducted from net pay. Set a percentage or a fixed amount, not both.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Percentage"><Input type="number" min={0} max={100} value={empPct} onChange={(e) => setEmpPct(e.target.value)} placeholder="0" /></Field>
          <Field label="Fixed amount"><Input type="number" min={0} value={empFixed} onChange={(e) => setEmpFixed(e.target.value)} placeholder="0.00" /></Field>
        </div>
      </div>

      <div className="rounded-lg border border-[hsl(var(--border))] p-3">
        <p className="mb-2 text-xs font-semibold">Employer share</p>
        <p className="mb-2 text-[11px] text-[hsl(var(--foreground-muted))]">
          Recorded as a cost to the company — it appears on the payslip for transparency but does not change net pay.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Percentage"><Input type="number" min={0} max={100} value={erPct} onChange={(e) => setErPct(e.target.value)} placeholder="0" /></Field>
          <Field label="Fixed amount"><Input type="number" min={0} value={erFixed} onChange={(e) => setErFixed(e.target.value)} placeholder="0.00" /></Field>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Minimum base" hint="Base is raised to this before the rate applies.">
          <Input type="number" min={0} value={minBase} onChange={(e) => setMinBase(e.target.value)} placeholder="Optional" />
        </Field>
        <Field label="Maximum base" hint="Base is capped here — the usual statutory ceiling.">
          <Input type="number" min={0} value={maxBase} onChange={(e) => setMaxBase(e.target.value)} placeholder="Optional" />
        </Field>
      </div>

      {!boundsOk && (
        <p className="text-[11px] text-[hsl(var(--destructive))]">Minimum base can&apos;t be above the maximum.</p>
      )}
      {!hasAnyShare && (
        <p className="flex items-center gap-1.5 text-[11px] text-[hsl(var(--foreground-muted))]">
          <Landmark size={11} /> Set at least one employee or employer share before saving.
        </p>
      )}

      <Field label="Effective from" required>
        <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
      </Field>

      <Checkbox checked={taxable} onChange={setTaxable} label="Employee's share is taxable" />
    </Drawer>
  );
}
