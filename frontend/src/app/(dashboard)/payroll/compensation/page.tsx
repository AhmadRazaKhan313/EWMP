"use client";

/**
 * Compensation — loans, advances, bonuses, commissions, arrears and
 * reimbursement claims.
 *
 * All six of these were fully implemented on the backend and completely
 * unreachable from the UI; the only way to create a loan or approve a
 * bonus was Postman. They share one page rather than six routes because
 * they are one job — "what else is going into this person's pay besides
 * their structure" — and because an HR admin reconciling a run needs to
 * move between them without losing their place.
 *
 * The split down the middle is deliberate: loans and advances are
 * RECOVERIES (money coming back out of pay over time, tracked by
 * remaining balance), while bonuses, commissions and arrears are
 * ADDITIONS gated behind an approval. Reimbursements are additions with
 * their own reject path. The tab order follows that grouping.
 */

import { useState } from "react";
import {
  Plus, Landmark, HandCoins, Gift, TrendingUp, History, Receipt, Ban, Check, X,
} from "lucide-react";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";
import {
  Drawer, EmployeeSelect, Field, Input, Select, Textarea, Checkbox, SaveButton, Tabs,
  QueryError, ListSkeleton, useEmployeeNames,
} from "@/components/molecules/PayrollKit";
import {
  BONUS_TYPES, REIMBURSEMENT_CATEGORIES, fmtDate, fmtMoney, humanize,
  useLoans, useCreateLoan, useCancelLoan,
  useAdvances, useCreateAdvance,
  useBonuses, useCreateBonus, useApproveBonus,
  useArrears, useCreateArrear, useApproveArrear,
  useReimbursements, useCreateReimbursement, useApproveReimbursement, useRejectReimbursement,
  useCreateCommission,
  type BonusType, type ReimbursementCategory,
} from "@/services/payroll.service";
import { PayrollNav } from "../PayrollNav";

type Tab = "loans" | "advances" | "bonuses" | "commissions" | "arrears" | "reimbursements";

const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => new Date().toISOString().slice(0, 8) + "01";

const statusVariant = (s: string) =>
  s === "approved" || s === "paid" || s === "closed" ? "success" as const
  : s === "pending" || s === "submitted" || s === "reviewed" ? "warning" as const
  : s === "rejected" || s === "cancelled" ? "error" as const
  : "info" as const;

export default function CompensationPage() {
  const [tab, setTab] = useState<Tab>("loans");
  const [drawer, setDrawer] = useState(false);

  const loans = useLoans();
  const advances = useAdvances();
  const bonuses = useBonuses();
  const arrears = useArrears();
  const reimbursements = useReimbursements();

  // Counts on the tabs are the pending items only — the number that
  // means "something is waiting on you", not "how many rows exist".
  const pendingCounts = {
    loans: 0,
    advances: 0,
    bonuses: (bonuses.data?.items ?? []).filter((b) => b.status === "pending").length,
    commissions: 0,
    arrears: (arrears.data?.items ?? []).filter((a) => a.status === "pending").length,
    reimbursements: (reimbursements.data?.items ?? []).filter((r) => r.status === "submitted").length,
  };

  const newLabel: Record<Tab, string> = {
    loans: "New Loan",
    advances: "New Advance",
    bonuses: "New Bonus",
    commissions: "Record Commission",
    arrears: "New Arrear",
    reimbursements: "New Claim",
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payroll"
        description="Manage salary processing, payslips, and compensation."
        action={<Button icon={<Plus size={15} />} onClick={() => setDrawer(true)}>{newLabel[tab]}</Button>}
      />
      <PayrollNav />

      <Tabs<Tab>
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "loans", label: "Loans" },
          { id: "advances", label: "Advances" },
          { id: "bonuses", label: "Bonuses", count: pendingCounts.bonuses },
          { id: "commissions", label: "Commissions" },
          { id: "arrears", label: "Arrears", count: pendingCounts.arrears },
          { id: "reimbursements", label: "Reimbursements", count: pendingCounts.reimbursements },
        ]}
      />

      {tab === "loans" && <LoansTab query={loans} />}
      {tab === "advances" && <AdvancesTab query={advances} />}
      {tab === "bonuses" && <BonusesTab query={bonuses} />}
      {tab === "commissions" && <CommissionsTab />}
      {tab === "arrears" && <ArrearsTab query={arrears} />}
      {tab === "reimbursements" && <ReimbursementsTab query={reimbursements} />}

      {drawer && tab === "loans" && <LoanDrawer onClose={() => setDrawer(false)} />}
      {drawer && tab === "advances" && <AdvanceDrawer onClose={() => setDrawer(false)} />}
      {drawer && tab === "bonuses" && <BonusDrawer onClose={() => setDrawer(false)} />}
      {drawer && tab === "commissions" && <CommissionDrawer onClose={() => setDrawer(false)} />}
      {drawer && tab === "arrears" && <ArrearDrawer onClose={() => setDrawer(false)} />}
      {drawer && tab === "reimbursements" && <ReimbursementDrawer onClose={() => setDrawer(false)} />}
    </div>
  );
}

