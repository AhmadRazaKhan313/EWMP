import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { toast } from "sonner";
import apiClient from "./api-client";
import { apiErrorMessage } from "./payroll.service";

// ═══ types ═════════════════════════════════════════════════════════════════
export type OfferStatus =
  | "draft" | "pending_approval" | "approved" | "sent" | "viewed"
  | "accepted" | "declined" | "expired" | "revoked" | "revised";

export interface OfferApproval { user_id: string; decision: "approved" | "rejected"; at: string; note: string }

export interface Offer {
  id: string;
  status: OfferStatus;
  version: number;
  parent_offer_id: string | null;
  candidate_name: string;
  candidate_email: string;
  candidate_phone: string | null;
  job_title: string;
  department_id: string | null;
  designation_id: string | null;
  branch_id: string | null;
  manager_id: string | null;
  template_id: string | null;
  employment_type: string;
  job_nature: string;
  salary: number | null;
  currency: string;
  pay_items: Record<string, unknown>[];
  joining_date: string;
  probation_months: number | null;
  expires_at: string | null;
  approver_ids: string[];
  approvals: OfferApproval[];
  sent_at: string | null;
  viewed_at: string | null;
  responded_at: string | null;
  decline_reason: string | null;
  accepted_name: string | null;
  employee_id: string | null;
  body?: string | null;
  history?: { id: string; version: number; status: OfferStatus }[];
  /** Only present in the response of send/resend: the secret link, shown once. */
  link?: string;
}

export interface OfferInput {
  candidate_name: string;
  candidate_email: string;
  candidate_phone?: string | null;
  job_title: string;
  department_id?: string | null;
  designation_id?: string | null;
  branch_id?: string | null;
  manager_id?: string | null;
  template_id?: string | null;
  employment_type?: string;
  job_nature?: string;
  salary?: number | null;
  currency?: string;
  joining_date: string;
  probation_months?: number | null;
  approver_ids?: string[];
  body?: string | null;
}

export type TaskStatus = "pending" | "in_progress" | "done" | "skipped";
export type OwnerRole = "hr" | "it" | "manager" | "employee";
export type TaskPhase = "pre_boarding" | "day_1" | "first_week" | "probation" | "exit";
export type TaskKind = "manual" | "document" | "form" | "acknowledge" | "provision";

export const OWNER_ROLES: { value: OwnerRole; label: string }[] = [
  { value: "hr", label: "HR" }, { value: "it", label: "IT" },
  { value: "manager", label: "Manager" }, { value: "employee", label: "New hire" },
];
export const PHASES: { value: TaskPhase; label: string }[] = [
  { value: "pre_boarding", label: "Before day 1" }, { value: "day_1", label: "Day 1" },
  { value: "first_week", label: "First week" }, { value: "probation", label: "Probation" },
  { value: "exit", label: "Exit" },
];
export const TASK_KINDS: { value: TaskKind; label: string }[] = [
  { value: "manual", label: "Manual" }, { value: "form", label: "Pre-boarding form" },
  { value: "document", label: "Documents" }, { value: "acknowledge", label: "Policy acknowledgement" },
  { value: "provision", label: "Provisioning (account, asset, ...)" },
];

export interface CaseTask {
  id: string;
  case_id: string;
  order: number;
  title: string;
  description: string | null;
  owner_role: OwnerRole;
  phase: TaskPhase;
  assignee_user_id: string | null;
  assignee_name: string | null;
  due_date: string | null;
  status: TaskStatus;
  is_required: boolean;
  kind: TaskKind;
  provision_key: string | null;
  link_url: string | null;
  notes: string | null;
  depends_on_id: string | null;
  blocked: boolean;
  overdue: boolean;
  completed_at: string | null;
}

export interface CaseDocument {
  id: string;
  document_type: string;
  title: string;
  is_required: boolean;
  status: "requested" | "uploaded" | "verified" | "rejected";
  rejection_reason: string | null;
  employee_document_id: string | null;
  uploaded_at: string | null;
}

export interface Progress { done: number; total: number; percent: number; overdue: number }

export interface OnboardingCase {
  id: string;
  kind: "onboarding" | "offboarding";
  status: "pre_boarding" | "active" | "completed" | "cancelled";
  employee: { id: string; employee_code: string | null; name: string; email: string | null; department_id: string | null };
  offer_id: string | null;
  template_id: string | null;
  anchor_date: string;
  days_until: number;
  manager_id: string | null;
  buddy_id: string | null;
  progress: Progress;
  preboarding_submitted_at: string | null;
  policy_ack_at: string | null;
  welcome_sent_at: string | null;
  completed_at: string | null;
  welcome_message?: string | null;
  tasks?: CaseTask[];
  documents?: CaseDocument[];
  preboarding_link?: string;
}

