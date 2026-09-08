"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft, Mail, Phone, MapPin, Calendar, Briefcase,
  Edit, UserX, Building2, Clock, CreditCard, Shield,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import apiClient from "@/services/api-client";
import { Badge, Button, Card, Skeleton } from "@/components/atoms";
import { EmployeeDrawer } from "@/components/organisms/EmployeeDrawer";

const statusConfig: Record<string, { label: string; variant: "success" | "warning" | "error" | "info" | "default" }> = {
  active:        { label: "Active",        variant: "success" },
  probation:     { label: "Probation",     variant: "info" },
  on_leave:      { label: "On Leave",      variant: "warning" },
  notice_period: { label: "Notice Period", variant: "warning" },
  terminated:    { label: "Terminated",    variant: "error" },
  resigned:      { label: "Resigned",      variant: "error" },
};

function InfoRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex justify-between py-2.5 border-b border-[hsl(var(--border))] last:border-0">
      <span className="text-xs text-[hsl(var(--foreground-muted))]">{label}</span>
      <span className="text-sm font-medium text-right">{value || "—"}</span>
    </div>
  );
}

export default function EmployeeDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [editOpen, setEditOpen] = useState(false);

  const { data: employee, isLoading } = useQuery({
    queryKey: ["employee", id],
    queryFn: async () => {
      const { data } = await apiClient.get(`/employees/${id}`);
      return data;
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-48" />
        <div className="grid grid-cols-3 gap-6">
          <Skeleton className="h-64 rounded-xl" />
          <div className="col-span-2 space-y-4">
            <Skeleton className="h-40 rounded-xl" />
            <Skeleton className="h-40 rounded-xl" />
          </div>
        </div>
      </div>
    );
  }

  if (!employee) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <p className="text-[hsl(var(--foreground-muted))]">Employee not found</p>
        <Button variant="outline" onClick={() => router.back()} className="mt-4">
          Go Back
        </Button>
      </div>
    );
  }

  const status = statusConfig[employee.employment_status] ?? { label: employee.employment_status, variant: "default" as const };
  const initials = `${(employee.first_name || "")[0] ?? ""}${(employee.last_name || "")[0] ?? ""}`.toUpperCase();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.back()}
            className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] transition-colors"
          >
            <ArrowLeft size={16} />
          </button>
          <div>
            <h1 className="font-heading text-xl font-semibold">
              {employee.first_name} {employee.last_name}
            </h1>
            <p className="text-sm text-[hsl(var(--foreground-muted))]">
              {employee.employee_code}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" icon={<UserX size={14} />} onClick={() => {}}>
            Offboard
          </Button>
          <Button icon={<Edit size={14} />} onClick={() => setEditOpen(true)}>
            Edit Profile
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Left — Profile card */}
        <div className="space-y-4">
          <Card>
            <div className="flex flex-col items-center text-center">
              {/* Avatar */}
              <div className="flex h-20 w-20 items-center justify-center rounded-full bg-[hsl(var(--primary))] text-2xl font-bold text-[hsl(var(--primary-foreground))]">
                {initials}
              </div>
              <h2 className="mt-3 font-heading text-base font-semibold">
                {employee.first_name} {employee.last_name}
              </h2>
              <p className="text-sm text-[hsl(var(--foreground-muted))]">
                {employee.designation_id || "No designation"}
              </p>
              <div className="mt-2">
                <Badge variant={status.variant}>{status.label}</Badge>
              </div>
            </div>

            <div className="mt-5 space-y-2.5">
              {employee.email && (
                <div className="flex items-center gap-2.5 text-sm text-[hsl(var(--foreground-subtle))]">
                  <Mail size={14} className="shrink-0" />
                  <span className="truncate">{employee.email}</span>
                </div>
              )}
              {employee.work_phone && (
                <div className="flex items-center gap-2.5 text-sm text-[hsl(var(--foreground-subtle))]">
                  <Phone size={14} className="shrink-0" />
                  <span>{employee.work_phone}</span>
                </div>
              )}
              {employee.work_location && (
                <div className="flex items-center gap-2.5 text-sm text-[hsl(var(--foreground-subtle))]">
                  <MapPin size={14} className="shrink-0" />
                  <span>{employee.work_location}</span>
                </div>
              )}
              {employee.is_remote && (
                <div className="flex items-center gap-2.5 text-sm text-[hsl(var(--info))]">
                  <Shield size={14} className="shrink-0" />
                  <span>Remote Employee</span>
                </div>
              )}
            </div>
          </Card>

          {/* Quick stats */}
          <Card>
            <div className="space-y-0">
              <div className="flex items-center justify-between py-2.5 border-b border-[hsl(var(--border))]">
                <div className="flex items-center gap-2 text-xs text-[hsl(var(--foreground-muted))]">
                  <Clock size={13} /> Tenure
                </div>
                <span className="text-sm font-semibold">
                  {employee.years_of_service < 1
                    ? `${Math.round(employee.years_of_service * 12)} months`
                    : `${employee.years_of_service} years`}
                </span>
              </div>
              <div className="flex items-center justify-between py-2.5 border-b border-[hsl(var(--border))]">
                <div className="flex items-center gap-2 text-xs text-[hsl(var(--foreground-muted))]">
                  <Briefcase size={13} /> Type
                </div>
                <span className="text-sm font-medium capitalize">
                  {(employee.employment_type || "").replace("_", " ")}
                </span>
              </div>
              {employee.current_salary && (
                <div className="flex items-center justify-between py-2.5">
                  <div className="flex items-center gap-2 text-xs text-[hsl(var(--foreground-muted))]">
                    <CreditCard size={13} /> Salary
                  </div>
                  <span className="text-sm font-medium">
                    {employee.currency} {parseFloat(employee.current_salary).toLocaleString()}
                  </span>
                </div>
              )}
            </div>
          </Card>
        </div>

        {/* Right — Details */}
        <div className="col-span-2 space-y-4">
          {/* Employment info */}
          <Card padding={false}>
            <div className="flex items-center gap-2 border-b border-[hsl(var(--border))] px-5 py-4">
              <Briefcase size={15} className="text-[hsl(var(--foreground-subtle))]" />
              <h3 className="font-heading text-sm font-semibold">Employment Information</h3>
            </div>
            <div className="px-5 py-2">
              <InfoRow label="Employee Code" value={employee.employee_code} />
              <InfoRow label="Date of Joining" value={employee.date_of_joining
                ? new Date(employee.date_of_joining).toLocaleDateString("en-US", { day: "numeric", month: "long", year: "numeric" })
                : null} />
              <InfoRow label="Employment Status" value={status.label} />
              <InfoRow label="Employment Type" value={(employee.employment_type || "").replace("_", " ").replace(/\b\w/g, (c: string) => c.toUpperCase())} />
              <InfoRow label="Department" value={employee.department_id || null} />
              <InfoRow label="Notice Period" value={employee.notice_period_days ? `${employee.notice_period_days} days` : null} />
            </div>
          </Card>

          {/* Personal info */}
          <Card padding={false}>
            <div className="flex items-center gap-2 border-b border-[hsl(var(--border))] px-5 py-4">
              <Shield size={15} className="text-[hsl(var(--foreground-subtle))]" />
              <h3 className="font-heading text-sm font-semibold">Personal Information</h3>
            </div>
            <div className="px-5 py-2">
              <InfoRow label="Date of Birth" value={employee.date_of_birth
                ? new Date(employee.date_of_birth).toLocaleDateString("en-US", { day: "numeric", month: "long", year: "numeric" })
                : null} />
              <InfoRow label="Gender" value={employee.gender ? employee.gender.replace("_", " ").replace(/\b\w/g, (c: string) => c.toUpperCase()) : null} />
              <InfoRow label="Nationality" value={employee.nationality} />
              <InfoRow label="Blood Group" value={employee.blood_group} />
              <InfoRow label="Personal Email" value={employee.personal_email} />
              <InfoRow label="Personal Phone" value={employee.personal_phone} />
            </div>
          </Card>

          {/* Emergency contact */}
          {employee.emergency_contact && (
            <Card padding={false}>
              <div className="flex items-center gap-2 border-b border-[hsl(var(--border))] px-5 py-4">
                <Phone size={15} className="text-[hsl(var(--foreground-subtle))]" />
                <h3 className="font-heading text-sm font-semibold">Emergency Contact</h3>
              </div>
              <div className="px-5 py-2">
                <InfoRow label="Name" value={employee.emergency_contact?.name} />
                <InfoRow label="Phone" value={employee.emergency_contact?.phone} />
                <InfoRow label="Relationship" value={employee.emergency_contact?.relationship} />
              </div>
            </Card>
          )}
        </div>
      </div>

      {/* Edit Drawer */}
      <EmployeeDrawer
        open={editOpen}
        onClose={() => setEditOpen(false)}
        employeeId={id}
      />
    </div>
  );
}
