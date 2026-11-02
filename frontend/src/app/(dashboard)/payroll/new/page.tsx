"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { NewPayrollRunDrawer } from "../NewPayrollRunDrawer";

/** New payroll run as a page (dashboard quick action → /payroll/new). */
export default function NewPayrollRunPage() {
  const router = useRouter();
  return (
    <div className="space-y-4">
      <Link href="/payroll" className="inline-flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"><ArrowLeft size={14} /> Payroll</Link>
      <NewPayrollRunDrawer variant="page" onClose={() => router.push("/payroll")} />
    </div>
  );
}
