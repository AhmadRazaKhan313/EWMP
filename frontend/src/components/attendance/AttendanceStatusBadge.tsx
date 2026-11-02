import { Badge } from "@/components/atoms";

/**
 * One place that decides how an attendance status looks, so "Absent" is the
 * same red everywhere (attendance list, employee profile, ...). Absent is a
 * filled red pill built from the destructive design token; everything else
 * keeps the standard Badge.
 */
export type AttendanceStatusValue = string;

const CONFIG: Record<string, { label: string; variant: "success" | "warning" | "error" | "default" | "info" }> = {
  present:        { label: "Present",        variant: "success" },
  late:           { label: "Late",           variant: "warning" },
  half_day:       { label: "Half Day",       variant: "warning" },
  work_from_home: { label: "WFH",            variant: "info" },
  missed_punch:   { label: "Missed punch",   variant: "warning" },
  absent:         { label: "Absent",         variant: "error" },
  on_leave:       { label: "On Leave",       variant: "info" },
  holiday:        { label: "Holiday",        variant: "default" },
  weekend:        { label: "Weekly off",     variant: "default" },
  weekly_off:     { label: "Weekly off",     variant: "default" },
  not_checked_in: { label: "Not checked in", variant: "warning" },
  scheduled:      { label: "Scheduled",      variant: "default" },
};

export function AttendanceStatusBadge({ status }: { status: AttendanceStatusValue }) {
  if (status === "absent") {
    return (
      <span
        data-testid="absent-badge"
        className="inline-flex items-center rounded-md border border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.12)] px-1.5 py-0.5 text-xs font-semibold text-[hsl(var(--destructive))]"
      >
        Absent
      </span>
    );
  }
  const cfg = CONFIG[status] ?? { label: status.replace(/_/g, " "), variant: "default" as const };
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
}