// ── Shared row chrome ─────────────────────────────────────────────────────
function Rows({ children }: { children: React.ReactNode }) {
  return (
    <Card padding={false}>
      <div className="divide-y divide-[hsl(var(--border))]">{children}</div>
    </Card>
  );
}

function Row({
  name, code, primary, meta, status, actions,
}: {
  name: string; code: string; primary: React.ReactNode;
  meta: React.ReactNode; status: string; actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-4 px-5 py-3.5">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{name}</p>
        <p className="font-mono text-[11px] text-[hsl(var(--foreground-muted))]">{code}</p>
      </div>
      <div className="hidden min-w-0 flex-[2] sm:block">
        <p className="truncate text-sm">{primary}</p>
        <p className="truncate text-[11px] text-[hsl(var(--foreground-muted))]">{meta}</p>
      </div>
      <Badge variant={statusVariant(status)}>{humanize(status)}</Badge>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </div>
  );
}

function IconAction({
  onClick, disabled, title, tone = "neutral", children,
}: {
  onClick: () => void; disabled?: boolean; title: string;
  tone?: "neutral" | "danger" | "success"; children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={onClick}
      className={
        "flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] " +
        "disabled:cursor-not-allowed disabled:opacity-35 " +
        (tone === "danger"
          ? "hover:bg-[hsl(var(--status-error-bg))] hover:text-[hsl(var(--destructive))]"
          : tone === "success"
            ? "hover:bg-[hsl(var(--status-active-bg))] hover:text-[hsl(var(--success))]"
            : "hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]")
      }
    >
      {children}
    </button>
  );
}

type ListQuery<T> = {
  data?: { items: T[]; total: number };
  isPending: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
};

/** Every tab is list → skeleton → error → empty → rows. Written once. */
function TabShell<T>({
  query, icon, title, body, children,
}: {
  query: ListQuery<T>;
  icon: React.ElementType;
  title: string;
  body: string;
  children: (items: T[]) => React.ReactNode;
}) {
  if (query.isPending) return <ListSkeleton />;
  if (query.isError) return <QueryError error={query.error} onRetry={query.refetch} />;
  const items = query.data?.items ?? [];
  if (items.length === 0) {
    return <Card><EmptyState icon={icon} title={title} description={body} /></Card>;
  }
  return <Rows>{children(items)}</Rows>;
}

