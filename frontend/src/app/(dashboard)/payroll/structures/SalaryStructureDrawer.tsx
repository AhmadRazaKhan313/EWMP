"use client";

import { useState, useEffect } from "react";
import { X, Loader2, Plus, Trash2, CheckCircle2, AlertTriangle } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import apiClient from "@/services/api-client";
import { Button } from "@/components/atoms";
import { cn } from "@/utils/cn";

type CalcType = "fixed" | "percentage_of_basic" | "percentage_of_gross" | "formula";
type CompType = "earning" | "deduction" | "employer_contribution";

interface ComponentDraft {
  key: string;
  name: string;
  code: string;
  component_type: CompType;
  calculation_type: CalcType;
  amount: string;
  percentage: string;
  formula: string;
  is_taxable: boolean;
}

function Label({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="block text-xs font-medium text-[hsl(var(--foreground-subtle))] mb-1">
      {children} {required && <span className="text-[hsl(var(--destructive))]">*</span>}
    </label>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        "w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1.5 text-sm outline-none",
        "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1 hover:border-[hsl(var(--border-strong))]",
        props.className,
      )}
    />
  );
}

function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1"
    />
  );
}

function newComponent(component_type: CompType): ComponentDraft {
  return {
    key: crypto.randomUUID(), name: "", code: "", component_type,
    calculation_type: "fixed", amount: "", percentage: "", formula: "", is_taxable: component_type !== "deduction",
  };
}

// Live formula validation — debounced, checked against every OTHER
// component's code plus the always-available BASIC/GROSS variables, so an
// HR admin sees "unknown code" or a syntax error before ever saving.
function FormulaField({
  value, onChange, knownCodes,
}: {
  value: string; onChange: (v: string) => void; knownCodes: string[];
}) {
  const [result, setResult] = useState<{ valid: boolean; errors: string[] } | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (!value.trim()) { setResult(null); return; }
    setChecking(true);
    const id = setTimeout(() => {
      apiClient
        .post("/payroll/formulas/validate", { expression: value, known_codes: knownCodes })
        .then((res) => setResult(res.data))
        .catch(() => setResult(null))
        .finally(() => setChecking(false));
    }, 400);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, knownCodes.join(",")]);

  return (
    <div>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="e.g. BASIC * 0.2  or  IF(BASIC > 100000, BASIC * 0.1, BASIC * 0.05)"
        className="font-mono text-xs"
      />
      {checking && <p className="mt-1 text-[11px] text-[hsl(var(--foreground-muted))]">Checking…</p>}
      {!checking && result && (
        <p className={cn("mt-1 flex items-center gap-1 text-[11px]", result.valid ? "text-[hsl(var(--success))]" : "text-[hsl(var(--destructive))]")}>
          {result.valid ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}
          {result.valid ? "Valid formula" : result.errors.join("; ")}
        </p>
      )}
    </div>
  );
}