export interface TemplateTask {
  id?: string;
  order: number;
  title: string;
  description: string | null;
  owner_role: OwnerRole;
  phase: TaskPhase;
  due_offset_days: number;
  depends_on_order: number | null;
  is_required: boolean;
  kind: TaskKind;
  provision_key: string | null;
  link_url: string | null;
}

export interface Template {
  id: string;
  name: string;
  description: string | null;
  kind: "onboarding" | "offboarding";
  department_id: string | null;
  designation_id: string | null;
  branch_id: string | null;
  is_active: boolean;
  is_default: boolean;
  task_count?: number;
  tasks?: TemplateTask[];
}

export interface OnboardingDashboard {
  totals: {
    open_onboarding: number; open_offboarding: number; overdue_tasks: number;
    due_this_week: number; completed_this_month: number;
  };
  upcoming_joiners: OnboardingCase[];
  bottlenecks: {
    by_owner_role: { owner_role: string; overdue: number }[];
    by_task: { title: string; overdue: number }[];
    by_department: { department_id: string | null; department: string; overdue: number }[];
  };
}

export interface MyTask extends CaseTask {
  case: { id: string; kind: string; anchor_date: string; employee_id: string };
}

interface Page<T> { items: T[]; total: number; page: number; page_size: number }

// ═══ query keys ════════════════════════════════════════════════════════════
export const obKeys = {
  all: ["onboarding"] as const,
  dashboard: () => [...obKeys.all, "dashboard"] as const,
  offers: (f: object) => [...obKeys.all, "offers", f] as const,
  offer: (id: string) => [...obKeys.all, "offer", id] as const,
  templates: (kind?: string) => [...obKeys.all, "templates", kind ?? "all"] as const,
  template: (id: string) => [...obKeys.all, "template", id] as const,
  cases: (f: object) => [...obKeys.all, "cases", f] as const,
  case: (id: string) => [...obKeys.all, "case", id] as const,
  mine: (done: boolean) => [...obKeys.all, "mine", done] as const,
};

const BASE = "/onboarding";

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: obKeys.all });
}

function useAction<TVars, TOut>(
  fn: (v: TVars) => Promise<TOut>,
  opts: { success?: string; error: string },
) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      invalidate();
      if (opts.success) toast.success(opts.success);
    },
    onError: (err: unknown) => toast.error(apiErrorMessage(err, opts.error)),
  });
}

// ═══ dashboard ═════════════════════════════════════════════════════════════
export function useOnboardingDashboard() {
  return useQuery({
    queryKey: obKeys.dashboard(),
    queryFn: async () => (await apiClient.get<OnboardingDashboard>(`${BASE}/dashboard`)).data,
  });
}

// ═══ offers ════════════════════════════════════════════════════════════════
export function useOffers(f: { status?: string; search?: string; page?: number; page_size?: number }) {
  return useQuery({
    queryKey: obKeys.offers(f),
    queryFn: async () => (await apiClient.get<Page<Offer>>(`${BASE}/offers`, { params: f })).data,
  });
}

export function useOffer(id: string) {
  return useQuery({
    queryKey: obKeys.offer(id),
    queryFn: async () => (await apiClient.get<Offer>(`${BASE}/offers/${id}`)).data,
    enabled: !!id,
  });
}

export const useCreateOffer = () =>
  useAction((v: OfferInput) => apiClient.post<Offer>(`${BASE}/offers`, v).then((r) => r.data),
    { success: "Offer saved as a draft", error: "Could not save the offer" });

export const useUpdateOffer = (id: string) =>
  useAction((v: Partial<OfferInput>) => apiClient.patch<Offer>(`${BASE}/offers/${id}`, v).then((r) => r.data),
    { success: "Offer updated", error: "Could not update the offer" });

export const useDeleteOffer = () =>
  useAction((id: string) => apiClient.delete(`${BASE}/offers/${id}`).then(() => id),
    { success: "Draft deleted", error: "Could not delete the offer" });

export const useSubmitOffer = (id: string) =>
  useAction<void, Offer>(() => apiClient.post<Offer>(`${BASE}/offers/${id}/submit`).then((r) => r.data),
    { success: "Offer submitted", error: "Could not submit the offer" });