// ── Loans ─────────────────────────────────────────────────────────────────
function LoansTab({ query }: { query: ReturnType<typeof useLoans> }) {
  const nameOf = useEmployeeNames();
  const cancel = useCancelLoan();

  return (
    <TabShell
      query={query}
      icon={Landmark}
      title="No loans recorded"
      body="Loans are repaid by a fixed installment deducted from each payroll run until the balance clears."
    >
      {(loans) =>
        loans.map((l) => {
          const emp = nameOf(l.employee_id);
          const repaid = parseFloat(l.principal_amount) - parseFloat(l.remaining_balance);
          return (
            <Row
              key={l.id}
              name={emp.name}
              code={emp.code}
              primary={
                <>
                  {fmtMoney(l.remaining_balance)} <span className="text-[hsl(var(--foreground-muted))]">left</span>
                  {" · "}
                  {fmtMoney(l.installment_amount)}/run
                </>
              }
              meta={`${fmtMoney(l.principal_amount)} principal at ${l.interest_rate}% · ${fmtMoney(repaid)} repaid · from ${fmtDate(l.start_date)}`}
              status={l.status}
              actions={
                <IconAction
                  title={l.status === "active" ? "Cancel loan" : "Only active loans can be cancelled"}
                  tone="danger"
                  disabled={l.status !== "active" || cancel.isPending}
                  onClick={() => {
                    if (window.confirm(`Cancel this loan? ${fmtMoney(l.remaining_balance)} is still outstanding and no further deductions will be taken.`)) {
                      cancel.mutate(l.id);
                    }
                  }}
                >
                  <Ban size={14} />
                </IconAction>
              }
            />
          );
        })
      }
    </TabShell>
  );
}

function LoanDrawer({ onClose }: { onClose: () => void }) {
  const create = useCreateLoan();
  const [employeeId, setEmployeeId] = useState("");
  const [principal, setPrincipal] = useState("");
  const [rate, setRate] = useState("0");
  const [installments, setInstallments] = useState("12");
  const [startDate, setStartDate] = useState(today());
  const [reason, setReason] = useState("");

  // Mirrors the backend's own arithmetic (principal * (1 + rate/100) /
  // installments) so the number shown here is the number that will be
  // deducted — not an approximation the user has to reconcile later.
  const p = parseFloat(principal) || 0;
  const r = parseFloat(rate) || 0;
  const n = parseInt(installments, 10) || 0;
  const totalPayable = p * (1 + r / 100);
  const perRun = n > 0 ? totalPayable / n : 0;
  const valid = !!employeeId && p > 0 && n > 0;

  return (
    <Drawer
      title="New Loan"
      description="Repaid by an equal deduction from each payroll run"
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
                  employee_id: employeeId,
                  principal_amount: p,
                  interest_rate: r,
                  number_of_installments: n,
                  start_date: startDate,
                  reason: reason || null,
                },
                { onSuccess: onClose },
              )
            }
          >
            Create Loan
          </SaveButton>
        </>
      }
    >
      <Field label="Employee" required>
        <EmployeeSelect value={employeeId} onChange={(id) => setEmployeeId(id)} />
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Principal amount" required>
          <Input type="number" min={0} value={principal} onChange={(e) => setPrincipal(e.target.value)} placeholder="0.00" />
        </Field>
        <Field label="Interest rate (%)" hint="Flat rate applied to the whole principal.">
          <Input type="number" min={0} max={100} value={rate} onChange={(e) => setRate(e.target.value)} />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Number of installments" required>
          <Input type="number" min={1} value={installments} onChange={(e) => setInstallments(e.target.value)} />
        </Field>
        <Field label="First deduction from" required>
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </Field>
      </div>

      <Field label="Reason">
        <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="What this loan is for" />
      </Field>

      {valid && (
        <div className="rounded-lg bg-[hsl(var(--accent))] p-3.5">
          <div className="flex items-baseline justify-between">
            <span className="text-sm">Deducted each run</span>
            <span className="font-mono text-lg font-semibold">{fmtMoney(perRun)}</span>
          </div>
          <p className="mt-1 text-[11px] text-[hsl(var(--foreground-muted))]">
            {fmtMoney(totalPayable)} total over {n} run{n === 1 ? "" : "s"}
            {r > 0 && ` — ${fmtMoney(totalPayable - p)} of that is interest`}.
            A deduction is capped at the remaining balance, so the final run takes whatever is left.
          </p>
        </div>
      )}
    </Drawer>
  );
}