export function SalaryStructureDrawer({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [description, setDescription] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [isDefault, setIsDefault] = useState(false);
  const [components, setComponents] = useState<ComponentDraft[]>([
    { key: crypto.randomUUID(), name: "Basic Salary", code: "BASIC", component_type: "earning", calculation_type: "fixed", amount: "", percentage: "", formula: "", is_taxable: true },
  ]);

  const knownCodes = components.map((c) => c.code.toUpperCase()).filter(Boolean);

  function updateComponent(key: string, patch: Partial<ComponentDraft>) {
    setComponents((prev) => prev.map((c) => (c.key === key ? { ...c, ...patch } : c)));
  }

  const create = useMutation({
    mutationFn: () =>
      apiClient.post("/payroll/salary-structures", {
        name, code, description: description || null, currency, is_default: isDefault,
        components: components.map((c, i) => ({
          name: c.name, code: c.code.toUpperCase(), component_type: c.component_type,
          calculation_type: c.calculation_type,
          amount: c.calculation_type === "fixed" ? Number(c.amount || 0) : null,
          percentage: c.calculation_type.startsWith("percentage") ? Number(c.percentage || 0) : null,
          formula: c.calculation_type === "formula" ? c.formula : null,
          is_taxable: c.is_taxable, is_mandatory: false, display_order: i,
        })),
      }),
    onSuccess: () => {
      toast.success("Salary structure created");
      void qc.invalidateQueries({ queryKey: ["salary-structures"] });
      onClose();
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not create structure";
      toast.error(msg);
    },
  });

  const canSave = name.trim() && code.trim() && components.every((c) => c.name.trim() && c.code.trim());

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-2xl flex-col bg-[hsl(var(--background))] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div>
            <h2 className="font-heading text-lg font-semibold">New Salary Structure</h2>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">Define how basic, allowances, and deductions combine</p>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label required>Name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Standard" />
            </div>
            <div>
              <Label required>Code</Label>
              <Input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="STD" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Description</Label>
              <Input value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div>
              <Label>Currency</Label>
              <Input value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
            Make this the default structure for new employees
          </label>

          <div className="border-t border-[hsl(var(--border))] pt-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Components</h3>
              <div className="flex gap-1.5">
                <Button size="sm" variant="outline" icon={<Plus size={12} />} onClick={() => setComponents((p) => [...p, newComponent("earning")])}>
                  Earning
                </Button>
                <Button size="sm" variant="outline" icon={<Plus size={12} />} onClick={() => setComponents((p) => [...p, newComponent("deduction")])}>
                  Deduction
                </Button>
              </div>
            </div>

            <div className="space-y-3">
              {components.map((c) => (
                <div key={c.key} className="rounded-lg border border-[hsl(var(--border))] p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <Input value={c.name} onChange={(e) => updateComponent(c.key, { name: e.target.value })} placeholder="Component name" className="flex-1" />
                    <Input value={c.code} onChange={(e) => updateComponent(c.key, { code: e.target.value.toUpperCase() })} placeholder="CODE" className="w-28 font-mono" />
                    <button
                      onClick={() => setComponents((p) => p.filter((x) => x.key !== c.key))}
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--destructive))]/10 hover:text-[hsl(var(--destructive))]"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className={cn(
                      "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium",
                      c.component_type === "earning" ? "bg-[hsl(var(--success-subtle))] text-[hsl(var(--success))]" :
                      c.component_type === "deduction" ? "bg-[hsl(var(--destructive))]/10 text-[hsl(var(--destructive))]" :
                      "bg-[hsl(var(--info-subtle))] text-[hsl(var(--info))]",
                    )}>
                      {c.component_type.replace("_", " ")}
                    </span>
                    <Select value={c.calculation_type} onChange={(e) => updateComponent(c.key, { calculation_type: e.target.value as CalcType })} className="w-40">
                      <option value="fixed">Fixed amount</option>
                      <option value="percentage_of_basic">% of Basic</option>
                      <option value="percentage_of_gross">% of Gross</option>
                      <option value="formula">Formula</option>
                    </Select>

                    {c.calculation_type === "fixed" && (
                      <Input type="number" value={c.amount} onChange={(e) => updateComponent(c.key, { amount: e.target.value })} placeholder="0.00" className="w-32" />
                    )}
                    {(c.calculation_type === "percentage_of_basic" || c.calculation_type === "percentage_of_gross") && (
                      <Input type="number" value={c.percentage} onChange={(e) => updateComponent(c.key, { percentage: e.target.value })} placeholder="0" className="w-24" />
                    )}

                    <label className="ml-auto flex shrink-0 items-center gap-1.5 text-xs text-[hsl(var(--foreground-muted))]">
                      <input type="checkbox" checked={c.is_taxable} onChange={(e) => updateComponent(c.key, { is_taxable: e.target.checked })} />
                      Taxable
                    </label>
                  </div>

                  {c.calculation_type === "formula" && (
                    <div className="mt-2">
                      <FormulaField
                        value={c.formula}
                        onChange={(v) => updateComponent(c.key, { formula: v })}
                        knownCodes={knownCodes.filter((code) => code !== c.code.toUpperCase())}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[hsl(var(--border))] px-6 py-4">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => create.mutate()} disabled={create.isPending || !canSave}>
            {create.isPending && <Loader2 size={14} className="animate-spin" />}
            Create Structure
          </Button>
        </div>
      </div>
    </>
  );
}
