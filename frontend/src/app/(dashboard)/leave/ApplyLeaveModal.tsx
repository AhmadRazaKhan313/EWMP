"use client";

import { forwardRef, useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { X, Loader2, CalendarDays } from "lucide-react";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/utils/cn";
import apiClient from "@/services/api-client";
import { Button } from "@/components/atoms";

// ── Local field styling (matches EmployeeDrawer conventions) ───────────────
function Label({ children, required, htmlFor }: { children: React.ReactNode; required?: boolean; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="block text-xs font-medium text-[hsl(var(--foreground-subtle))] mb-1">
      {children} {required && <span className="text-[hsl(var(--destructive))]">*</span>}
    </label>
  );
}

const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement> & { error?: boolean }>(
  ({ error, className, ...props }, ref) => (
    <input
      ref={ref}
      {...props}
      className={cn(
        "w-full rounded-md border px-3 py-2 text-sm outline-none transition-colors",
        "bg-[hsl(var(--background))] placeholder:text-[hsl(var(--foreground-muted))]",
        "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
        error ? "border-[hsl(var(--destructive))]" : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
        className,
      )}
    />
  ),
);
Input.displayName = "Input";

const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement> & { error?: boolean }>(
  ({ error, children, className, ...props }, ref) => (
    <select
      ref={ref}
      {...props}
      className={cn(
        "w-full rounded-md border px-3 py-2 text-sm outline-none transition-colors",
        "bg-[hsl(var(--background))]",
        "focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1",
        error ? "border-[hsl(var(--destructive))]" : "border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))]",
        className,
      )}
    >
      {children}
    </select>
  ),
);
Select.displayName = "Select";

function ErrorText({ children }: { children?: string }) {
  if (!children) return null;
  return <p className="mt-1 text-xs text-[hsl(var(--destructive))]">{children}</p>;
}

// ── Schema — mirrors backend LeaveApplyRequest validation ───────────────────
const applySchema = z
  .object({
    leave_type_id: z.string().min(1, "Select a leave type"),
    start_date: z.string().min(1, "Required"),
    end_date: z.string().optional().default(""),
    duration_type: z.enum(["full_day", "half_day", "hourly"]),
    half_day_period: z.enum(["morning", "afternoon"]).optional(),
    hours: z.string().optional(),
    reason: z.string().optional(),
  })
  .superRefine((val, ctx) => {
    if (val.duration_type === "full_day") {
      if (!val.end_date) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["end_date"], message: "Required" });
      } else if (val.end_date < val.start_date) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["end_date"], message: "End date can't be before start date" });
      }
    }
    if (val.duration_type === "half_day" && !val.half_day_period) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["half_day_period"], message: "Pick morning or afternoon" });
    }
    if (val.duration_type === "hourly") {
      const h = Number(val.hours);
      if (!val.hours || Number.isNaN(h) || h <= 0) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["hours"], message: "Enter the number of hours" });
      }
    }
  });

type ApplyForm = z.infer<typeof applySchema>;

interface LeaveType {
  id: string;
  name: string;
  code: string;
  color: string;
  days_per_year: string;
  is_paid: boolean;
}

interface BalanceItem {
  leave_type_id: string;
  leave_type_name: string;
  remaining_days: number;
}

interface ApplyLeaveModalProps {
  open: boolean;
  onClose: () => void;
}