// ── Advances ──────────────────────────────────────────────────────────────
function AdvancesTab({ query }: { query: ReturnType<typeof useAdvances> }) {
  const nameOf = useEmployeeNames();
  return (
    <TabShell
      query={query}
      icon={HandCoins}
      title="No advances recorded"
      body="A salary advance is money paid early and recovered from later runs. Unlike a loan it carries no interest."
    >
      {(advances) =>
        advances.map((a) => {
          const emp = nameOf(a.employee_id);
          return (
            <Row
              key={a.id}
              name={emp.name}
              code={emp.code}
              primary={
                <>
                  {fmtMoney(a.remaining_balance)} <span className="text-[hsl(var(--foreground-muted))]">left</span>
                  {" · "}{fmtMoney(a.installment_amount)}/run
                </>
              }
              meta={`${fmtMoney(a.advance_amount)} advanced over ${a.number_of_installments} runs · recovery from ${fmtDate(a.recovery_start_date)}${a.reason ? ` · ${a.reason}` : ""}`}
              status={a.status}
            />
          );
        })
      }
    </TabShell>
  );
}

function AdvanceDrawer({ onClose }: { onClose: () => void }) {
  const create = useCreateAdvance();
  const [employeeId, setEmployeeId] = useState("");
  const [amount, setAmount] = useState("");
  const [installments, setInstallments] = useState("3");
  const [startDate, setStartDate] = useState(today());
  const [reason, setReason] = useState("");

  const a = parseFloat(amount) || 0;
  const n = parseInt(installments, 10) || 0;
  const valid = !!employeeId && a > 0 && n > 0;

  return (
    <Drawer
      title="New Salary Advance"
      description="Recovered in equal installments from upcoming runs"
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
                  employee_id: employeeId,
                  advance_amount: a,
                  number_of_installments: n,
                  recovery_start_date: startDate,
                  reason: reason || null,
                },
                { onSuccess: onClose },
              )
            }
          >
            Create Advance
          </SaveButton>
        </>
      }
    >
      <Field label="Employee" required>
        <EmployeeSelect value={employeeId} onChange={(id) => setEmployeeId(id)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Advance amount" required>
          <Input type="number" min={0} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
        </Field>
        <Field label="Recover over (runs)" required>
          <Input type="number" min={1} value={installments} onChange={(e) => setInstallments(e.target.value)} />
        </Field>
      </div>
      <Field label="Recovery starts" required>
        <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
      </Field>
      <Field label="Reason">
        <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>

      {valid && (
        <div className="rounded-lg bg-[hsl(var(--accent))] p-3.5">
          <div className="flex items-baseline justify-between">
            <span className="text-sm">Recovered each run</span>
            <span className="font-mono text-lg font-semibold">{fmtMoney(a / n)}</span>
          </div>
          <p className="mt-1 text-[11px] text-[hsl(var(--foreground-muted))]">
            No interest is applied to advances — {fmtMoney(a)} out, {fmtMoney(a)} back.
          </p>
        </div>
      )}
    </Drawer>
  );
}

// ── Bonuses ───────────────────────────────────────────────────────────────
function BonusesTab({ query }: { query: ReturnType<typeof useBonuses> }) {
  const nameOf = useEmployeeNames();
  const approve = useApproveBonus();

  return (
    <TabShell
      query={query}
      icon={Gift}
      title="No bonuses recorded"
      body="Bonuses stay pending until approved. Only approved ones are picked up by a run whose period overlaps the bonus's target period."
    >
      {(bonuses) =>
        bonuses.map((b) => {
          const emp = nameOf(b.employee_id);
          return (
            <Row
              key={b.id}
              name={emp.name}
              code={emp.code}
              primary={<>{b.name} — {fmtMoney(b.amount)}</>}
              meta={`${humanize(b.bonus_type)} · pays in the run covering ${fmtDate(b.target_period_start)} – ${fmtDate(b.target_period_end)}${b.is_taxable ? "" : " · non-taxable"}`}
              status={b.status}
              actions={
                <IconAction
                  title={b.status === "pending" ? "Approve bonus" : "Only pending bonuses can be approved"}
                  tone="success"
                  disabled={b.status !== "pending" || approve.isPending}
                  onClick={() => approve.mutate(b.id)}
                >
                  <Check size={15} />
                </IconAction>
              }
            />
          );
        })
      }
    </TabShell>
  );
}