export const useDecideOffer = (id: string) =>
  useAction((v: { decision: "approved" | "rejected"; note?: string }) =>
    apiClient.post<Offer>(`${BASE}/offers/${id}/decision`, v).then((r) => r.data),
    { success: "Decision recorded", error: "Could not record your decision" });

export const useSendOffer = (id: string) =>
  useAction((v: { valid_days?: number } = {}) =>
    apiClient.post<Offer>(`${BASE}/offers/${id}/send`, v).then((r) => r.data),
    { success: "Offer sent", error: "Could not send the offer" });

export const useRevokeOffer = (id: string) =>
  useAction<void, Offer>(() => apiClient.post<Offer>(`${BASE}/offers/${id}/revoke`).then((r) => r.data),
    { success: "Offer withdrawn", error: "Could not withdraw the offer" });

export const useReviseOffer = (id: string) =>
  useAction((v: Partial<OfferInput>) => apiClient.post<Offer>(`${BASE}/offers/${id}/revise`, v).then((r) => r.data),
    { success: "New version created", error: "Could not revise the offer" });

export const useConvertOffer = (id: string) =>
  useAction((v: { role_id: string; first_name?: string; last_name?: string; template_id?: string; manager_id?: string; buddy_id?: string }) =>
    apiClient.post<{ employee_id: string; employee_code: string; temporary_password: string | null; case: OnboardingCase }>(
      `${BASE}/offers/${id}/convert`, v).then((r) => r.data),
    { success: "Employee created and onboarding started", error: "Could not convert the offer" });

// ═══ templates ═════════════════════════════════════════════════════════════
export function useTemplates(kind?: "onboarding" | "offboarding") {
  return useQuery({
    queryKey: obKeys.templates(kind),
    queryFn: async () => (await apiClient.get<{ items: Template[] }>(`${BASE}/templates`, { params: { kind } })).data.items,
  });
}

export function useTemplate(id: string) {
  return useQuery({
    queryKey: obKeys.template(id),
    queryFn: async () => (await apiClient.get<Template>(`${BASE}/templates/${id}`)).data,
    enabled: !!id && id !== "new",
  });
}

export const useSeedTemplates = () =>
  useAction<void, unknown>(() => apiClient.post(`${BASE}/templates/defaults`).then((r) => r.data),
    { success: "Default templates added", error: "Could not add the default templates" });

export const useSaveTemplate = (id: string | null) =>
  useAction((v: Partial<Template> & { tasks?: TemplateTask[] }) =>
    (id ? apiClient.patch<Template>(`${BASE}/templates/${id}`, v) : apiClient.post<Template>(`${BASE}/templates`, v))
      .then((r) => r.data),
    { success: "Template saved", error: "Could not save the template" });

export const useDeleteTemplate = () =>
  useAction((id: string) => apiClient.delete(`${BASE}/templates/${id}`).then(() => id),
    { success: "Template deleted", error: "Could not delete the template" });

// ═══ cases ═════════════════════════════════════════════════════════════════
export interface CaseFilters { kind?: string; status?: string; search?: string; overdue?: boolean; employee_id?: string; page?: number; page_size?: number }

export function useCases(f: CaseFilters) {
  return useQuery({
    queryKey: obKeys.cases(f),
    queryFn: async () => (await apiClient.get<Page<OnboardingCase>>(`${BASE}/cases`, { params: f })).data,
  });
}

export function useCase(id: string) {
  return useQuery({
    queryKey: obKeys.case(id),
    queryFn: async () => (await apiClient.get<OnboardingCase>(`${BASE}/cases/${id}`)).data,
    enabled: !!id,
  });
}

export const useCreateCase = () =>
  useAction((v: { employee_id: string; kind: string; template_id?: string; anchor_date?: string; manager_id?: string; buddy_id?: string }) =>
    apiClient.post<OnboardingCase>(`${BASE}/cases`, v).then((r) => r.data),
    { success: "Checklist started", error: "Could not start the checklist" });

export const useUpdateCase = (id: string) =>
  useAction((v: { manager_id?: string | null; buddy_id?: string | null; anchor_date?: string; welcome_message?: string | null }) =>
    apiClient.patch<OnboardingCase>(`${BASE}/cases/${id}`, v).then((r) => r.data),
    { success: "Saved", error: "Could not save the changes" });

export const useCancelCase = (id: string) =>
  useAction<void, OnboardingCase>(() => apiClient.post<OnboardingCase>(`${BASE}/cases/${id}/cancel`).then((r) => r.data),
    { success: "Checklist cancelled", error: "Could not cancel" });

