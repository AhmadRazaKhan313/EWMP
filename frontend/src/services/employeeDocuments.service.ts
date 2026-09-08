import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./api-client";

export type DocumentType =
  | "national_id"
  | "passport"
  | "visa_work_permit"
  | "employment_contract"
  | "educational_certificate"
  | "professional_certificate"
  | "experience_letter"
  | "resume_cv"
  | "bank_document"
  | "tax_document"
  | "medical_record"
  | "police_clearance"
  | "nda_agreement"
  | "photo"
  | "other";

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  national_id: "National ID / CNIC",
  passport: "Passport",
  visa_work_permit: "Visa / Work Permit",
  employment_contract: "Employment Contract",
  educational_certificate: "Educational Certificate",
  professional_certificate: "Professional Certificate",
  experience_letter: "Experience Letter",
  resume_cv: "Resume / CV",
  bank_document: "Bank Document",
  tax_document: "Tax Document",
  medical_record: "Medical Record",
  police_clearance: "Police Clearance",
  nda_agreement: "NDA / Agreement",
  photo: "Photo",
  other: "Other",
};

export interface EmployeeDocument {
  id: string;
  employee_id: string;
  document_type: DocumentType;
  title: string;
  notes: string | null;
  original_file_name: string;
  mime_type: string;
  file_size_bytes: number;
  expiry_date: string | null;
  is_expired: boolean;
  days_until_expiry: number | null;
  is_locked: boolean;
  uploaded_by_id: string | null;
  created_at: string;
}

export interface UploadDocumentInput {
  employeeId: string;
  file: File;
  documentType: DocumentType;
  title: string;
  expiryDate?: string;
  notes?: string;
}

export const employeeDocumentKeys = {
  all: ["employee-documents"] as const,
  list: (employeeId: string) => [...employeeDocumentKeys.all, employeeId] as const,
};

async function fetchDocuments(employeeId: string) {
  const { data } = await apiClient.get<{ items: EmployeeDocument[]; total: number }>(
    `/employees/${employeeId}/documents`,
  );
  return data;
}

export function useEmployeeDocuments(employeeId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: employeeDocumentKeys.list(employeeId ?? ""),
    queryFn: () => fetchDocuments(employeeId as string),
    enabled: !!employeeId && enabled,
  });
}

export function useUploadEmployeeDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: UploadDocumentInput) => {
      const form = new FormData();
      form.append("file", input.file);
      form.append("document_type", input.documentType);
      form.append("title", input.title);
      if (input.expiryDate) form.append("expiry_date", input.expiryDate);
      if (input.notes) form.append("notes", input.notes);

      const { data } = await apiClient.post<EmployeeDocument>(
        `/employees/${input.employeeId}/documents`,
        form,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      return data;
    },
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: employeeDocumentKeys.list(variables.employeeId) });
    },
  });
}

export function useDeleteEmployeeDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ employeeId, documentId }: { employeeId: string; documentId: string }) => {
      await apiClient.delete(`/employees/${employeeId}/documents/${documentId}`);
    },
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: employeeDocumentKeys.list(variables.employeeId) });
    },
  });
}

export async function downloadEmployeeDocument(
  employeeId: string,
  documentId: string,
  fileName: string,
) {
  const response = await apiClient.get(
    `/employees/${employeeId}/documents/${documentId}/download`,
    { responseType: "blob" },
  );
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
