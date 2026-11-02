"use client";

import { use } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft, Mail, Phone, MapPin, Calendar, Briefcase,
  Edit, UserX, Building2, Clock, CreditCard, Shield,
  GraduationCap, Wallet, Award, Users,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import apiClient from "@/services/api-client";
import { Badge, Button, Card, Skeleton, Tabs } from "@/components/atoms";
import { resolveMediaUrl } from "@/utils/media";
import { useAuthStore } from "@/store/auth.store";
import { RecentAttendanceCard } from "@/components/attendance/RecentAttendanceCard";
import { OffboardDialog } from "@/components/employee/OffboardDialog";
import { StatusTimeline } from "@/components/employee/StatusTimeline";
import { ContractsPanel } from "@/components/employee/ContractsPanel";

const statusConfig: Record<string, { label: string; variant: "success" | "warning" | "error" | "info" | "default" }> = {
  regular:       { label: "Regular",       variant: "success" },
  active:        { label: "Active",        variant: "success" },
  probation:     { label: "Probation",     variant: "info" },
  on_leave:      { label: "On Leave",      variant: "warning" },
  notice_period: { label: "Notice Period", variant: "warning" },
  terminated:    { label: "Terminated",    variant: "error" },
  resigned:      { label: "Resigned",      variant: "error" },
};

const PROFILE_TABS = [
  { id: "personal" as const, label: "Personal" },
  { id: "employment" as const, label: "Employment" },
  { id: "compensation" as const, label: "Compensation" },
  { id: "background" as const, label: "Background" },
  { id: "emergency" as const, label: "Emergency" },
  { id: "contract" as const, label: "Contract" },
];
type ProfileTab = (typeof PROFILE_TABS)[number]["id"];

function InfoRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex justify-between py-2.5 border-b border-[hsl(var(--border))] last:border-0">
      <span className="text-xs text-[hsl(var(--foreground-muted))]">{label}</span>
      <span className="text-sm font-medium text-right">{value || "—"}</span>
    </div>
  );
}

type Json = Record<string, string | undefined | null>;

function formatAddress(a?: Json | null): string | null {
  if (!a) return null;
  const parts = [a.street, a.city, a.state, a.postal_code, a.country].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}

function payItemValue(i: Record<string, string>, currency: string): string {
  return i.calculation === "percent_of_basic"
    ? `${Number(i.percentage)}% of basic`
    : `${currency} ${Number(i.amount).toLocaleString()}`;
}

function SectionCard({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children: React.ReactNode }) {
  return (
    <Card padding={false}>
      <div className="flex items-center gap-2 border-b border-[hsl(var(--border))] px-5 py-4">
        <Icon size={15} className="text-[hsl(var(--foreground-subtle))]" />
        <h3 className="font-heading text-sm font-semibold">{title}</h3>
      </div>
      {children}
    </Card>
  );
}