function BonusDrawer({ onClose }: { onClose: () => void }) {
  const create = useCreateBonus();
  const [employeeId, setEmployeeId] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<BonusType>("performance");
  const [amount, setAmount] = useState("");
  const [taxable, setTaxable] = useState(true);
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const [notes, setNotes] = useState("");

  const valid = !!employeeId && name.trim() !== "" && (parseFloat(amount) || 0) > 0 && to >= from;

  return (
    <Drawer
      title="New Bonus"
      description="Created as pending — it needs approval before any run will pay it"
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
                  employee_id: employeeId, bonus_type: type, name: name.trim(),
                  amount: parseFloat(amount), is_taxable: taxable,
                  target_period_start: from, target_period_end: to, notes: notes || null,
                },
                { onSuccess: onClose },
              )
            }
          >
            Create Bonus
          </SaveButton>
        </>
      }
    >
      <Field label="Employee" required>
        <EmployeeSelect value={employeeId} onChange={(id) => setEmployeeId(id)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Bonus name" required>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Q3 Performance Bonus" />
        </Field>
        <Field label="Type">
          <Select value={type} onChange={(e) => setType(e.target.value as BonusType)}>
            {BONUS_TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
          </Select>
        </Field>
      </div>
      <Field label="Amount" required>
        <Input type="number" min={0} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Target period start" required>
          <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="Target period end" required>
          <Input type="date" min={from} value={to} onChange={(e) => setTo(e.target.value)} />
        </Field>
      </div>
      <p className="-mt-1 text-[11px] text-[hsl(var(--foreground-muted))]">
        The bonus is paid by whichever payroll run overlaps this window — it does not need to match a run exactly.
      </p>
      <Checkbox checked={taxable} onChange={setTaxable} label="Taxable" />
      <Field label="Notes">
        <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
    </Drawer>
  );
}

// ── Arrears ───────────────────────────────────────────────────────────────
function ArrearsTab({ query }: { query: ReturnType<typeof useArrears> }) {
  const nameOf = useEmployeeNames();
  const approve = useApproveArrear();

  return (
    <TabShell
      query={query}
      icon={History}
      title="No arrears recorded"
      body="An arrear is a backdated correction — an increment approved late, or pay that was missed — recorded against the period it fixes and paid in a later one."
    >
      {(arrears) =>
        arrears.map((a) => {
          const emp = nameOf(a.employee_id);
          return (
            <Row
              key={a.id}
              name={emp.name}
              code={emp.code}
              primary={<>{fmtMoney(a.amount)} — {a.reason}</>}
              meta={`corrects ${fmtDate(a.source_period_start)} – ${fmtDate(a.source_period_end)} · pays in ${fmtDate(a.target_period_start)} – ${fmtDate(a.target_period_end)}`}
              status={a.status}
              actions={
                <IconAction
                  title={a.status === "pending" ? "Approve arrear" : "Only pending arrears can be approved"}
                  tone="success"
                  disabled={a.status !== "pending" || approve.isPending}
                  onClick={() => approve.mutate(a.id)}
                >
                  <Check size={15} />
                </IconAction>
              }
            />
          );
        })
      }
    </TabShell>
  );
}