export const useSendWelcome = (id: string) =>
  useAction((message: string | null) =>
    apiClient.post<OnboardingCase>(`${BASE}/cases/${id}/welcome`, { message }).then((r) => r.data),
    { success: "Welcome message sent", error: "Could not send the welcome message" });

export const useConfirmCase = (id: string) =>
  useAction((v: { confirmed_on?: string; note?: string }) =>
    apiClient.post<OnboardingCase>(`${BASE}/cases/${id}/confirm`, v).then((r) => r.data),
    { success: "Employee confirmed", error: "Could not confirm the employee" });

export const useNewPreboardingLink = (id: string) =>
  useAction<void, { link: string }>(() => apiClient.post<{ link: string }>(`${BASE}/cases/${id}/preboarding-link`).then((r) => r.data),
    { success: "New link created", error: "Could not create a new link" });

export const useRequestDocument = (id: string) =>
  useAction((v: { document_type: string; title: string; is_required: boolean }) =>
    apiClient.post<CaseDocument>(`${BASE}/cases/${id}/documents`, v).then((r) => r.data),
    { success: "Document requested", error: "Could not request the document" });

export const useReviewDocument = () =>
  useAction((v: { id: string; approve: boolean; reason?: string }) =>
    apiClient.post<CaseDocument>(`${BASE}/documents/${v.id}/review`, { approve: v.approve, reason: v.reason }).then((r) => r.data),
    { error: "Could not save the review" });

// ═══ tasks ═════════════════════════════════════════════════════════════════
export function useMyTasks(includeDone = false) {
  return useQuery({
    queryKey: obKeys.mine(includeDone),
    queryFn: async () => (await apiClient.get<{ items: MyTask[] }>(`${BASE}/tasks/mine`, { params: { include_done: includeDone } })).data.items,
  });
}

export const useUpdateTask = () =>
  useAction((v: { id: string; status?: TaskStatus; notes?: string | null; assignee_user_id?: string | null; due_date?: string }) => {
    const { id, ...body } = v;
    return apiClient.patch<CaseTask>(`${BASE}/tasks/${id}`, body).then((r) => r.data);
  }, { error: "Could not update the task" });

// ═══ public pages (no login): a clean client that never sends credentials ══
const publicClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1",
  timeout: 30_000,
});

export interface PublicOffer {
  company_name: string;
  candidate_name: string;
  job_title: string;
  joining_date: string;
  salary: number | null;
  currency: string;
  pay_items: Record<string, unknown>[];
  body: string | null;
  status: OfferStatus;
  expires_at: string | null;
  can_respond: boolean;
}

export const publicOfferApi = {
  get: async (token: string) => (await publicClient.get<PublicOffer>(`/public/offers/${token}`)).data,
  accept: async (token: string, full_name: string, agree: boolean) =>
    (await publicClient.post<PublicOffer>(`/public/offers/${token}/accept`, { full_name, agree })).data,
  decline: async (token: string, reason: string) =>
    (await publicClient.post<PublicOffer>(`/public/offers/${token}/decline`, { reason })).data,
};

export interface EmergencyContact { name: string; phone: string; relationship?: string }

export interface PreboardingView {
  company_name: string;
  first_name: string;
  joining_date: string;
  submitted: boolean;
  policy_acknowledged: boolean;
  form: Record<string, unknown> & { emergency_contacts?: EmergencyContact[] };
  documents: CaseDocument[];
  required_fields: string[];
}

export const preboardingApi = {
  get: async (token: string) => (await publicClient.get<PreboardingView>(`/public/preboarding/${token}`)).data,
  save: async (token: string, body: { form: Record<string, unknown>; submit: boolean; acknowledge_policy: boolean }) =>
    (await publicClient.put<PreboardingView>(`/public/preboarding/${token}`, body)).data,
  upload: async (token: string, docId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return (await publicClient.post<CaseDocument>(`/public/preboarding/${token}/documents/${docId}`, fd)).data;
  },
};

export { apiErrorMessage };

// ═══ lookups for the forms (departments / designations as the rest of the app reads them) ═══
interface Named { id: string; name: string }
const asList = (d: unknown): Named[] =>
  Array.isArray(d) ? (d as Named[]) : ((d as { items?: Named[] } | null)?.items ?? []);

export function useDepartmentOptions() {
  return useQuery({ queryKey: ["onboarding", "lookup", "departments"], queryFn: async () => asList((await apiClient.get("/departments")).data) });
}
export function useDesignationOptions() {
  return useQuery({ queryKey: ["onboarding", "lookup", "designations"], queryFn: async () => asList((await apiClient.get("/designations")).data) });
}
