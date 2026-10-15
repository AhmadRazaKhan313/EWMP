"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormProvider, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight, CheckCircle2, Copy, Loader2, UserPlus, X } from "lucide-react";
import apiClient from "@/services/api-client";
import { useAuthStore } from "@/store/auth.store";
import { useUploadEmployeeDocument, type DocumentType } from "@/services/employeeDocuments.service";
import { Button, EmptyState, PageHeader } from "@/components/atoms";
import { ChecklistPanel, ProgressBar, Stepper } from "./Progress";
import { EmergencyStep, PayStep, PersonalStep, RoleStep, useWizardOptions } from "./Steps";
import { DocumentsStep, type DocStatus } from "./DocumentsStep";
import { ReviewStep } from "./ReviewStep";
import {
  DEFAULT_VALUES, FIELD_STEP, LAST_STEP, STEPS, buildCreatePayload, buildFollowUpPatch, crossFieldErrors,
  employeeWizardSchema, fieldsOfStep, firstStepWithError, serverFieldErrors, serverMessage,
  type EmployeeWizardValues, type StagedDoc,
} from "./wizard";

function showTemporaryPassword(password: string) {
  toast.custom(
    (id) => (
      <div className="flex items-center gap-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-3 shadow-[var(--shadow-md)]">
        <div className="text-sm">
          <p className="font-medium">Employee added</p>
          <p className="text-[hsl(var(--foreground-muted))]">
            Temporary password: <span className="font-mono font-semibold text-[hsl(var(--foreground))]">{password}</span>
          </p>
        </div>
        <button
          onClick={() => { void navigator.clipboard.writeText(password); toast.success("Password copied", { duration: 2000 }); }}
          title="Copy password" aria-label="Copy password"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[hsl(var(--border))] hover:bg-[hsl(var(--accent))]"
        >
          <Copy size={14} />
        </button>
        <button onClick={() => toast.dismiss(id)} title="Dismiss" aria-label="Dismiss"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md hover:bg-[hsl(var(--accent))]">
          <X size={14} />
        </button>
      </div>
    ),
    { duration: Infinity },
  );
}