export default function EmployeeDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [tab, setTab] = useState<ProfileTab>("personal");
  const canSeeAttendance = useAuthStore((s) => s.hasPermission)("attendance.view");
  const canOffboard = useAuthStore((s) => s.hasPermission)("employees.delete");
  const canManageContracts = useAuthStore((s) => s.hasPermission)("employees.update");
  const [offboardOpen, setOffboardOpen] = useState(false);
  // Reminder notifications link here with ?tab=contract.
  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    if (wanted && PROFILE_TABS.some((t) => t.id === wanted)) setTab(wanted as ProfileTab);
  }, []);

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

  const displayStatus = employee.job_nature === "permanent"
    ? "permanent"
    : employee.employment_status;
  const status = statusConfig[displayStatus] ?? { label: displayStatus, variant: "default" as const };
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
          {canOffboard && !["resigned", "terminated"].includes(employee.employment_status) && (
            <Button variant="outline" icon={<UserX size={14} />} onClick={() => setOffboardOpen(true)}>
              Offboard
            </Button>
          )}
          <Button icon={<Edit size={14} />} onClick={() => router.push(`/employees/${id}/edit`)}>
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
              <div className="flex h-20 w-20 items-center justify-center overflow-hidden rounded-full bg-[hsl(var(--primary))] text-2xl font-bold text-[hsl(var(--primary-foreground))]">
                {employee.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={resolveMediaUrl(employee.avatar_url) ?? undefined}
                    alt={`${employee.first_name} ${employee.last_name}`}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  initials
                )}
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

        <div className="col-span-2 space-y-4">
          <Tabs tabs={PROFILE_TABS} active={tab} onChange={setTab} />
          {tab === "personal" && (
            <div className="space-y-4" data-testid="tab-personal">
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
          {/* Family & addresses */}
          <SectionCard icon={Building2} title="Family, Address & ID">
            <div className="px-5 py-2">
              <InfoRow label="Marital Status" value={employee.marital_status ? employee.marital_status.replace(/\b\w/g, (c: string) => c.toUpperCase()) : null} />
              <InfoRow label="Father's Name" value={employee.father_name} />
              <InfoRow label="Mother's Name" value={employee.mother_name} />
              <InfoRow label="Spouse Name" value={employee.spouse_name} />
              <InfoRow label="Current Address" value={formatAddress(employee.address)} />
              <InfoRow label="Permanent Address" value={formatAddress(employee.permanent_address)} />
              <InfoRow label="CNIC / National ID" value={employee.national_id} />
              <InfoRow label="Driving Licence" value={employee.driving_license_number
                ? `${employee.driving_license_number}${employee.driving_license_expiry ? ` (expires ${employee.driving_license_expiry})` : ""}`
                : null} />
              <InfoRow label="Passport" value={employee.passport_number
                ? `${employee.passport_number}${employee.passport_expiry ? ` (expires ${employee.passport_expiry})` : ""}`
                : null} />
              <InfoRow label="ID Type" value={employee.national_id_type ? String(employee.national_id_type).toUpperCase() : null} />
              <InfoRow label="Tax Number" value={employee.tax_number} />
              <InfoRow label="EOBI / Social Security" value={employee.social_security_number} />
              <InfoRow label="Provident Fund" value={employee.provident_fund_number} />
              <InfoRow label="Visa / Work Permit" value={employee.visa_number
                ? `${employee.visa_number}${employee.visa_expiry ? ` (expires ${employee.visa_expiry})` : ""}`
                : null} />
              <InfoRow label="Religion" value={employee.religion} />
              <InfoRow label="Place of Birth" value={employee.place_of_birth} />
              <InfoRow label="Home Phone" value={employee.home_phone} />
              <InfoRow label="Previous Employee ID" value={employee.previous_employee_id} />
              <InfoRow label="Heard About Us Via" value={employee.referral_source} />
              <InfoRow label="Hobbies" value={employee.hobbies} />
              {Object.entries((employee.social_links ?? {}) as Record<string, string>)
                .filter(([, v]) => v)
                .map(([k, v]) => (
                  <InfoRow key={k} label={k.charAt(0).toUpperCase() + k.slice(1)} value={v} />
                ))}
            </div>
          </SectionCard>
          {/* Dependents */}
          {Array.isArray(employee.dependents) && employee.dependents.length > 0 && (
            <SectionCard icon={Users} title="Dependents">
              <div className="px-5 py-2" data-testid="dependents">
                {employee.dependents.map((d: Record<string, string>, idx: number) => (
                  <InfoRow
                    key={idx}
                    label={`${d.name ?? ""}${d.relationship ? ` (${d.relationship})` : ""}`}
                    value={d.date_of_birth ? `Born ${d.date_of_birth}` : null}
                  />
                ))}
              </div>
            </SectionCard>
          )}
            </div>
          )}
          {tab === "employment" && (
            <div className="space-y-4" data-testid="tab-employment">
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
              <InfoRow label="Reports To" value={employee.manager_name} />
              <InfoRow label="Probation Ends" value={employee.probation_end_date} />
              <InfoRow label="Confirmation Date" value={employee.date_of_confirmation} />
              <InfoRow label="Notice Period" value={employee.notice_period_days ? `${employee.notice_period_days} days` : null} />
            </div>
          </Card>
          {canSeeAttendance && <RecentAttendanceCard employeeId={id} />}
          <StatusTimeline employeeId={id} />
            </div>
          )}
          {tab === "compensation" && (
            <div className="space-y-4" data-testid="tab-compensation">
              {!(employee.compensation_items?.length || employee.bank_name || employee.bank_account_number || employee.bank_iban || employee.health_insurance_provider) && (
                <Card><p className="text-sm text-[hsl(var(--foreground-muted))]">No allowances, deductions or bank details on file.</p></Card>
              )}
          {/* Allowances & deductions — only sent to people allowed to edit */}
          {Array.isArray(employee.compensation_items) && employee.compensation_items.length > 0 && (
            <SectionCard icon={Wallet} title="Allowances & Deductions">
              <div className="px-5 py-2" data-testid="pay-items">
                {employee.compensation_items.map((i: Record<string, string>) => (
                  <div key={i.id} className="flex items-center justify-between border-b border-[hsl(var(--border))] py-2.5 last:border-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{i.name}</span>
                      <Badge variant={i.kind === "deduction" ? "error" : "success"}>
                        {i.kind === "deduction" ? "Deduction" : "Allowance"}
                      </Badge>
                    </div>
                    <span className="text-sm font-medium">
                      {i.kind === "deduction" ? "− " : "+ "}
                      {payItemValue(i, employee.currency)}
                    </span>
                  </div>
                ))}
              </div>
            </SectionCard>
          )}
          {(employee.bank_name || employee.bank_account_number || employee.bank_iban || employee.health_insurance_provider) && (
            <SectionCard icon={CreditCard} title="Bank & Insurance">
              <div className="px-5 py-2">
                <InfoRow label="Bank" value={employee.bank_name} />
                <InfoRow label="Account Title" value={employee.bank_account_title} />
                <InfoRow label="Account Number" value={employee.bank_account_number} />
                <InfoRow label="IBAN" value={employee.bank_iban} />
                <InfoRow label="Health Insurance" value={employee.health_insurance_provider} />
                <InfoRow label="Policy Number" value={employee.health_insurance_number} />
              </div>
            </SectionCard>
          )}
            </div>
          )}
          {tab === "background" && (
            <div className="space-y-4" data-testid="tab-background">
              {!(employee.education?.length || employee.work_experience?.length || employee.skills?.length || employee.languages?.length || employee.certifications?.length) && (
                <Card><p className="text-sm text-[hsl(var(--foreground-muted))]">No education, skills or experience added yet.</p></Card>
              )}
          {/* Education & experience */}
          {((employee.education?.length ?? 0) > 0 || (employee.work_experience?.length ?? 0) > 0) && (
            <SectionCard icon={GraduationCap} title="Education & Experience">
              <div className="px-5 py-2">
                {(employee.education ?? []).map((e: Record<string, string>, idx: number) => (
                  <InfoRow
                    key={`edu-${idx}`}
                    label={e.degree ?? ""}
                    value={[e.institute, e.year, e.grade && `Grade ${e.grade}`].filter(Boolean).join(" · ") || null}
                  />
                ))}
                {(employee.work_experience ?? []).map((w: Record<string, string>, idx: number) => (
                  <InfoRow
                    key={`exp-${idx}`}
                    label={w.company ?? ""}
                    value={[w.designation, [w.from_date, w.to_date].filter(Boolean).join(" → ")].filter(Boolean).join(" · ") || null}
                  />
                ))}
              </div>
            </SectionCard>
          )}
          {/* Skills, languages, certifications */}
          {((employee.skills?.length ?? 0) > 0 || (employee.languages?.length ?? 0) > 0 || (employee.certifications?.length ?? 0) > 0) && (
            <SectionCard icon={Award} title="Skills, Languages & Certifications">
              <div className="px-5 py-2" data-testid="skills">
                {(employee.skills ?? []).map((k: Record<string, string>, idx: number) => (
                  <InfoRow key={`skill-${idx}`} label={`Skill: ${k.name ?? ""}`} value={k.level} />
                ))}
                {(employee.languages ?? []).map((l: Record<string, string>, idx: number) => (
                  <InfoRow key={`lang-${idx}`} label={`Language: ${l.name ?? ""}`} value={l.fluency} />
                ))}
                {(employee.certifications ?? []).map((c: Record<string, string>, idx: number) => (
                  <InfoRow
                    key={`cert-${idx}`}
                    label={c.name ?? ""}
                    value={[c.issued_by, c.expiry_date && `expires ${c.expiry_date}`].filter(Boolean).join(" · ") || null}
                  />
                ))}
              </div>
            </SectionCard>
          )}
            </div>
          )}
          {tab === "contract" && <ContractsPanel employeeId={id} canManage={canManageContracts} />}
          {tab === "emergency" && (
            <div className="space-y-4" data-testid="tab-emergency">
              {!employee.emergency_contacts?.length && (
                <Card><p className="text-sm text-[hsl(var(--foreground-muted))]">No emergency contacts added yet.</p></Card>
              )}
          {/* Emergency contacts — any number */}
          {Array.isArray(employee.emergency_contacts) && employee.emergency_contacts.length > 0 && (
            <SectionCard icon={Phone} title="Emergency Contacts">
              <div className="px-5 py-2" data-testid="emergency-contacts">
                {employee.emergency_contacts.map((c: Record<string, string>, idx: number) => (
                  <InfoRow
                    key={idx}
                    label={`${c.name}${c.relationship ? ` (${c.relationship})` : ""}`}
                    value={[c.phone, c.email].filter(Boolean).join(" · ") || null}
                  />
                ))}
              </div>
            </SectionCard>
          )}
            </div>
          )}
        </div>
      </div>

      <OffboardDialog
        employeeId={id}
        employeeName={`${employee.first_name} ${employee.last_name}`.trim()}
        open={offboardOpen}
        onClose={() => setOffboardOpen(false)}
      />
    </div>
  );
}
