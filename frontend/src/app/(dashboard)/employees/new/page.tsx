"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { EmployeeDrawer } from "@/components/organisms/EmployeeDrawer";

/**
 * Add Employee as a real page (dashboard quick action → /employees/new).
 * Same form as the drawer on the Employees list — it is rendered with
 * `variant="page"`, so there is one form to maintain, not two.
 */
export default function NewEmployeePage() {
  const router = useRouter();
  return (
    <div className="space-y-4">
      <Link
        href="/employees"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
      >
        <ArrowLeft size={14} /> Employees
      </Link>
      <EmployeeDrawer open variant="page" onClose={() => router.push("/employees")} />
    </div>
  );
}