function ArrearDrawer({ onClose }: { onClose: () => void }) {
  const create = useCreateArrear();
  const [employeeId, setEmployeeId] = useState("");
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const [taxable, setTaxable] = useState(true);
  const [srcFrom, setSrcFrom] = useState(monthStart());
  const [srcTo, setSrcTo] = useState(today());
  const [tgtFrom, setTgtFrom] = useState(monthStart());
  const [tgtTo, setTgtTo] = useState(today());

  const valid = !!employeeId && reason.trim() !== "" && (parseFloat(amount) || 0) > 0 && srcTo >= srcFrom && tgtTo >= tgtFrom;

  return (
    <Drawer
      title="New Arrear"
      description="A backdated adjustment, paid in a future run"
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
                  employee_id: employeeId, reason: reason.trim(), amount: parseFloat(amount),
                  is_taxable: taxable,
                  source_period_start: srcFrom, source_period_end: srcTo,
                  target_period_start: tgtFrom, target_period_end: tgtTo,
                },
                { onSuccess: onClose },
              )
            }
          >
            Create Arrear
          </SaveButton>
        </>
      }
    >
      <Field label="Employee" required>
        <EmployeeSelect value={employeeId} onChange={(id) => setEmployeeId(id)} />
      </Field>
      <Field label="Reason" required hint="Appears on the payslip line, so write it for the employee.">
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="January increment applied late" />
      </Field>
      <Field label="Amount" required>
        <Input type="number" min={0} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
      </Field>

      <div className="rounded-lg border border-[hsl(var(--border))] p-3">
        <p className="mb-2 text-xs font-semibold">Period this corrects</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="From"><Input type="date" value={srcFrom} onChange={(e) => setSrcFrom(e.target.value)} /></Field>
          <Field label="To"><Input type="date" min={srcFrom} value={srcTo} onChange={(e) => setSrcTo(e.target.value)} /></Field>
        </div>
      </div>

      <div className="rounded-lg border border-[hsl(var(--border))] p-3">
        <p className="mb-2 text-xs font-semibold">Period it gets paid in</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="From"><Input type="date" value={tgtFrom} onChange={(e) => setTgtFrom(e.target.value)} /></Field>
          <Field label="To"><Input type="date" min={tgtFrom} value={tgtTo} onChange={(e) => setTgtTo(e.target.value)} /></Field>
        </div>
      </div>

      <Checkbox checked={taxable} onChange={setTaxable} label="Taxable" />
    </Drawer>
  );
}

// ── Commissions ───────────────────────────────────────────────────────────

/**
 * Commissions have no list endpoint on the backend — only create and
 * approve. Rather than invent a table that can't be populated, this tab
 * says so plainly and offers the one action that does exist.
 */
function CommissionsTab() {
  return (
    <Card>
      <EmptyState
        icon={TrendingUp}
        title="Commissions are recorded, not browsed"
        description="The API exposes recording a commission against a tiered plan and approving it, but has no endpoint that lists them. Recorded commissions show up on the payslip of the run covering their target period. Use Record Commission above to add one."
      />
    </Card>
  );
}

function CommissionDrawer({ onClose }: { onClose: () => void }) {
  const create = useCreateCommission();
  const [employeeId, setEmployeeId] = useState("");
  const [planId, setPlanId] = useState("");
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const [sales, setSales] = useState("");

  const valid = !!employeeId && (parseFloat(sales) || 0) >= 0 && to >= from;

  return (
    <Drawer
      title="Record Commission"
      description="The amount is computed server-side from the plan's tiers"
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
                  employee_id: employeeId, plan_id: planId.trim() || null,
                  target_period_start: from, target_period_end: to,
                  sales_amount: parseFloat(sales) || 0,
                },
                { onSuccess: onClose },
              )
            }
          >
            Record
          </SaveButton>
        </>
      }
    >
      <Field label="Employee" required>
        <EmployeeSelect value={employeeId} onChange={(id) => setEmployeeId(id)} />
      </Field>
      <Field label="Sales amount" required hint="The figure the tiers are applied to, not the commission itself.">
        <Input type="number" min={0} value={sales} onChange={(e) => setSales(e.target.value)} placeholder="0.00" />
      </Field>
      <Field
        label="Commission plan ID"
        hint="Leave blank to record the sale with a zero commission — without a plan there are no tiers to apply. There is no endpoint that lists plans, so this is an ID for now."
      >
        <Input value={planId} onChange={(e) => setPlanId(e.target.value)} placeholder="UUID of a commission plan" className="font-mono text-xs" />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Period start" required><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="Period end" required><Input type="date" min={from} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
      </div>
      <p className="text-[11px] text-[hsl(var(--foreground-muted))]">
        Tiers are marginal, like tax brackets — a sale spanning two tiers is charged at each tier&apos;s rate for the
        portion that falls inside it, not at one rate for the whole amount.
      </p>
    </Drawer>
  );
}

