"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { EmployeeDrawer } from "@/components/organisms/EmployeeDrawer";

/**
 * Edit Employee as a real page (`/employees/[id]/edit`) — the same form as
 * Add (`/employees/new`), prefilled. Saving or closing returns to the profile.
 */
export default function EditEmployeePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  return (
    <div className="space-y-4">
      <Link
        href={`/employees/${id}`}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
      >
        <ArrowLeft size={14} /> Back to profile
      </Link>
      <EmployeeDrawer open variant="page" employeeId={id} onClose={() => router.push(`/employees/${id}`)} />
    </div>
  );
}
