"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { ApplyLeaveModal } from "../ApplyLeaveModal";

/** Apply for Leave as a page (dashboard quick action → /leave/new). */
export default function NewLeavePage() {
  const router = useRouter();
  return (
    <div className="space-y-4">
      <Link href="/leave" className="inline-flex items-center gap-1.5 text-sm font-medium text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"><ArrowLeft size={14} /> Leave</Link>
      <ApplyLeaveModal open variant="page" onClose={() => router.push("/leave")} />
    </div>
  );
}
