"use client";

import { useState } from "react";
import { Lock } from "lucide-react";
import { PageHeader, Tabs } from "@/components/atoms";
import { useAuthStore } from "@/store/auth.store";
import { useFinSummary } from "@/services/finance.service";
import { ClosePanel } from "./ClosePanel";
import { OpeningPanel } from "./OpeningPanel";

type Tab = "close" | "opening";

export default function ClosePage() {
  const canManage = useAuthStore((s) => s.hasPermission("finance.manage"));
  const currency = useFinSummary().data?.currency ?? "PKR";
  const [tab, setTab] = useState<Tab>("close");
  return (
    <div className="space-y-6">
      <PageHeader title="Close books" action={<Lock size={18} aria-hidden className="text-[hsl(var(--foreground-muted))]" />} />
      <Tabs<Tab> active={tab} onChange={setTab} tabs={[{ value: "close", label: "Month / year close" }, { value: "opening", label: "Opening balances" }]} />
      {tab === "close" ? <ClosePanel currency={currency} canManage={canManage} /> : <OpeningPanel currency={currency} canManage={canManage} />}
    </div>
  );
}
