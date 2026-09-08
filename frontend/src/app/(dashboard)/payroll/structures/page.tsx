"use client";

import { useState } from "react";
import { Plus, Layers } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "@/services/api-client";
import { Badge, Button, Card, EmptyState, PageHeader } from "@/components/atoms";
import { PayrollNav } from "../PayrollNav";
import { SalaryStructureDrawer } from "./SalaryStructureDrawer";

interface StructureComponent {
  id: string; name: string; code: string; component_type: string; calculation_type: string;
  amount: string | null; percentage: string | null; is_taxable: boolean; display_order: number;
}

interface SalaryStructure {
  id: string; name: string; code: string; description: string | null; currency: string;
  is_active: boolean; is_default: boolean; version: number; components: StructureComponent[];
}

const calcLabel: Record<string, string> = {
  fixed: "Fixed amount",
  percentage_of_basic: "% of Basic",
  percentage_of_gross: "% of Gross",
  formula: "Formula",
};

function ComponentSummary({ c }: { c: StructureComponent }) {
  if (c.calculation_type === "fixed") return <span>{c.amount}</span>;
  if (c.calculation_type === "percentage_of_basic") return <span>{c.percentage}% of Basic</span>;
  if (c.calculation_type === "percentage_of_gross") return <span>{c.percentage}% of Gross</span>;
  return <span className="font-mono text-[11px]">{calcLabel[c.calculation_type]}</span>;
}

export default function SalaryStructuresPage() {
  const [showCreate, setShowCreate] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["salary-structures"],
    queryFn: async () => (await apiClient.get<{ items: SalaryStructure[]; total: number }>("/payroll/salary-structures")).data,
  });

  const structures = data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payroll"
        description="Manage salary processing, payslips, and compensation."
        action={<Button icon={<Plus size={15} />} onClick={() => setShowCreate(true)}>New Structure</Button>}
      />
      <PayrollNav />

      {isLoading ? (
        <p className="text-sm text-[hsl(var(--foreground-muted))]">Loading…</p>
      ) : structures.length === 0 ? (
        <Card>
          <EmptyState
            icon={Layers}
            title="No salary structures yet"
            description="Create a structure to define how basic, allowances, and deductions combine into a salary."
            action={<Button icon={<Plus size={14} />} onClick={() => setShowCreate(true)}>New Structure</Button>}
          />
        </Card>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {structures.map((s) => (
            <Card key={s.id}>
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-heading text-sm font-semibold">{s.name}</h3>
                    {s.is_default && <Badge variant="info">Default</Badge>}
                    <span className="text-[11px] text-[hsl(var(--foreground-muted))]">v{s.version}</span>
                  </div>
                  <p className="text-xs text-[hsl(var(--foreground-muted))]">{s.code} · {s.currency}</p>
                </div>
              </div>
              {s.description && <p className="mt-2 text-xs text-[hsl(var(--foreground-subtle))]">{s.description}</p>}

              <div className="mt-3 space-y-1 border-t border-[hsl(var(--border))] pt-3">
                {s.components.map((c) => (
                  <div key={c.id} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-1.5">
                      {c.name}
                      {c.component_type === "deduction" && <span className="text-[10px] text-[hsl(var(--destructive))]">(deduction)</span>}
                    </span>
                    <span className="font-mono text-xs text-[hsl(var(--foreground-muted))]"><ComponentSummary c={c} /></span>
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}

      {showCreate && <SalaryStructureDrawer onClose={() => setShowCreate(false)} />}
    </div>
  );
}