export function EmployeeWizard() {
  const router = useRouter();
  const qc = useQueryClient();
  const canCreate = useAuthStore((s) => s.hasPermission("employees.create"));
  const options = useWizardOptions();
  const uploadDoc = useUploadEmployeeDocument();

  const methods = useForm<EmployeeWizardValues>({
    resolver: zodResolver(employeeWizardSchema),
    defaultValues: DEFAULT_VALUES,
    mode: "onTouched",
  });
  const { trigger, getValues, setError, formState: { isDirty } } = methods;

  const [step, setStep] = useState(0);
  const [reached, setReached] = useState(0);
  const [docs, setDocs] = useState<StagedDoc[]>([]);
  const [docStatus, setDocStatus] = useState<Record<string, DocStatus>>({});
  const [submitting, setSubmitting] = useState(false);

  // Set the moment the server confirms the employee. After that a retry must
  // never POST again (that would try to create a duplicate); it only finishes
  // the follow-up work that failed.
  const [createdId, setCreatedId] = useState<string | null>(null);
  const createdRef = useRef<string | null>(null);
  const patchDone = useRef(false);
  const busy = useRef(false); // synchronous guard: state updates are too late for a fast double click
  const topRef = useRef<HTMLDivElement>(null);

  const dirty = (isDirty || docs.length > 0) && !createdId;
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function confirmLeave(): boolean {
    return !dirty || window.confirm("Leave without creating this employee? What you entered will be lost.");
  }
  function leave(e?: React.MouseEvent) {
    if (!confirmLeave()) { e?.preventDefault(); return; }
    if (!e) router.push("/employees");
  }

  function show(i: number) {
    setStep(i);
    setReached((r) => Math.max(r, i));
    topRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }

  /** Validates one step; shows inline errors and focuses the first bad field. */
  async function validateStep(i: number): Promise<boolean> {
    const id = STEPS[i]!.id;
    const ok = await trigger(fieldsOfStep(id), { shouldFocus: true });
    const cross = crossFieldErrors(getValues()).filter((e) => FIELD_STEP[e.field] === id);
    cross.forEach((e) => setError(e.field, { type: "custom", message: e.message }, { shouldFocus: true }));
    return ok && cross.length === 0;
  }

  async function next() {
    if (step >= LAST_STEP) return;
    if (await validateStep(step)) show(step + 1);
  }

  async function goTo(i: number) {
    if (i === step || i > reached) return;
    // Going forward over a step the user is still on must not skip its rules.
    if (i > step && !(await validateStep(step))) return;
    show(i);
  }

  function failedUploads() {
    return docs.filter((d) => docStatus[d.id] === "failed").length;
  }

  async function create() {
    if (busy.current) return;
    busy.current = true;
    setSubmitting(true);
    try {
      if (!createdRef.current) {
        const ok = await trigger();
        const cross = crossFieldErrors(getValues());
        cross.forEach((e) => setError(e.field, { type: "custom", message: e.message }));
        if (!ok || cross.length) {
          const bad = [...Object.keys(methods.formState.errors), ...cross.map((c) => c.field)];
          const at = firstStepWithError(bad);
          toast.error("Some information is missing or invalid. Please fix it and try again.");
          if (at >= 0) {
            show(at);
            // the step has to be visible before its field can take focus
            setTimeout(() => void trigger(fieldsOfStep(STEPS[at]!.id), { shouldFocus: true }), 60);
          }
          return;
        }
        try {
          const res = await apiClient.post("/employees", buildCreatePayload(getValues()));
          const id = res.data?.id as string | undefined;
          if (!id) throw new Error("The server did not return the new employee's id");
          createdRef.current = id;
          setCreatedId(id);
          void qc.invalidateQueries({ queryKey: ["employees"] });
          void qc.invalidateQueries({ queryKey: ["employee-stats"] });
          const pw = res.data?.temporary_password as string | undefined;
          if (pw) showTemporaryPassword(pw); else toast.success("Employee added successfully");
        } catch (err) {
          // Nothing was saved. Keep every value, tell the user why, and take
          // them to the step the server complained about, if it named one.
          const fields = serverFieldErrors(err);
          fields.forEach((f) => setError(f.field, { type: "server", message: f.message }));
          const at = firstStepWithError(fields.map((f) => f.field));
          if (at >= 0) show(at);
          const status = (err as { response?: { status?: number } })?.response?.status;
          const msg = serverMessage(err);
          toast.error(
            msg ||
            (!status
              ? "The server didn't respond in time. The employee may already have been created — check the employee list before trying again."
              : status === 403 ? "You don't have permission to create employees."
              : "Couldn't create the employee. Your entries are kept — please try again."),
          );
          if (!status) void qc.invalidateQueries({ queryKey: ["employees"] });
          return;
        }
      }

      const id = createdRef.current!;

      // The create call doesn't store these three; the update endpoint does.
      const patch = buildFollowUpPatch(getValues());
      let patchFailed = false;
      if (patch && !patchDone.current) {
        try { await apiClient.patch(`/employees/${id}`, patch); patchDone.current = true; }
        catch { patchFailed = true; }
      } else patchDone.current = true;

      let failed = 0;
      for (const d of docs) {
        if (docStatus[d.id] === "done") continue;
        setDocStatus((s) => ({ ...s, [d.id]: "uploading" }));
        try {
          await uploadDoc.mutateAsync({
            employeeId: id, file: d.file, documentType: d.document_type as DocumentType,
            title: d.title, expiryDate: d.expiry_date, notes: d.notes,
          });
          setDocStatus((s) => ({ ...s, [d.id]: "done" }));
        } catch {
          failed++;
          setDocStatus((s) => ({ ...s, [d.id]: "failed" }));
        }
      }

      if (failed === 0 && !patchFailed) {
        if (docs.length) toast.success(`${docs.length} document${docs.length > 1 ? "s" : ""} uploaded`);
        router.push(`/employees/${id}`);
        return;
      }
      toast.error(
        [
          patchFailed ? "Nationality, blood group or emergency contact couldn't be saved — add them from the employee's profile." : "",
          failed ? `${failed} document${failed > 1 ? "s" : ""} failed to upload.` : "",
        ].filter(Boolean).join(" "),
      );
    } finally {
      busy.current = false;
      setSubmitting(false);
    }
  }

  const values = methods.watch();
  const options_ = options;

  if (!canCreate) {
    return (
      <EmptyState icon={UserPlus} title="You can't add employees"
        description="Your account doesn't have permission to create employees. Ask an administrator for access."
        action={<Button onClick={() => router.push("/employees")}>Back to employees</Button>} />
    );
  }

  const meta = STEPS[step]!;
  const isLast = step === LAST_STEP;
  const retryable = !!createdId && (failedUploads() > 0 || docs.some((d) => docStatus[d.id] !== "done"));

  return (
    <div className="space-y-6" ref={topRef}>
      <PageHeader
        breadcrumb={
          <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-sm text-[hsl(var(--foreground-muted))]">
            <Link href="/employees" onClick={leave} className="hover:text-[hsl(var(--foreground))]">Employees</Link>
            <span aria-hidden>/</span>
            <span aria-current="page" className="font-medium text-[hsl(var(--foreground-subtle))]">Add Employee</span>
          </nav>
        }
        title="Add New Employee"
        description="Set up a new team member in a few simple steps."
        action={<Button variant="secondary" onClick={() => leave()} icon={<X size={15} className="mr-1.5" />}>Cancel</Button>}
      />

      <FormProvider {...methods}>
        <form
          onSubmit={(e) => { e.preventDefault(); if (isLast) void create(); else void next(); }}
          noValidate
          className="mx-auto max-w-6xl overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] shadow-[var(--shadow-xs)]"
        >
          <div className="space-y-5 border-b border-[hsl(var(--border))] px-5 py-6 sm:px-8">
            <Stepper current={step} reached={reached} onGo={(i) => void goTo(i)} />
            <ProgressBar current={step} />
          </div>

          <div className="grid grid-cols-1 gap-8 px-5 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_280px]">
            <section aria-labelledby="step-title" className="min-w-0">
              <h2 id="step-title" className="font-heading text-xl font-semibold text-[hsl(var(--foreground))]">{meta.title}</h2>
              <p className="mb-6 mt-1 text-sm text-[hsl(var(--foreground-muted))]">{meta.subtitle}</p>

              {/* All steps stay mounted so no value is ever lost; only the active one is shown. */}
              <div hidden={meta.id !== "personal"}><PersonalStep /></div>
              <div hidden={meta.id !== "role"}><RoleStep options={options_} /></div>
              <div hidden={meta.id !== "pay"}><PayStep /></div>
              <div hidden={meta.id !== "emergency"}><EmergencyStep /></div>
              <div hidden={meta.id !== "documents"}>
                <DocumentsStep
                  docs={docs} status={docStatus} locked={!!createdId}
                  onAdd={(d) => setDocs((p) => [...p, d])}
                  onRemove={(id) => setDocs((p) => p.filter((d) => d.id !== id))}
                />
              </div>
              {meta.id === "review" && (
                <ReviewStep
                  values={values} docs={docs} options={options_}
                  onEdit={(i) => void goTo(i)}
                  createdNotice={createdId ? (
                    <div role="status" className="flex items-start gap-3 rounded-xl border border-[hsl(var(--success))]/40 bg-[hsl(var(--success-subtle))] p-4">
                      <CheckCircle2 size={18} aria-hidden className="mt-0.5 shrink-0 text-[hsl(var(--success))]" />
                      <div className="text-sm">
                        <p className="font-semibold">Employee created</p>
                        <p className="text-[hsl(var(--foreground-subtle))]">
                          The profile exists, but some follow-up steps didn&apos;t finish. Retry them below, or open the profile and finish there. Don&apos;t create the employee again.
                        </p>
                      </div>
                    </div>
                  ) : null}
                />
              )}
            </section>

            <ChecklistPanel current={step} reached={reached} onGo={(i) => void goTo(i)} />
          </div>

          {/* Action bar */}
          <div className="sticky bottom-0 z-10 flex items-center justify-between gap-3 border-t border-[hsl(var(--border))] bg-[hsl(var(--background))]/95 px-5 py-4 backdrop-blur sm:px-8">
            <p className="hidden text-xs text-[hsl(var(--foreground-muted))] sm:block" aria-live="polite">
              {createdId ? "Employee created" : `Step ${step + 1} of ${STEPS.length}`}
            </p>
            <div className="ml-auto flex items-center gap-3">
              {createdId ? (
                <>
                  <Button variant="secondary" onClick={() => router.push(`/employees/${createdId}`)}>Open employee profile</Button>
                  {retryable && (
                    <Button onClick={() => void create()} disabled={submitting}
                      icon={submitting ? <Loader2 size={15} className="mr-2 animate-spin" /> : undefined}>
                      {submitting ? "Retrying…" : "Retry failed steps"}
                    </Button>
                  )}
                </>
              ) : (
                <>
                  <Button variant="secondary" onClick={() => show(step - 1)} disabled={step === 0 || submitting}
                    icon={<ArrowLeft size={15} className="mr-2" />}>Previous</Button>
                  {isLast ? (
                    <Button type="submit" disabled={submitting}
                      icon={submitting ? <Loader2 size={15} className="mr-2 animate-spin" /> : <UserPlus size={15} className="mr-2" />}>
                      {submitting ? "Creating…" : docs.length ? `Create employee & upload ${docs.length} doc${docs.length > 1 ? "s" : ""}` : "Create employee"}
                    </Button>
                  ) : (
                    <Button type="submit" disabled={submitting}>
                      Next step <ArrowRight size={15} className="ml-2" />
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>
        </form>
      </FormProvider>
    </div>
  );
}