export function ApplyLeaveModal({ open, onClose }: ApplyLeaveModalProps) {
  const qc = useQueryClient();

  const { data: leaveTypes } = useQuery({
    queryKey: ["leave-types"],
    queryFn: async () => (await apiClient.get<{ items: LeaveType[] }>("/leave/types")).data.items,
    enabled: open,
  });

  const { data: balances } = useQuery({
    queryKey: ["leave-balances", "self"],
    queryFn: async () => (await apiClient.get<{ items: BalanceItem[] }>("/leave/balances")).data.items,
    enabled: open,
  });

  const {
    register,
    handleSubmit,
    control,
    watch,
    reset,
    formState: { errors },
  } = useForm<ApplyForm>({
    resolver: zodResolver(applySchema),
    defaultValues: { duration_type: "full_day", start_date: "", end_date: "", leave_type_id: "", reason: "" },
  });

  useEffect(() => {
    if (open) reset({ duration_type: "full_day", start_date: "", end_date: "", leave_type_id: "", reason: "" });
  }, [open, reset]);

  const durationType = watch("duration_type");
  const selectedLeaveTypeId = watch("leave_type_id");
  const selectedBalance = balances?.find((b) => b.leave_type_id === selectedLeaveTypeId);

  const applyMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiClient.post("/leave/requests", payload),
    onSuccess: () => {
      toast.success("Leave request submitted");
      void qc.invalidateQueries({ queryKey: ["leave-requests"] });
      void qc.invalidateQueries({ queryKey: ["leave-balances"] });
      onClose();
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { message?: string; detail?: string } } })?.response?.data;
      toast.error(msg?.message || msg?.detail || "Couldn't submit leave request");
    },
  });

  function onSubmit(values: ApplyForm) {
    // Half-day/hourly are always single-day: derive end_date from start_date
    // rather than relying on a field the user doesn't see for those modes.
    const end_date = values.duration_type === "full_day" ? values.end_date : values.start_date;
    const payload: Record<string, unknown> = {
      leave_type_id: values.leave_type_id,
      start_date: values.start_date,
      end_date,
      duration_type: values.duration_type,
      reason: values.reason || "",
    };
    if (values.duration_type === "half_day") payload.half_day_period = values.half_day_period;
    if (values.duration_type === "hourly") payload.hours = Number(values.hours);
    applyMutation.mutate(payload);
  }

  if (!open) return null;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-xl bg-[hsl(var(--background))] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[hsl(var(--border))] px-6 py-4">
          <div className="flex items-center gap-2">
            <CalendarDays size={16} className="text-[hsl(var(--primary))]" />
            <h2 className="font-heading text-lg font-semibold">Apply for Leave</h2>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))] text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]"
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="max-h-[70vh] space-y-4 overflow-y-auto px-6 py-5">
          <div>
            <Label required htmlFor="leave_type_id">Leave Type</Label>
            <Select id="leave_type_id" {...register("leave_type_id")} error={!!errors.leave_type_id}>
              <option value="">Select a leave type…</option>
              {leaveTypes?.map((lt) => (
                <option key={lt.id} value={lt.id}>
                  {lt.name}
                </option>
              ))}
            </Select>
            <ErrorText>{errors.leave_type_id?.message}</ErrorText>
            {selectedBalance && (
              <p className="mt-1 text-xs text-[hsl(var(--foreground-muted))]">
                {selectedBalance.remaining_days} day(s) remaining
              </p>
            )}
          </div>

          <div>
            <Label required>Duration</Label>
            <div className="flex gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-1">
              {(
                [
                  { value: "full_day", label: "Full day(s)" },
                  { value: "half_day", label: "Half day" },
                  { value: "hourly", label: "Hourly" },
                ] as const
              ).map((opt) => (
                <label
                  key={opt.value}
                  className={cn(
                    "flex-1 cursor-pointer rounded-md px-3 py-1.5 text-center text-sm font-medium transition-colors",
                    durationType === opt.value
                      ? "bg-[hsl(var(--background))] shadow-[var(--shadow-xs)] text-[hsl(var(--foreground))]"
                      : "text-[hsl(var(--foreground-muted))] hover:text-[hsl(var(--foreground))]",
                  )}
                >
                  <input type="radio" value={opt.value} {...register("duration_type")} className="sr-only" />
                  {opt.label}
                </label>
              ))}
            </div>
          </div>

          <div className={cn("grid gap-3", durationType === "full_day" ? "grid-cols-2" : "grid-cols-1")}>
            <div>
              <Label required htmlFor="start_date">{durationType === "full_day" ? "Start Date" : "Date"}</Label>
              <Input id="start_date" type="date" {...register("start_date")} error={!!errors.start_date} />
              <ErrorText>{errors.start_date?.message}</ErrorText>
            </div>
            {durationType === "full_day" && (
              <div>
                <Label required htmlFor="end_date">End Date</Label>
                <Input id="end_date" type="date" {...register("end_date")} error={!!errors.end_date} />
                <ErrorText>{errors.end_date?.message}</ErrorText>
              </div>
            )}
          </div>

          {durationType === "half_day" && (
            <div>
              <Label required htmlFor="half_day_period">Which half?</Label>
              <Controller
                control={control}
                name="half_day_period"
                render={({ field }) => (
                  <Select id="half_day_period" {...field} value={field.value ?? ""} error={!!errors.half_day_period}>
                    <option value="">Select…</option>
                    <option value="morning">Morning</option>
                    <option value="afternoon">Afternoon</option>
                  </Select>
                )}
              />
              <ErrorText>{errors.half_day_period?.message}</ErrorText>
            </div>
          )}

          {durationType === "hourly" && (
            <div>
              <Label required htmlFor="hours">Hours</Label>
              <Input id="hours" type="number" step="0.5" min="0.5" placeholder="e.g. 2" {...register("hours")} error={!!errors.hours} />
              <ErrorText>{errors.hours?.message}</ErrorText>
            </div>
          )}

          <div>
            <Label htmlFor="reason">Reason</Label>
            <textarea
              id="reason"
              {...register("reason")}
              rows={3}
              placeholder="Optional — add context for your manager"
              className="w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-2 text-sm outline-none transition-colors placeholder:text-[hsl(var(--foreground-muted))] hover:border-[hsl(var(--border-strong))] focus:ring-2 focus:ring-[hsl(var(--ring))] focus:ring-offset-1"
            />
          </div>
        </form>

        <div className="flex items-center justify-end gap-2 border-t border-[hsl(var(--border))] px-6 py-4">
          <Button variant="outline" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button onClick={handleSubmit(onSubmit)} disabled={applyMutation.isPending}>
            {applyMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : null}
            Submit Request
          </Button>
        </div>
      </div>
    </>
  );
}