// ── Reimbursements ────────────────────────────────────────────────────────
function ReimbursementsTab({ query }: { query: ReturnType<typeof useReimbursements> }) {
  const nameOf = useEmployeeNames();
  const approve = useApproveReimbursement();
  const reject = useRejectReimbursement();

  return (
    <TabShell
      query={query}
      icon={Receipt}
      title="No reimbursement claims"
      body="Claims are submitted against a category, approved or rejected, then folded into the next payroll run."
    >
      {(items) =>
        items.map((r) => {
          const emp = nameOf(r.employee_id);
          const decidable = r.status === "submitted" || r.status === "reviewed";
          return (
            <Row
              key={r.id}
              name={emp.name}
              code={emp.code}
              primary={<>{fmtMoney(r.amount)} — {humanize(r.category)}</>}
              meta={
                r.status === "rejected" && r.rejection_reason
                  ? `Rejected: ${r.rejection_reason}`
                  : `${r.description ?? "No description"} · submitted ${fmtDate(r.submitted_at)}`
              }
              status={r.status}
              actions={
                <>
                  <IconAction
                    title={decidable ? "Approve claim" : `Cannot approve a ${humanize(r.status).toLowerCase()} claim`}
                    tone="success"
                    disabled={!decidable || approve.isPending}
                    onClick={() => approve.mutate(r.id)}
                  >
                    <Check size={15} />
                  </IconAction>
                  <IconAction
                    title={decidable ? "Reject claim" : `Cannot reject a ${humanize(r.status).toLowerCase()} claim`}
                    tone="danger"
                    disabled={!decidable || reject.isPending}
                    onClick={() => {
                      // The reason is stored and shown back to the
                      // employee, so it must not be optional.
                      const reason = window.prompt("Why is this claim being rejected? The employee will see this.");
                      if (reason?.trim()) reject.mutate({ id: r.id, reason: reason.trim() });
                    }}
                  >
                    <X size={15} />
                  </IconAction>
                </>
              }
            />
          );
        })
      }
    </TabShell>
  );
}

function ReimbursementDrawer({ onClose }: { onClose: () => void }) {
  const create = useCreateReimbursement();
  const [employeeId, setEmployeeId] = useState("");
  const [category, setCategory] = useState<ReimbursementCategory>("travel");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [receiptUrl, setReceiptUrl] = useState("");
  const [taxable, setTaxable] = useState(false);

  const valid = !!employeeId && (parseFloat(amount) || 0) > 0;

  return (
    <Drawer
      title="New Reimbursement Claim"
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
                  employee_id: employeeId, category, amount: parseFloat(amount),
                  description: description || null, receipt_url: receiptUrl || null, is_taxable: taxable,
                },
                { onSuccess: onClose },
              )
            }
          >
            Submit Claim
          </SaveButton>
        </>
      }
    >
      <Field label="Employee" required>
        <EmployeeSelect value={employeeId} onChange={(id) => setEmployeeId(id)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Category">
          <Select value={category} onChange={(e) => setCategory(e.target.value as ReimbursementCategory)}>
            {REIMBURSEMENT_CATEGORIES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
          </Select>
        </Field>
        <Field label="Amount" required>
          <Input type="number" min={0} value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
        </Field>
      </div>
      <Field label="Description">
        <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Client visit to Lahore, 3 nights" />
      </Field>
      <Field label="Receipt URL" hint="A link to the receipt wherever it is already stored.">
        <Input value={receiptUrl} onChange={(e) => setReceiptUrl(e.target.value)} placeholder="https://…" />
      </Field>
      <Checkbox checked={taxable} onChange={setTaxable} label="Taxable (most reimbursements are not)" />
    </Drawer>
  );
}
